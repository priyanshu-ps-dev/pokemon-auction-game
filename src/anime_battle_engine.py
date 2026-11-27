"""
Anime Character Battle Engine (Phase 2)
=======================================
Separate combat engine for non-Pokémon anime characters using verified
Phase 1 combat records (attacks, abilities, transformations, energy systems).
Never forces anime characters into Pokémon type charts or mechanics, and
explicitly marks characters lacking verified combat data as unsupported.
"""

import random

from src.combat_interactions import end_nonpokemon_turn, resolve_technique_damage, spend_stamina
from typing import Any, Dict, List, Optional, Tuple

from src.battle_interface import BaseCombatant, BattleAction, BattleResult

MAX_ANIME_TURNS = 150

# Transparent, documented category base-power mapping (no hidden arbitrary multipliers)
CATEGORY_BASE_POWER = {
    "energy": 75,
    "elemental": 75,
    "magical": 75,
    "psychic": 70,
    "physical": 70,
    "ranged": 65,
    "defensive": 0,
    "healing": 0,
    "support": 0,
    "unknown": 60,
}


class AnimeCombatant(BaseCombatant):
    """Stateful in-battle representation of an anime character."""

    def __init__(self, profile: dict):
        self._profile = profile
        self._id = str(profile.get("character_id", ""))
        self._name = profile.get("name", "Anime Character")
        self.anime_id = profile.get("anime_id", "unknown")
        self.energy_system = profile.get("energy_system") or "Standard"
        self.verification_status = profile.get("verification_status", "unverified_incomplete")

        stats = profile.get("stats", {})
        # Transparent normalized scaling from documented 1-100 anime stats
        self.estimation_method = "normalized_anime_stats_v1"
        dur = float(stats.get("durability", stats.get("hp", 60)))
        self._max_hp = max(80, int(120 + dur * 1.8))
        self._current_hp = self._max_hp

        self.attack_stat = float(stats.get("attack_power", stats.get("attack", 60)))
        self.strength_stat = float(stats.get("strength", self.attack_stat))
        self.defense_stat = float(stats.get("defense", 60))
        self._speed = float(stats.get("speed", 60))
        self.battle_iq = float(stats.get("battle_iq", 60))

        self.attacks: List[Dict[str, Any]] = list(profile.get("attacks", []))
        self.abilities: List[Dict[str, Any]] = list(profile.get("abilities", []))
        self.transformations: List[Dict[str, Any]] = list(profile.get("transformations", []))
        self.active_transformation: Optional[str] = None
        self.transformation_turns = 0
        self.transformed_once = False
        self.transformation_bonus = (0.0, 0.0)
        self.shield_turns: int = 0
        self.max_stamina = max(24, int(stats.get("stamina", 76)))
        self.stamina = self.max_stamina
        self._status: Optional[str] = None

        self.weaknesses: List[str] = list(profile.get("weaknesses") or [])
        self.resistances: List[str] = list(profile.get("resistances") or [])
        self.immunities: List[str] = list(profile.get("immunities") or [])

        # Clear unsupported-data state when no verified attacks/abilities exist
        self.has_verified_combat_data: bool = (
            self.verification_status == "verified_curated" and len(self.attacks) > 0
        )
        self.unsupported_reason: Optional[str] = (
            None
            if self.has_verified_combat_data
            else f"Character '{self._name}' lacks verified combat data ({self.verification_status})."
        )

    @property
    def combatant_id(self) -> str:
        return self._id

    @property
    def name(self) -> str:
        return f"{self._name} ({self.active_transformation})" if self.active_transformation else self._name

    @property
    def system(self) -> str:
        return "anime"

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
        return self._speed * (1.15 if self.active_transformation else 1.0)

    def has_ability_type(self, ability_type: str) -> bool:
        return any(a.get("ability_type") == ability_type for a in self.abilities)

    def activate_transformation(self, transformation_id: str) -> Tuple[bool, str]:
        tf = next((form for form in self.get_available_transformations() if form["id"] == transformation_id), None)
        if not tf:
            return False, "Transformation is unavailable."
        self.stamina -= tf.get("stamina_cost", 18)
        self.transformed_once = True
        self.active_transformation = tf["name"]
        self.transformation_turns = tf.get("duration_turns", 6)
        boosted_attack = min(115.0, self.attack_stat * 1.15)
        boosted_defense = min(115.0, self.defense_stat * 1.10)
        self.transformation_bonus = (boosted_attack - self.attack_stat, boosted_defense - self.defense_stat)
        self.attack_stat = boosted_attack
        self.defense_stat = boosted_defense
        return True, f"{self._name} transformed into {tf['name']}!"

    def tick_transformation(self):
        if self.active_transformation:
            self.transformation_turns -= 1
            if self.transformation_turns == 0:
                name = self.active_transformation
                self.active_transformation = None
                self.attack_stat -= self.transformation_bonus[0]
                self.defense_stat -= self.transformation_bonus[1]
                return f"{self._name} returned to base form as {name} wore off."
        return None

    def take_damage(self, amount: int) -> int:
        if amount <= 0 or self.is_fainted:
            return 0
        if self.shield_turns > 0:
            amount = max(1, int(amount * 0.65))
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
        if self.transformed_once:
            return []
        return [form for form in self.transformations if self.stamina >= form.get("stamina_cost", 18)]

    def to_summary_dict(self) -> Dict[str, Any]:
        return {
            "id": self.combatant_id,
            "name": self.name,
            "system": self.system,
            "anime_id": self.anime_id,
            "energy_system": self.energy_system,
            "verification_status": self.verification_status,
            "has_verified_combat_data": self.has_verified_combat_data,
            "unsupported_reason": self.unsupported_reason,
            "estimation_method": self.estimation_method,
            "current_hp": self._current_hp,
            "max_hp": self._max_hp,
            "fainted": self.is_fainted,
        }


