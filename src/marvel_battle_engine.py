"""
Marvel Universe Native Battle Engine (Phase 6)
==============================================
Implements Marvel Comics & MCU native combat mechanics through BaseCombatant:
- Physical, Energy, Magical, Psychic, Ranged, and Defensive attacks
- Shields, healing/regeneration factors, and status conditions
- Transformations / alternate forms (Hulkbuster, Odinforce, World Breaker, Binary, Giant-Man)
- Documented weaknesses, resistances, and immunities
- Strict exclusion of incomplete/unverified civilian characters
- Deterministic seeded RNG
"""

import random
from typing import Any, Dict, List, Optional, Tuple

from src.battle_interface import BaseCombatant, BattleAction, BattleResult

MAX_MARVEL_TURNS = 150

MARVEL_CATEGORY_POWER = {
    "energy": 74,
    "magical": 74,
    "physical": 72,
    "ranged": 68,
    "psychic": 70,
    "elemental": 74,
    "defensive": 0,
    "healing": 0,
    "support": 0,
}


class MarvelCombatant(BaseCombatant):
    """Stateful in-battle representation of a Marvel Comics / MCU character."""

    def __init__(self, profile: dict):
        self._profile = profile
        self._id = str(profile.get("character_id", ""))
        self._name = profile.get("name", "Marvel Character")
        self.incarnation = profile.get("incarnation", "Earth-616 (Comics)")
        self.verification_status = profile.get("verification_status", "incomplete")
        self.combat_eligible = bool(profile.get("combat_eligible", False))

        stats = profile.get("stats", {})
        dur = float(stats.get("durability", 60))
        self._max_hp = max(90, int(125 + dur * 1.75))
        self._current_hp = self._max_hp

        self.strength_stat = float(stats.get("strength", 60))
        self.energy_stat = float(stats.get("energy_projection", 50))
        self.combat_skill = float(stats.get("combat_skill", 60))
        self.durability_stat = dur
        self.intelligence_stat = float(stats.get("intelligence", 60))
        self._speed = float(stats.get("speed", 60))

        self.attacks: List[Dict[str, Any]] = list(profile.get("attacks", []))
        self.abilities: List[Dict[str, Any]] = list(profile.get("abilities", []))
        self.transformations: List[Dict[str, Any]] = list(profile.get("transformations", []))
        self.active_transformation: Optional[str] = None
        self.shield_turns: int = 0
        self._status: Optional[str] = None
        self.status_turns: int = 0

        self.weaknesses: List[str] = list(profile.get("weaknesses") or [])
        self.resistances: List[str] = list(profile.get("resistances") or [])
        self.immunities: List[str] = list(profile.get("immunities") or [])

        self.has_verified_combat_data: bool = (
            self.combat_eligible
            and self.verification_status == "verified_curated"
            and len(self.attacks) > 0
        )
        self.unsupported_reason: Optional[str] = (
            None
            if self.has_verified_combat_data
            else f"Marvel character '{self._name}' lacks verified combat data ({self.verification_status})."
        )

    @property
    def combatant_id(self) -> str:
        return self._id

    @property
    def name(self) -> str:
        return f"{self._name} [{self.active_transformation}]" if self.active_transformation else self._name

    @property
    def system(self) -> str:
        return "marvel"

    @property
    def current_hp(self) -> int:
        return self._current_hp

    @property
    def max_hp(self) -> int:
        return self._max_hp

    @property
    def is_fainted(self) -> bool:
        return self._current_hp <= 0

    @property
    def status(self) -> Optional[str]:
        return self._status

    @property
    def effective_speed(self) -> float:
        return self._speed * (1.12 if self.active_transformation else 1.0)

    def has_ability_type(self, ability_type: str) -> bool:
        return any(a.get("ability_type") == ability_type for a in self.abilities)

    def activate_transformation(self, transformation_id: str) -> Tuple[bool, str]:
        if self.active_transformation is not None:
            return False, f"{self._name} is already transformed."
        tf = next((t for t in self.transformations if t["id"] == transformation_id), None)
        if not tf:
            return False, "Transformation not found."
        self.active_transformation = tf["name"]
        self.strength_stat = min(115.0, self.strength_stat * 1.15)
        self.energy_stat = min(115.0, self.energy_stat * 1.15)
        self.durability_stat = min(115.0, self.durability_stat * 1.10)
        return True, f"{self._name} activated {tf['name']}!"

    def take_damage(self, amount: int) -> int:
        if amount <= 0 or self.is_fainted:
            return 0
        if self.shield_turns > 0:
            amount = max(1, int(amount * 0.60))
        actual = min(self._current_hp, amount)
        self._current_hp -= actual
        return actual

    def heal(self, amount: int) -> int:
        if amount <= 0 or self.is_fainted:
            return 0
        actual = min(self._max_hp - self._current_hp, amount)
        self._current_hp += actual
        return actual

    def get_available_moves(self) -> List[Dict[str, Any]]:
        return list(self.attacks)

    def get_available_transformations(self) -> List[Dict[str, Any]]:
        if self.active_transformation is not None:
            return []
        return list(self.transformations)

    def to_summary_dict(self) -> Dict[str, Any]:
        return {
            "id": self.combatant_id,
            "name": self.name,
            "system": self.system,
            "incarnation": self.incarnation,
            "verification_status": self.verification_status,
            "has_verified_combat_data": self.has_verified_combat_data,
            "unsupported_reason": self.unsupported_reason,
            "current_hp": self._current_hp,
            "max_hp": self._max_hp,
            "status": self._status,
            "fainted": self.is_fainted,
        }


