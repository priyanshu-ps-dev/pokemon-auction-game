"""
Player-Controlled Live Battle Session (Phase 5)
===============================================
Supports three battle-control modes:
- 'ai_vs_ai'
- 'player_vs_ai'
- 'player_vs_player'

Server-authoritative turn resolution:
- Validates all submitted actions (attack, switch, transform)
- Rejects illegal moves and duplicate submissions in the same turn
- Hides opponent's pending action until both sides submit or timeout
- Falls back to TacticalBattleAI on timeout or disconnect
"""

import asyncio
import random
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from src.anime_battle_engine import AnimeBattleSimulator, AnimeCombatant
from src.battle_ai import TacticalBattleAI
from src.battle_engine import PokemonBattleSimulator, PokemonCombatant
from src.marvel_battle_engine import MarvelBattleSimulator, MarvelCombatant
from src.battle_interface import BattleAction, BattleResult
from src.cross_universe_adapter import CrossUniverseBattleSimulator


class LiveBattleSession:
    """Interactive turn-by-turn battle coordinator."""

    def __init__(
        self,
        player_a_id: str,
        team_a: List[Any],
        player_b_id: str,
        team_b: List[Any],
        control_mode: str = "ai_vs_ai",
        seed: int = 42,
        turn_timeout_seconds: float = 20.0,
        images_by_id: Optional[Dict[str, str]] = None,
        match_id: str = "",
    ):
        self.player_a_id = player_a_id
        self.player_b_id = player_b_id
        self.control_mode = control_mode if control_mode in ("ai_vs_ai", "player_vs_ai", "player_vs_player") else "ai_vs_ai"
        self.seed = seed
        self.rng = random.Random(seed)
        self.turn_timeout_seconds = turn_timeout_seconds
        self.ai = TacticalBattleAI()
        self.images_by_id = images_by_id or {}
        self.match_id = match_id
        self.is_invalidated: bool = False

        self.teams: Dict[str, List[Any]] = {
            player_a_id: list(team_a),
            player_b_id: list(team_b),
        }
        self.active_idx: Dict[str, int] = {player_a_id: 0, player_b_id: 0}
        self.turn_number: int = 0
        self.pending_actions: Dict[str, BattleAction] = {}
        self.turn_ready_event: asyncio.Event = asyncio.Event()
        self.turn_log: List[Dict[str, Any]] = []

        # Determine native/cross simulator helper for damage resolution
        sys_set = {c.system for c in team_a + team_b}
        if sys_set == {"pokemon"}:
            self._engine_kind = "pokemon"
            self._pkmn_sim = PokemonBattleSimulator(player_a_id, team_a, player_b_id, team_b, seed=seed, ai_selector=self.ai)
        elif sys_set == {"anime"}:
            self._engine_kind = "anime"
            self._anime_sim = AnimeBattleSimulator(player_a_id, team_a, player_b_id, team_b, seed=seed, ai_selector=self.ai)
        elif sys_set == {"marvel"}:
            self._engine_kind = "marvel"
            self._marvel_sim = MarvelBattleSimulator(player_a_id, team_a, player_b_id, team_b, seed=seed, ai_selector=self.ai)
        else:
            self._engine_kind = "cross"
            self._cross_sim = CrossUniverseBattleSimulator(player_a_id, team_a, player_b_id, team_b, seed=seed, ai_selector=self.ai, images_by_id=self.images_by_id)

    def invalidate(self):
        """Invalidates this session so stale events or pending waits terminate immediately."""
        self.is_invalidated = True
        self.pending_actions.clear()
        self.turn_ready_event.set()

    def is_human_controlled(self, pid: str) -> bool:
        if self.control_mode == "player_vs_player":
            return pid in (self.player_a_id, self.player_b_id)
        if self.control_mode == "player_vs_ai":
            return pid == self.player_a_id
        return False

    def get_active(self, pid: str) -> Optional[Any]:
        team = self.teams[pid]
        idx = self.active_idx[pid]
        if 0 <= idx < len(team) and not team[idx].is_fainted:
            return team[idx]
        for i, c in enumerate(team):
            if not c.is_fainted:
                self.active_idx[pid] = i
                return c
        return None

    def remaining_count(self, pid: str) -> int:
        return sum(1 for c in self.teams[pid] if not c.is_fainted)

    def remaining_hp(self, pid: str) -> int:
        return sum(max(0, c.current_hp) for c in self.teams[pid])

    def build_player_prompt(self, pid: str) -> Dict[str, Any]:
        """Builds private turn options for `pid` without exposing opponent's pending action."""
        active = self.get_active(pid)
        opp_id = self.player_b_id if pid == self.player_a_id else self.player_a_id
        opp = self.get_active(opp_id)
        team = self.teams[pid]

        moves = []
        if active:
            for m in active.get_available_moves():
                moves.append({
                    "id": m["id"],
                    "name": m["name"],
                    "type": m.get("type") or m.get("element_or_energy_type") or "Standard",
                    "category": m.get("category", "unknown"),
                    "power": m.get("power"),
                    "pp": m.get("current_pp"),
                    "max_pp": m.get("pp"),
                })

        switches = [
            {"index": idx, "name": c.name, "current_hp": c.current_hp, "max_hp": c.max_hp, "status": c.status}
            for idx, c in enumerate(team)
            if not c.is_fainted and c is not active
        ]

        transforms = [
            {"id": t["id"], "name": t["name"]}
            for t in (active.get_available_transformations() if active else [])
        ]

        return {
            "match_id": self.match_id,
            "turn": self.turn_number,
            "side": "a" if pid == self.player_a_id else "b",
            "control_mode": self.control_mode,
            "timeout_seconds": self.turn_timeout_seconds,
            "your_active": active.to_summary_dict() if active else None,
            "opponent_active": opp.to_summary_dict() if opp else None,
            "your_remaining": self.remaining_count(pid),
            "opponent_remaining": self.remaining_count(opp_id),
            "available_moves": moves,
            "available_switches": switches,
            "available_transformations": transforms,
            "opponent_submitted": opp_id in self.pending_actions,
        }

    def submit_action(self, pid: str, raw_action: dict) -> Tuple[bool, str]:
        """Server-authoritative validation of a player's turn action."""
        if self.is_invalidated:
            return False, "This battle session has ended."
        req_match_id = raw_action.get("match_id")
        if req_match_id and self.match_id and str(req_match_id) != str(self.match_id):
            return False, "Stale battle action from a previous match rejected."
        if not self.is_human_controlled(pid):
            return False, "This side is AI-controlled."
        if pid in self.pending_actions:
            return False, "Duplicate turn submission rejected."

        active = self.get_active(pid)
        if not active:
            return False, "No active combatant remaining."

        atype = str(raw_action.get("action_type", "")).lower()
        if atype == "attack":
            move_id = raw_action.get("move_id")
            avail = active.get_available_moves()
            if not any(str(m["id"]) == str(move_id) for m in avail):
                return False, "Illegal or unavailable move selected."
            # Preserve exact typed ID
            matched = next(m for m in avail if str(m["id"]) == str(move_id))
            self.pending_actions[pid] = BattleAction(action_type="attack", move_id=matched["id"])

        elif atype == "switch":
            try:
                idx = int(raw_action.get("switch_index"))
            except (TypeError, ValueError):
                return False, "Invalid switch index."
            team = self.teams[pid]
            if not (0 <= idx < len(team)) or team[idx].is_fainted or team[idx] is active:
                return False, "Cannot switch to fainted or already active combatant."
            self.pending_actions[pid] = BattleAction(action_type="switch", switch_index=idx)

        elif atype == "transform":
            tf_id = str(raw_action.get("transformation_id", ""))
            avail_tfs = active.get_available_transformations()
            if not any(t["id"] == tf_id for t in avail_tfs):
                return False, "Transformation is not available for this combatant."
            self.pending_actions[pid] = BattleAction(action_type="transform", transformation_id=tf_id)

        else:
            return False, f"Unsupported action_type: {atype}"

        # Check if all human players have now submitted
        humans = [p for p in (self.player_a_id, self.player_b_id) if self.is_human_controlled(p)]
        if all(h in self.pending_actions for h in humans):
            self.turn_ready_event.set()
        return True, "Action accepted."

    def _ai_fallback(self, pid: str, opp_id: str) -> BattleAction:
        active = self.get_active(pid)
        opp = self.get_active(opp_id)
        if not active or not opp:
            return BattleAction(action_type="pass")
        if isinstance(active, PokemonCombatant):
            return self.ai.choose_pokemon_action(active, self.teams[pid], opp, self.rng)
        if isinstance(active, MarvelCombatant):
            return self.ai.choose_marvel_action(active, opp, self.rng)
        return self.ai.choose_anime_action(active, opp, self.rng)

    def resolve_single_turn(self) -> Dict[str, Any]:
        """Resolves one turn using pending actions + AI fallback for missing/AI sides."""
        self.turn_number += 1
        act_a = self.pending_actions.get(self.player_a_id) or self._ai_fallback(self.player_a_id, self.player_b_id)
        act_b = self.pending_actions.get(self.player_b_id) or self._ai_fallback(self.player_b_id, self.player_a_id)
        self.pending_actions.clear()
        self.turn_ready_event.clear()

        events: List[str] = []
        action_details: List[dict] = []

        order = sorted(
            [(self.player_a_id, self.player_b_id, act_a), (self.player_b_id, self.player_a_id, act_b)],
            key=lambda item: (
                6 if item[2].action_type == "switch" else 0,
                (self.get_active(item[0]).effective_speed if self.get_active(item[0]) else 0.0),
                self.rng.random(),
            ),
            reverse=True,
        )

        for pid, opp_id, act in order:
            mon = self.get_active(pid)
            opp = self.get_active(opp_id)
            if not mon or mon.is_fainted or not opp or opp.is_fainted:
                continue
            side = "a" if pid == self.player_a_id else "b"
            target_side = "b" if side == "a" else "a"

            if act.action_type == "switch" and act.switch_index is not None:
                team = self.teams[pid]
                if 0 <= act.switch_index < len(team) and not team[act.switch_index].is_fainted:
                    if hasattr(mon, "reset_stages"):
                        mon.reset_stages()
                    self.active_idx[pid] = act.switch_index
                    new_mon = team[act.switch_index]
                    events.append(f"{pid} switched {mon.name} out for {new_mon.name}!")
                    action_details.append({"event_type": "switch", "side": side, "move_name": f"Switch -> {new_mon.name}"})
            elif act.action_type == "transform" and act.transformation_id and isinstance(mon, (AnimeCombatant, MarvelCombatant)):
                ok, msg = mon.activate_transformation(act.transformation_id)
                events.append(msg)
                if ok:
                    action_details.append({"event_type": "transform", "side": side, "move_name": mon.active_transformation})
            elif act.action_type == "attack":
                if self._engine_kind == "pokemon":
                    move = next((m for m in mon.moves if m["id"] == act.move_id), mon.moves[0] if mon.moves else None)
                    if move:
                        self._pkmn_sim._execute_attack(mon, opp, move, events, action_details, side, target_side)
                elif self._engine_kind == "anime":
                    atk = next((a for a in mon.attacks if a["id"] == act.move_id), mon.attacks[0] if mon.attacks else None)
                    if atk:
                        dmg, msg = self._anime_sim.resolve_attack(mon, opp, atk)
                        events.append(msg)
                        action_details.append({"event_type": "attack", "side": side, "target_side": target_side, "move_name": atk["name"], "category": atk.get("category", "special"), "damage": dmg})
                elif self._engine_kind == "marvel":
                    atk = next((a for a in mon.attacks if a["id"] == act.move_id), mon.attacks[0] if mon.attacks else None)
                    if atk:
                        dmg, msg = self._marvel_sim.resolve_attack(mon, opp, atk)
                        events.append(msg)
                        action_details.append({"event_type": "attack", "side": side, "target_side": target_side, "move_name": atk["name"], "category": atk.get("category", "physical"), "damage": dmg})
                else:
                    if isinstance(mon, PokemonCombatant):
                        move = next((m for m in mon.moves if m["id"] == act.move_id), mon.moves[0] if mon.moves else None)
                        if move:
                            dmg, msg = self._cross_sim._pokemon_vs_any_damage(mon, opp, move)
                            events.append(msg)
                            action_details.append({"event_type": "attack", "side": side, "target_side": target_side, "move_name": move["name"], "category": "elemental" if move.get("category") == "Special" else "physical", "damage": dmg})
                    elif isinstance(mon, MarvelCombatant) and mon.attacks:
                        atk = next((a for a in mon.attacks if a["id"] == act.move_id), mon.attacks[0])
                        dmg, msg = self._cross_sim._marvel_vs_any_damage(mon, opp, atk)
                        events.append(msg)
                        action_details.append({"event_type": "attack", "side": side, "target_side": target_side, "move_name": atk["name"], "category": atk.get("category", "physical"), "damage": dmg})
                    elif isinstance(mon, AnimeCombatant) and mon.attacks:
                        atk = next((a for a in mon.attacks if a["id"] == act.move_id), mon.attacks[0])
                        dmg, msg = self._cross_sim._anime_vs_any_damage(mon, opp, atk)
                        events.append(msg)
                        action_details.append({"event_type": "attack", "side": side, "target_side": target_side, "move_name": atk["name"], "category": atk.get("category", "special"), "damage": dmg})

                if opp.is_fainted:
                    events.append(f"{opp.name} fainted!")
                    action_details.append({"event_type": "faint", "side": target_side})

        cur_a = self.get_active(self.player_a_id)
        cur_b = self.get_active(self.player_b_id)
        turn_entry = {
            "match_id": self.match_id,
            "turn": self.turn_number,
            "events": events,
            "action_details": action_details,
            "active_a": cur_a.to_summary_dict() if cur_a else None,
            "active_b": cur_b.to_summary_dict() if cur_b else None,
            "remaining_a": self.remaining_count(self.player_a_id),
            "remaining_b": self.remaining_count(self.player_b_id),
        }
        self.turn_log.append(turn_entry)
        return turn_entry

    async def run_interactive(
        self,
        send_prompt: Optional[Callable[[str, dict], Awaitable[None]]] = None,
        broadcast_turn: Optional[Callable[[dict], Awaitable[None]]] = None,
        max_turns: int = 100,
    ) -> BattleResult:
        """Runs the full interactive battle loop asynchronously."""
        while (
            not self.is_invalidated
            and self.turn_number < max_turns
            and self.remaining_count(self.player_a_id) > 0
            and self.remaining_count(self.player_b_id) > 0
        ):
            humans = [p for p in (self.player_a_id, self.player_b_id) if self.is_human_controlled(p)]
            if humans:
                self.turn_ready_event.clear()
                if send_prompt:
                    for h in humans:
                        await send_prompt(h, self.build_player_prompt(h))
                try:
                    await asyncio.wait_for(self.turn_ready_event.wait(), timeout=self.turn_timeout_seconds)
                except asyncio.TimeoutError:
                    pass  # Missing players automatically fall back to AI in resolve_single_turn()

            if self.is_invalidated:
                break
            turn_entry = self.resolve_single_turn()
            if broadcast_turn and not self.is_invalidated:
                await broadcast_turn(turn_entry)

        rem_a = self.remaining_count(self.player_a_id)
        rem_b = self.remaining_count(self.player_b_id)
        hp_a = self.remaining_hp(self.player_a_id)
        hp_b = self.remaining_hp(self.player_b_id)

        if rem_a > 0 and rem_b == 0:
            return BattleResult(self.player_a_id, self.player_b_id, False, "TEAM_ELIMINATION", self.turn_number, self.seed, hp_a, hp_b, rem_a, rem_b, self.turn_log)
        if rem_b > 0 and rem_a == 0:
            return BattleResult(self.player_b_id, self.player_a_id, False, "TEAM_ELIMINATION", self.turn_number, self.seed, hp_a, hp_b, rem_a, rem_b, self.turn_log)
        if hp_a > hp_b:
            return BattleResult(self.player_a_id, self.player_b_id, False, "TIME_LIMIT_HP", self.turn_number, self.seed, hp_a, hp_b, rem_a, rem_b, self.turn_log)
        if hp_b > hp_a:
            return BattleResult(self.player_b_id, self.player_a_id, False, "TIME_LIMIT_HP", self.turn_number, self.seed, hp_a, hp_b, rem_a, rem_b, self.turn_log)
        return BattleResult(None, None, True, "DRAW", self.turn_number, self.seed, hp_a, hp_b, rem_a, rem_b, self.turn_log)