class AnimeBattleSimulator:
    """Deterministic, seeded turn-based battle simulator for anime combatants."""

    def __init__(
        self,
        player_a_id: str,
        team_a: List[AnimeCombatant],
        player_b_id: str,
        team_b: List[AnimeCombatant],
        seed: int = 42,
        ai_selector: Any = None,
    ):
        self.player_a_id = player_a_id
        self.player_b_id = player_b_id
        self.teams: Dict[str, List[AnimeCombatant]] = {
            player_a_id: list(team_a),
            player_b_id: list(team_b),
        }
        self.active_idx: Dict[str, int] = {player_a_id: 0, player_b_id: 0}
        self.rng = random.Random(seed)
        self.seed = seed
        self.ai_selector = ai_selector
        self.turn_log: List[Dict[str, Any]] = []

    def get_active(self, pid: str) -> Optional[AnimeCombatant]:
        team = self.teams[pid]
        idx = self.active_idx[pid]
        if 0 <= idx < len(team) and not team[idx].is_fainted:
            return team[idx]
        for i, char in enumerate(team):
            if not char.is_fainted:
                self.active_idx[pid] = i
                return char
        return None

    def remaining_count(self, pid: str) -> int:
        return sum(1 for c in self.teams[pid] if not c.is_fainted)

    def remaining_hp(self, pid: str) -> int:
        return sum(max(0, c.current_hp) for c in self.teams[pid])

    def resolve_attack(
        self,
        attacker: AnimeCombatant,
        defender: AnimeCombatant,
        attack: dict,
    ) -> Tuple[int, str]:
        if not spend_stamina(attacker, attack):
            return 0, f"{attacker.name} recovered stamina instead of using {attack['name']}."
        cat = attack.get("category", "unknown")
        if cat == "healing":
            healed = attacker.heal(max(15, int(attacker.max_hp * 0.25)))
            return 0, f"{attacker.name} used {attack['name']} and recovered {healed} HP!"
        if cat == "defensive":
            attacker.shield_turns = 2
            return 0, f"{attacker.name} activated {attack['name']} (defensive stance)!"
        if cat == "support":
            attacker.attack_stat = min(115.0, attacker.attack_stat + 5.0)
            return 0, f"{attacker.name} used {attack['name']} to bolster combat readiness!"

        base_power = CATEGORY_BASE_POWER.get(cat, 60)
        offense = attacker.strength_stat if cat == "physical" else attacker.attack_stat
        return resolve_technique_damage(
            attacker, defender, attack, base_power, offense, defender.defense_stat, self.rng
        )

    def run(self) -> BattleResult:
        rem_a = self.remaining_count(self.player_a_id)
        rem_b = self.remaining_count(self.player_b_id)
        if rem_a == 0 and rem_b == 0:
            return BattleResult(None, None, True, "BOTH_TEAMS_EMPTY", 0, self.seed, 0, 0, 0, 0, [])
        if rem_a == 0:
            return BattleResult(self.player_b_id, self.player_a_id, False, "TEAM_FORFEIT", 0, self.seed, 0, self.remaining_hp(self.player_b_id), 0, rem_b, [])
        if rem_b == 0:
            return BattleResult(self.player_a_id, self.player_b_id, False, "TEAM_FORFEIT", 0, self.seed, self.remaining_hp(self.player_a_id), 0, rem_a, 0, [])

        # Check unsupported-data state
        sup_a = any(c.has_verified_combat_data for c in self.teams[self.player_a_id])
        sup_b = any(c.has_verified_combat_data for c in self.teams[self.player_b_id])
        if not sup_a and not sup_b:
            return BattleResult(None, None, True, "UNSUPPORTED_COMBAT_DATA", 0, self.seed, self.remaining_hp(self.player_a_id), self.remaining_hp(self.player_b_id), rem_a, rem_b, [])
        if not sup_a:
            return BattleResult(self.player_b_id, self.player_a_id, False, "UNSUPPORTED_COMBAT_DATA", 0, self.seed, self.remaining_hp(self.player_a_id), self.remaining_hp(self.player_b_id), rem_a, rem_b, [])
        if not sup_b:
            return BattleResult(self.player_a_id, self.player_b_id, False, "UNSUPPORTED_COMBAT_DATA", 0, self.seed, self.remaining_hp(self.player_a_id), self.remaining_hp(self.player_b_id), rem_a, rem_b, [])

        turns = 0
        while turns < MAX_ANIME_TURNS:
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
                self.ai_selector.choose_anime_action(act_a, act_b, self.rng)
                if self.ai_selector
                else (BattleAction("attack", move_id=act_a.attacks[0]["id"]) if act_a.attacks else BattleAction("pass"))
            )
            dec_b = (
                self.ai_selector.choose_anime_action(act_b, act_a, self.rng)
                if self.ai_selector
                else (BattleAction("attack", move_id=act_b.attacks[0]["id"]) if act_b.attacks else BattleAction("pass"))
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

                if not char.has_verified_combat_data:
                    events.append(f"{char.name} has unsupported combat data and cannot attack.")
                    continue

                side = "a" if pid == self.player_a_id else "b"
                target_side = "b" if side == "a" else "a"

                if dec.action_type == "transform" and dec.transformation_id:
                    ok, msg = char.activate_transformation(dec.transformation_id)
                    events.append(msg)
                    if ok:
                        action_details.append({"event_type": "transform", "side": side, "move_name": char.active_transformation or "Transform"})
                elif dec.action_type == "attack":
                    atk = next((a for a in char.attacks if a["id"] == dec.move_id), char.attacks[0])
                    dmg, msg = self.resolve_attack(char, opp, atk)
                    events.append(msg)
                    cat = atk.get("category", "special")
                    anim_cat = "ranged" if atk.get("range") == "ranged" else (cat if cat in ("physical", "elemental") else "special")
                    action_details.append({
                        "event_type": "attack",
                        "side": side,
                        "target_side": target_side,
                        "attacker_id": char.combatant_id,
                        "defender_id": opp.combatant_id,
                        "move_name": atk["name"],
                        "category": anim_cat,
                        "damage": dmg,
                    })
                    if opp.is_fainted:
                        events.append(f"{opp.name} was defeated!")
                        action_details.append({"event_type": "faint", "side": target_side})

            for fighter in (act_a, act_b):
                end_nonpokemon_turn(fighter, events)

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
        return BattleResult(None, None, True, "DRAW", turns, self.seed, hp_a, hp_b, rem_a, rem_b, self.turn_log)