class MarvelBattleSimulator:
    """Deterministic, seeded turn-based battle simulator for Marvel combatants."""

    def __init__(
        self,
        player_a_id: str,
        team_a: List[MarvelCombatant],
        player_b_id: str,
        team_b: List[MarvelCombatant],
        seed: int = 42,
        ai_selector: Any = None,
    ):
        self.player_a_id = player_a_id
        self.player_b_id = player_b_id
        self.teams: Dict[str, List[MarvelCombatant]] = {
            player_a_id: list(team_a),
            player_b_id: list(team_b),
        }
        self.active_idx: Dict[str, int] = {player_a_id: 0, player_b_id: 0}
        self.rng = random.Random(seed)
        self.seed = seed
        self.ai_selector = ai_selector
        self.turn_log: List[Dict[str, Any]] = []

    def get_active(self, pid: str) -> Optional[MarvelCombatant]:
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

    def resolve_attack(
        self,
        attacker: MarvelCombatant,
        defender: MarvelCombatant,
        attack: dict,
    ) -> Tuple[int, str]:
        cat = attack.get("category", "physical")
        if cat == "defensive":
            attacker.shield_turns = 2
            return 0, f"{attacker.name} raised {attack['name']} (defensive shield)!"
        if cat == "healing":
            healed = attacker.heal(max(15, int(attacker.max_hp * 0.25)))
            return 0, f"{attacker.name} used {attack['name']} and recovered {healed} HP!"

        base_power = MARVEL_CATEGORY_POWER.get(cat, 68)
        off_stat = attacker.strength_stat if cat == "physical" else max(attacker.energy_stat, attacker.combat_skill * 0.85)
        skill_bonus = 1.0 + (attacker.combat_skill - 50.0) * 0.0025
        def_stat = max(20.0, defender.durability_stat)

        atk_name_low = attack.get("name", "").lower()
        if any(imm.lower() in atk_name_low for imm in defender.immunities if imm):
            return 0, f"{attacker.name} used {attack['name']}, but {defender.name} is immune!"

        mult = 1.0
        if any(w.lower() in atk_name_low for w in defender.weaknesses if w):
            mult *= 1.30
        if any(r.lower() in atk_name_low for r in defender.resistances if r):
            mult *= 0.78
        if defender.has_ability_type("defensive"):
            mult *= 0.90

        roll = self.rng.uniform(0.90, 1.05)
        raw_dmg = ((base_power * (off_stat / def_stat) * skill_bonus) * 0.42 + 10) * mult * roll
        actual = defender.take_damage(max(5, int(raw_dmg)))
        return actual, f"{attacker.name} used {attack['name']} for {actual} damage!"

    def run(self) -> BattleResult:
        rem_a = self.remaining_count(self.player_a_id)
        rem_b = self.remaining_count(self.player_b_id)
        if rem_a == 0 and rem_b == 0:
            return BattleResult(None, None, True, "BOTH_TEAMS_EMPTY", 0, self.seed, 0, 0, 0, 0, [])
        if rem_a == 0:
            return BattleResult(self.player_b_id, self.player_a_id, False, "TEAM_FORFEIT", 0, self.seed, 0, self.remaining_hp(self.player_b_id), 0, rem_b, [])
        if rem_b == 0:
            return BattleResult(self.player_a_id, self.player_b_id, False, "TEAM_FORFEIT", 0, self.seed, self.remaining_hp(self.player_a_id), 0, rem_a, 0, [])

        sup_a = any(c.has_verified_combat_data for c in self.teams[self.player_a_id])
        sup_b = any(c.has_verified_combat_data for c in self.teams[self.player_b_id])
        if not sup_a and not sup_b:
            return BattleResult(None, None, True, "UNSUPPORTED_COMBAT_DATA", 0, self.seed, self.remaining_hp(self.player_a_id), self.remaining_hp(self.player_b_id), rem_a, rem_b, [])
        if not sup_a:
            return BattleResult(self.player_b_id, self.player_a_id, False, "UNSUPPORTED_COMBAT_DATA", 0, self.seed, self.remaining_hp(self.player_a_id), self.remaining_hp(self.player_b_id), rem_a, rem_b, [])
        if not sup_b:
            return BattleResult(self.player_a_id, self.player_b_id, False, "UNSUPPORTED_COMBAT_DATA", 0, self.seed, self.remaining_hp(self.player_a_id), self.remaining_hp(self.player_b_id), rem_a, rem_b, [])

        turns = 0
        while turns < MAX_MARVEL_TURNS:
            if self.remaining_count(self.player_a_id) == 0 or self.remaining_count(self.player_b_id) == 0:
                break
            turns += 1
            events: List[str] = []
            action_details: List[dict] = []

            act_a = self.get_active(self.player_a_id)
            act_b = self.get_active(self.player_b_id)
            if not act_a or not act_b:
                break

            dec_a = (
                self.ai_selector.choose_marvel_action(act_a, act_b, self.rng)
                if self.ai_selector
                else BattleAction("attack", move_id=act_a.attacks[0]["id"])
            )
            dec_b = (
                self.ai_selector.choose_marvel_action(act_b, act_a, self.rng)
                if self.ai_selector
                else BattleAction("attack", move_id=act_b.attacks[0]["id"])
            )

            order = sorted(
                [(self.player_a_id, self.player_b_id, dec_a), (self.player_b_id, self.player_a_id, dec_b)],
                key=lambda item: (self.get_active(item[0]).effective_speed, self.rng.random()),
                reverse=True,
            )

            for pid, opp_id, dec in order:
                char = self.get_active(pid)
                opp = self.get_active(opp_id)
                if not char or char.is_fainted or not opp or opp.is_fainted:
                    continue
                side = "a" if pid == self.player_a_id else "b"
                target_side = "b" if side == "a" else "a"

                if dec.action_type == "transform" and dec.transformation_id:
                    ok, msg = char.activate_transformation(dec.transformation_id)
                    events.append(msg)
                    if ok:
                        action_details.append({"event_type": "transform", "side": side, "move_name": char.active_transformation})
                elif dec.action_type == "attack":
                    atk = next((a for a in char.attacks if a["id"] == dec.move_id), char.attacks[0])
                    dmg, msg = self.resolve_attack(char, opp, atk)
                    events.append(msg)
                    action_details.append({
                        "event_type": "attack",
                        "side": side,
                        "target_side": target_side,
                        "move_name": atk["name"],
                        "category": atk.get("category", "physical"),
                        "damage": dmg,
                    })
                    if opp.is_fainted:
                        events.append(f"{opp.name} was defeated!")
                        action_details.append({"event_type": "faint", "side": target_side})

            for pid in (self.player_a_id, self.player_b_id):
                c = self.get_active(pid)
                if c and not c.is_fainted:
                    if c.shield_turns > 0:
                        c.shield_turns -= 1
                    if c.has_ability_type("healing_support"):
                        healed = c.heal(max(2, c.max_hp // 18))
                        if healed > 0:
                            events.append(f"{c.name} regenerated {healed} HP.")

            cur_a = self.get_active(self.player_a_id)
            cur_b = self.get_active(self.player_b_id)
            self.turn_log.append({
                "turn": turns,
                "events": events,
                "action_details": action_details,
                "active_a": cur_a.to_summary_dict() if cur_a else None,
                "active_b": cur_b.to_summary_dict() if cur_b else None,
                "remaining_a": self.remaining_count(self.player_a_id),
                "remaining_b": self.remaining_count(self.player_b_id),
            })

        rem_a = self.remaining_count(self.player_a_id)
        rem_b = self.remaining_count(self.player_b_id)
        hp_a = self.remaining_hp(self.player_a_id)
        hp_b = self.remaining_hp(self.player_b_id)

        if rem_a > 0 and rem_b == 0:
            return BattleResult(self.player_a_id, self.player_b_id, False, "TEAM_ELIMINATION", turns, self.seed, hp_a, hp_b, rem_a, rem_b, self.turn_log)
        if rem_b > 0 and rem_a == 0:
            return BattleResult(self.player_b_id, self.player_a_id, False, "TEAM_ELIMINATION", turns, self.seed, hp_a, hp_b, rem_a, rem_b, self.turn_log)
        if hp_a > hp_b:
            return BattleResult(self.player_a_id, self.player_b_id, False, "TIME_LIMIT_HP", turns, self.seed, hp_a, hp_b, rem_a, rem_b, self.turn_log)
        if hp_b > hp_a:
            return BattleResult(self.player_b_id, self.player_a_id, False, "TIME_LIMIT_HP", turns, self.seed, hp_a, hp_b, rem_a, rem_b, self.turn_log)
        return BattleResult(None, None, True, "DRAW", turns, self.seed, hp_a, hp_b, rem_a, rem_b, self.turn_log)
