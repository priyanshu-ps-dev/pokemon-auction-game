"""
Multiplayer Battle & Tournament Manager (Phase 2)
=================================================
Orchestrates 2-player direct battles and 3-8 player round-robin tournaments
after auction completion. Supports incomplete teams (1-6), empty teams
(forfeit), withdrawn players, draws, timeouts, and deterministic seeds.
Runs simulations off the asyncio event loop via asyncio.to_thread.
"""

import asyncio
import hashlib
from typing import Any, Dict, List, Optional, Tuple

from src.anime_battle_engine import AnimeBattleSimulator, AnimeCombatant
from src.battle_ai import TacticalBattleAI
from src.battle_engine import PokemonBattleSimulator, PokemonCombatant
from src.marvel_battle_engine import MarvelBattleSimulator, MarvelCombatant
from src.battle_interface import BattleResult
from src.combat_data import CombatDataProvider
from src.cross_universe_adapter import CrossUniverseBattleSimulator, CrossUniverseConfig


def _deterministic_seed(match_id: str, suffix: str = "") -> int:
    digest = hashlib.sha256(f"{match_id}:{suffix}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


class BattleManager:
    """Runs server-authoritative simulated battles and tournaments."""

    def __init__(self, combat_provider: Optional[CombatDataProvider] = None):
        self.provider = combat_provider or CombatDataProvider()
        self.ai = TacticalBattleAI()

    def build_combatant(self, char_entry: dict) -> Tuple[str, Any]:
        """Builds either a PokemonCombatant or AnimeCombatant from a team entry."""
        profile = self.provider.get_combat_profile(char_entry)
        if profile is None:
            # Fallback if a custom/test dict isn't in the static DB
            if "national_id" in char_entry or char_entry.get("anime_id") == "pokemon":
                return "pokemon", PokemonCombatant(char_entry)
            return "anime", AnimeCombatant({
                "character_id": str(char_entry.get("id", "unknown")),
                "name": char_entry.get("name", "Unknown"),
                "anime_id": char_entry.get("anime_id", "unknown"),
                "stats": char_entry.get("stats", {}),
                "attacks": [],
                "abilities": [],
                "transformations": [],
                "verification_status": "unverified_incomplete",
            })

        if profile["system"] == "pokemon":
            return "pokemon", PokemonCombatant(profile)
        if profile["system"] == "marvel":
            return "marvel", MarvelCombatant(profile)
        return "anime", AnimeCombatant(profile)

    def simulate_1v1(
        self,
        player_a_id: str,
        team_a_raw: List[dict],
        player_b_id: str,
        team_b_raw: List[dict],
        seed: int = 42,
        cross_config: Optional[CrossUniverseConfig] = None,
    ) -> BattleResult:
        """
        Simulates a 1v1 team battle supporting 0..6 combatants per side:
        - Pure Pokémon -> native PokemonBattleSimulator
        - Pure Anime -> native AnimeBattleSimulator
        - Mixed / Cross-Universe -> CrossUniverseBattleSimulator
        """
        built_a = [self.build_combatant(c) for c in team_a_raw]
        built_b = [self.build_combatant(c) for c in team_b_raw]

        sys_a = {sys_name for sys_name, _ in built_a}
        sys_b = {sys_name for sys_name, _ in built_b}
        all_systems = sys_a | sys_b

        if all_systems == {"anime"}:
            sim = AnimeBattleSimulator(
                player_a_id, [c for _, c in built_a],
                player_b_id, [c for _, c in built_b],
                seed=seed, ai_selector=self.ai,
            )
            return sim.run()

        if all_systems == {"marvel"}:
            sim = MarvelBattleSimulator(
                player_a_id, [c for _, c in built_a],
                player_b_id, [c for _, c in built_b],
                seed=seed, ai_selector=self.ai,
            )
            return sim.run()

        if all_systems == {"pokemon"} or not all_systems:
            sim = PokemonBattleSimulator(
                player_a_id, [c for _, c in built_a],
                player_b_id, [c for _, c in built_b],
                seed=seed, ai_selector=self.ai,
            )
            return sim.run()

        images_by_id: Dict[str, str] = {}
        for raw, (_, comb) in zip(team_a_raw + team_b_raw, built_a + built_b):
            images_by_id[comb.combatant_id] = raw.get("image", "")

        sim = CrossUniverseBattleSimulator(
            player_a_id, [c for _, c in built_a],
            player_b_id, [c for _, c in built_b],
            seed=seed,
            ai_selector=self.ai,
            config=cross_config,
            images_by_id=images_by_id,
        )
        return sim.run()

    def run_tournament_sync(
        self,
        players: List[Any],
        match_id: str = "match_1",
        tournament_format: str = "round_robin",
    ) -> Dict[str, Any]:
        """
        Runs a complete tournament synchronously:
        - 2 active players -> direct 1v1 battle
        - 3..8 active players with tournament_format == 'bracket' -> Single-Elimination Championship Bracket
        - 3..8 active players with tournament_format == 'round_robin' -> Round-Robin League
        Withdrawn players are ranked below active participants.
        """
        active_players = [p for p in players if not getattr(p, "is_withdrawn", False)]
        if tournament_format == "bracket" and len(active_players) >= 2:
            return self._run_bracket_sync(players, active_players, match_id)
        withdrawn_players = [p for p in players if getattr(p, "is_withdrawn", False)]

        standings: Dict[str, Dict[str, Any]] = {}
        for p in players:
            sid = p.session_id
            standings[sid] = {
                "session_id": sid,
                "name": p.name,
                "avatar": getattr(p, "avatar", ""),
                "is_withdrawn": getattr(p, "is_withdrawn", False),
                "wins": 0,
                "losses": 0,
                "draws": 0,
                "points": 0,
                "remaining_hp_total": 0,
                "matches_played": 0,
                "team_count": len(getattr(p, "team", [])),
            }

        matches: List[Dict[str, Any]] = []
        n = len(active_players)
        for i in range(n):
            for j in range(i + 1, n):
                pa = active_players[i]
                pb = active_players[j]
                seed = _deterministic_seed(match_id, f"{pa.session_id}_vs_{pb.session_id}")
                res = self.simulate_1v1(pa.session_id, pa.team, pb.session_id, pb.team, seed=seed)

                standings[pa.session_id]["matches_played"] += 1
                standings[pb.session_id]["matches_played"] += 1
                standings[pa.session_id]["remaining_hp_total"] += res.player_a_remaining_hp
                standings[pb.session_id]["remaining_hp_total"] += res.player_b_remaining_hp

                if res.is_draw or res.winner_id is None:
                    standings[pa.session_id]["draws"] += 1
                    standings[pb.session_id]["draws"] += 1
                    standings[pa.session_id]["points"] += 1
                    standings[pb.session_id]["points"] += 1
                elif res.winner_id == pa.session_id:
                    standings[pa.session_id]["wins"] += 1
                    standings[pb.session_id]["losses"] += 1
                    standings[pa.session_id]["points"] += 3
                else:
                    standings[pb.session_id]["wins"] += 1
                    standings[pa.session_id]["losses"] += 1
                    standings[pb.session_id]["points"] += 3

                matches.append({
                    "player_a_id": pa.session_id,
                    "player_a_name": pa.name,
                    "player_b_id": pb.session_id,
                    "player_b_name": pb.name,
                    "player_a_team": [{"id": str(c.get("id", "")), "name": c.get("name", ""), "image": c.get("image", "")} for c in pa.team],
                    "player_b_team": [{"id": str(c.get("id", "")), "name": c.get("name", ""), "image": c.get("image", "")} for c in pb.team],
                    "winner_id": res.winner_id,
                    "is_draw": res.is_draw,
                    "reason": res.reason,
                    "turns_played": res.turns_played,
                    "seed": res.seed,
                    "player_a_remaining_hp": res.player_a_remaining_hp,
                    "player_b_remaining_hp": res.player_b_remaining_hp,
                    "turn_log": res.turn_log,
                })

        # Deterministic ranking: active > withdrawn, points, wins, remaining_hp_total
        # CRITICAL: Never sort by team_count or team_power!
        ranked = sorted(
            standings.values(),
            key=lambda s: (
                not s["is_withdrawn"],
                s["points"],
                s["wins"],
                s["remaining_hp_total"],
            ),
            reverse=True,
        )

        current_rank = 1
        for idx, entry in enumerate(ranked):
            if idx > 0:
                prev = ranked[idx - 1]
                tied = (
                    entry["is_withdrawn"] == prev["is_withdrawn"]
                    and entry["points"] == prev["points"]
                    and entry["wins"] == prev["wins"]
                    and entry["remaining_hp_total"] == prev["remaining_hp_total"]
                )
                if not tied:
                    current_rank = idx + 1
            entry["rank"] = current_rank

        return {
            "format": "direct_1v1" if n <= 2 else "round_robin",
            "match_id": match_id,
            "total_matches": len(matches),
            "standings": ranked,
            "champion": ranked[0] if ranked else None,
            "matches": matches,
            "bracket": None,
        }

    def _run_bracket_sync(
        self,
        all_players: List[Any],
        active_players: List[Any],
        match_id: str,
    ) -> Dict[str, Any]:
        """Single-elimination championship bracket (supports 2..8 players with automatic byes)."""
        standings: Dict[str, Dict[str, Any]] = {
            p.session_id: {
                "session_id": p.session_id,
                "name": p.name,
                "avatar": getattr(p, "avatar", ""),
                "is_withdrawn": getattr(p, "is_withdrawn", False),
                "wins": 0,
                "losses": 0,
                "draws": 0,
                "points": 0,
                "remaining_hp_total": 0,
                "matches_played": 0,
                "eliminated_round": 0,
                "team_count": len(getattr(p, "team", [])),
            }
            for p in all_players
        }

        matches: List[Dict[str, Any]] = []
        rounds: List[Dict[str, Any]] = []
        current_pool = list(active_players)
        round_num = 1

        while len(current_pool) > 1:
            round_label = (
                "Final" if len(current_pool) == 2
                else ("Semifinals" if len(current_pool) <= 4 else f"Round {round_num}")
            )
            next_pool: List[Any] = []
            round_matches: List[Dict[str, Any]] = []

            idx = 0
            while idx < len(current_pool):
                if idx + 1 >= len(current_pool):
                    # Automatic bye
                    bye_p = current_pool[idx]
                    next_pool.append(bye_p)
                    round_matches.append({"bye": True, "player_id": bye_p.session_id, "player_name": bye_p.name})
                    idx += 1
                    continue

                pa = current_pool[idx]
                pb = current_pool[idx + 1]
                idx += 2
                seed = _deterministic_seed(match_id, f"r{round_num}_{pa.session_id}_vs_{pb.session_id}")
                res = self.simulate_1v1(pa.session_id, pa.team, pb.session_id, pb.team, seed=seed)

                standings[pa.session_id]["matches_played"] += 1
                standings[pb.session_id]["matches_played"] += 1
                standings[pa.session_id]["remaining_hp_total"] += res.player_a_remaining_hp
                standings[pb.session_id]["remaining_hp_total"] += res.player_b_remaining_hp

                if res.winner_id == pb.session_id:
                    winner, loser = pb, pa
                elif res.winner_id == pa.session_id:
                    winner, loser = pa, pb
                else:
                    # Deterministic draw tiebreak in bracket by remaining HP, then pa
                    winner, loser = (pa, pb) if res.player_a_remaining_hp >= res.player_b_remaining_hp else (pb, pa)

                standings[winner.session_id]["wins"] += 1
                standings[winner.session_id]["points"] += 3
                standings[loser.session_id]["losses"] += 1
                standings[loser.session_id]["eliminated_round"] = round_num
                next_pool.append(winner)

                match_rec = {
                    "round": round_label,
                    "player_a_id": pa.session_id,
                    "player_a_name": pa.name,
                    "player_b_id": pb.session_id,
                    "player_b_name": pb.name,
                    "player_a_team": [{"id": str(c.get("id", "")), "name": c.get("name", ""), "image": c.get("image", "")} for c in pa.team],
                    "player_b_team": [{"id": str(c.get("id", "")), "name": c.get("name", ""), "image": c.get("image", "")} for c in pb.team],
                    "winner_id": winner.session_id,
                    "is_draw": res.is_draw,
                    "reason": res.reason,
                    "turns_played": res.turns_played,
                    "seed": res.seed,
                    "player_a_remaining_hp": res.player_a_remaining_hp,
                    "player_b_remaining_hp": res.player_b_remaining_hp,
                    "turn_log": res.turn_log,
                }
                matches.append(match_rec)
                round_matches.append({
                    "player_a_id": pa.session_id,
                    "player_a_name": pa.name,
                    "player_b_id": pb.session_id,
                    "player_b_name": pb.name,
                    "winner_id": winner.session_id,
                    "winner_name": winner.name,
                })

            rounds.append({"round": round_num, "label": round_label, "matches": round_matches})
            current_pool = next_pool
            round_num += 1

        if current_pool:
            standings[current_pool[0].session_id]["eliminated_round"] = round_num + 1

        ranked = sorted(
            standings.values(),
            key=lambda s: (
                not s["is_withdrawn"],
                s["eliminated_round"],
                s["wins"],
                s["remaining_hp_total"],
            ),
            reverse=True,
        )
        for rank_idx, entry in enumerate(ranked, start=1):
            entry["rank"] = rank_idx

        return {
            "format": "bracket",
            "match_id": match_id,
            "total_matches": len(matches),
            "standings": ranked,
            "champion": ranked[0] if ranked else None,
            "matches": matches,
            "bracket": rounds,
        }

    async def run_tournament_async(
        self,
        players: List[Any],
        match_id: str = "match_1",
        timeout_seconds: float = 15.0,
        tournament_format: str = "round_robin",
    ) -> Dict[str, Any]:
        """Runs the tournament in a worker thread with a timeout so asyncio never blocks."""
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self.run_tournament_sync, players, match_id, tournament_format),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            return {
                "format": "timeout",
                "match_id": match_id,
                "total_matches": 0,
                "standings": [],
                "champion": None,
                "matches": [],
                "error": "BATTLE_TIMEOUT",
            }
