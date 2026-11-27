"""
Cross-Universe Combat Adapter (Phase 3)
=======================================
Enables Pokémon and Anime combatants to battle in the same tournament when
players have mixed rosters or cross-franchise matchups, while preserving
native Pokémon mechanics and anime-specific abilities/transformations.

Same-system battles (Pokémon vs Pokémon, Anime vs Anime) continue to use
their dedicated native engines directly.
"""

import random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from src.anime_battle_engine import AnimeCombatant, CATEGORY_BASE_POWER
from src.battle_engine import LEVEL, PokemonCombatant, get_type_effectiveness
from src.marvel_battle_engine import MarvelCombatant, MARVEL_CATEGORY_POWER
from src.combat_interactions import end_nonpokemon_turn, resolve_technique_damage, spend_stamina
from src.battle_interface import BaseCombatant, BattleResult


@dataclass
class CrossUniverseConfig:
    """Explicit, configurable normalization parameters for cross-universe combat."""
    anime_hp_scale: float = 1.0
    pokemon_hp_scale: float = 1.0
    marvel_hp_scale: float = 1.0
    pokemon_cross_damage_scale: float = 1.0
    anime_cross_damage_scale: float = 1.0
    marvel_cross_damage_scale: float = 1.0
    cross_damage_scale: Optional[float] = None
    max_turns: int = 150

    def __post_init__(self):
        if self.cross_damage_scale is not None:
            self.pokemon_cross_damage_scale = self.cross_damage_scale
            self.anime_cross_damage_scale = self.cross_damage_scale


def _snapshot_combatant(c: BaseCombatant, image: str = "") -> Dict[str, Any]:
    return {
        "id": c.combatant_id,
        "name": c.name,
        "system": c.system,
        "image": image,
        "current_hp": c.current_hp,
        "max_hp": c.max_hp,
        "status": c.status,
        "fainted": c.is_fainted,
    }


class CrossUniverseBattleSimulator:
    """
    Deterministic turn-based simulator supporting mixed teams of
    PokemonCombatant and AnimeCombatant instances.
    """

    def __init__(
        self,
        player_a_id: str,
        team_a: List[BaseCombatant],
        player_b_id: str,
        team_b: List[BaseCombatant],
        seed: int = 42,
        ai_selector: Any = None,
        config: Optional[CrossUniverseConfig] = None,
        images_by_id: Optional[Dict[str, str]] = None,
    ):
        self.player_a_id = player_a_id
        self.player_b_id = player_b_id
        self.teams: Dict[str, List[BaseCombatant]] = {
            player_a_id: list(team_a),
            player_b_id: list(team_b),
        }
        self.active_idx: Dict[str, int] = {player_a_id: 0, player_b_id: 0}
        self.rng = random.Random(seed)
        self.seed = seed
        self.ai_selector = ai_selector
        self.config = config or CrossUniverseConfig()
        self.images_by_id = images_by_id or {}
        self.turn_log: List[Dict[str, Any]] = []

    def _is_eligible(self, c: BaseCombatant) -> bool:
        if c.is_fainted:
            return False
        if isinstance(c, (AnimeCombatant, MarvelCombatant)) and not c.has_verified_combat_data:
            return False
        return True

    def get_active(self, pid: str) -> Optional[BaseCombatant]:
        team = self.teams[pid]
        idx = self.active_idx[pid]
        if 0 <= idx < len(team) and self._is_eligible(team[idx]):
            return team[idx]
        for i, c in enumerate(team):
            if self._is_eligible(c):
                self.active_idx[pid] = i
                return c
        return None

    def remaining_count(self, pid: str) -> int:
        return sum(1 for c in self.teams[pid] if self._is_eligible(c))

    def remaining_hp(self, pid: str) -> int:
        return sum(max(0, c.current_hp) for c in self.teams[pid] if self._is_eligible(c))

    def _pokemon_vs_any_damage(
        self,
        attacker: PokemonCombatant,
        defender: BaseCombatant,
        move: dict,
    ) -> Tuple[int, str]:
        power = move.get("power") or 0
        category = move.get("category", "Status")
        if category == "Status" or power <= 0:
            meta = move.get("meta") or {}
            heal_pct = meta.get("healing", 0) or 0
            if heal_pct > 0:
                healed = attacker.heal(max(1, (attacker.max_hp * heal_pct) // 100))
                return 0, f"{attacker.name} used {move['name']} and restored {healed} HP!"
            return 0, f"{attacker.name} used {move['name']}!"

        acc = move.get("accuracy")
        if acc is not None and self.rng.random() * 100 >= acc:
            return 0, f"{attacker.name} used {move['name']}, but it missed!"

        mtype = move.get("type", "Normal")
        stab = 1.5 if mtype in attacker.types else 1.0
        is_crit = self.rng.random() < (1 / 24)
        crit_mult = 1.5 if is_crit else 1.0
        roll = self.rng.uniform(0.85, 1.0)

        if isinstance(defender, PokemonCombatant):
            type_mult = get_type_effectiveness(mtype, defender.types)
            if type_mult == 0.0:
                return 0, f"{attacker.name} used {move['name']}, but it doesn't affect {defender.name}!"
            atk_stat = attacker.get_stat("attack") if category == "Physical" else attacker.get_stat("special_attack")
            def_stat = defender.get_stat("defense") if category == "Physical" else defender.get_stat("special_defense")
            dmg = max(1, int(((((2 * LEVEL / 5 + 2) * power * (atk_stat / max(1.0, def_stat))) / 50) + 2) * stab * type_mult * crit_mult * roll))
        elif isinstance(defender, AnimeCombatant):
            # Cross-universe: Pokémon attacking AnimeCombatant (do NOT apply Pokémon type chart to anime)
            atk_stat = attacker.get_stat("attack") if category == "Physical" else attacker.get_stat("special_attack")
            # Normalize anime defense (1..100) into Level 50 defense range (~55..170)
            norm_def = 40.0 + defender.defense_stat * 1.2
            dmg = max(1, int((((((2 * LEVEL / 5 + 2) * power * (atk_stat / norm_def)) / 50) + 2) * stab * crit_mult * roll) * self.config.pokemon_cross_damage_scale))
        else:
            # Cross-universe: Pokémon attacking MarvelCombatant
            atk_stat = attacker.get_stat("attack") if category == "Physical" else attacker.get_stat("special_attack")
            norm_def = 40.0 + defender.durability_stat * 1.2
            dmg = max(1, int((((((2 * LEVEL / 5 + 2) * power * (atk_stat / norm_def)) / 50) + 2) * stab * crit_mult * roll) * self.config.pokemon_cross_damage_scale))

        actual = defender.take_damage(dmg)
        crit_txt = " Critical hit!" if is_crit else ""
        return actual, f"{attacker.name} used {move['name']} for {actual} damage!{crit_txt}"

    def _anime_vs_any_damage(
        self,
        attacker: AnimeCombatant,
        defender: BaseCombatant,
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
            return 0, f"{attacker.name} used {attack['name']} to boost power!"

        base_power = CATEGORY_BASE_POWER.get(cat, 60) * self.config.anime_cross_damage_scale
        offense = attacker.strength_stat if cat == "physical" else attacker.attack_stat
        if isinstance(defender, AnimeCombatant):
            defense = defender.defense_stat
        elif isinstance(defender, MarvelCombatant):
            defense = defender.durability_stat
        else:
            raw_defense = "defense" if cat in ("physical", "weapon") else "special_defense"
            defense = defender.get_stat(raw_defense) * 0.65
        return resolve_technique_damage(attacker, defender, attack, base_power, offense, defense, self.rng)

    def _marvel_vs_any_damage(
        self,
        attacker: MarvelCombatant,
        defender: BaseCombatant,
        attack: dict,
    ) -> Tuple[int, str]:
        if not spend_stamina(attacker, attack):
            return 0, f"{attacker.name} recovered stamina instead of using {attack['name']}."
        cat = attack.get("category", "physical")
        if cat == "defensive":
            attacker.shield_turns = 2
            return 0, f"{attacker.name} raised {attack['name']} (defensive shield)!"
        if cat == "healing":
            healed = attacker.heal(max(15, int(attacker.max_hp * 0.25)))
            return 0, f"{attacker.name} used {attack['name']} and recovered {healed} HP!"

        base_power = MARVEL_CATEGORY_POWER.get(cat, 68) * self.config.marvel_cross_damage_scale
        offense = attacker.strength_stat if cat in ("physical", "weapon") else attacker.energy_stat
        if isinstance(defender, AnimeCombatant):
            defense = defender.defense_stat
        elif isinstance(defender, MarvelCombatant):
            defense = defender.durability_stat
        else:
            raw_defense = "defense" if cat in ("physical", "weapon") else "special_defense"
            defense = defender.get_stat(raw_defense) * 0.65
        return resolve_technique_damage(attacker, defender, attack, base_power, offense, defense, self.rng)

    def run(self) -> BattleResult:
        rem_a = self.remaining_count(self.player_a_id)
        rem_b = self.remaining_count(self.player_b_id)
        if rem_a == 0 and rem_b == 0:
            return BattleResult(None, None, True, "NO_ELIGIBLE_COMBATANTS", 0, self.seed, 0, 0, 0, 0, [])
        if rem_a == 0:
            return BattleResult(self.player_b_id, self.player_a_id, False, "TEAM_FORFEIT_OR_UNSUPPORTED", 0, self.seed, 0, self.remaining_hp(self.player_b_id), 0, rem_b, [])
        if rem_b == 0:
            return BattleResult(self.player_a_id, self.player_b_id, False, "TEAM_FORFEIT_OR_UNSUPPORTED", 0, self.seed, self.remaining_hp(self.player_a_id), 0, rem_a, 0, [])

        turns = 0
        while turns < self.config.max_turns:
            if self.remaining_count(self.player_a_id) == 0 or self.remaining_count(self.player_b_id) == 0:
                break
            turns += 1
            events: List[str] = []
            action_details: List[dict] = []

            act_a = self.get_active(self.player_a_id)
            act_b = self.get_active(self.player_b_id)
            if not act_a or not act_b:
                break

            order = sorted(
                [(self.player_a_id, self.player_b_id, act_a), (self.player_b_id, self.player_a_id, act_b)],
                key=lambda item: (item[2].effective_speed, self.rng.random()),
                reverse=True,
            )

            for pid, opp_id, attacker in order:
                defender = self.get_active(opp_id)
                if attacker.is_fainted or not defender or defender.is_fainted:
                    continue
                side = "a" if pid == self.player_a_id else "b"
                target_side = "b" if side == "a" else "a"

                if isinstance(attacker, AnimeCombatant) and self.ai_selector:
                    dec = self.ai_selector.choose_anime_action(attacker, defender, self.rng)
                    if dec.action_type == "transform" and dec.transformation_id:
                        ok, msg = attacker.activate_transformation(dec.transformation_id)
                        events.append(msg)
                        if ok:
                            action_details.append({"event_type": "transform", "side": side, "move_name": attacker.active_transformation or "Transform"})
                        continue
                    atk = next((a for a in attacker.attacks if a["id"] == dec.move_id), attacker.attacks[0])
                    dmg, msg = self._anime_vs_any_damage(attacker, defender, atk)
                    events.append(msg)
                    action_details.append({"event_type": "attack", "side": side, "target_side": target_side, "attacker_id": attacker.combatant_id, "defender_id": defender.combatant_id, "move_name": atk["name"], "category": atk.get("category", "special"), "damage": dmg})
                elif isinstance(attacker, AnimeCombatant):
                    atk = attacker.attacks[0]
                    dmg, msg = self._anime_vs_any_damage(attacker, defender, atk)
                    events.append(msg)
                    action_details.append({"event_type": "attack", "side": side, "target_side": target_side, "attacker_id": attacker.combatant_id, "defender_id": defender.combatant_id, "move_name": atk["name"], "category": atk.get("category", "special"), "damage": dmg})
                elif isinstance(attacker, MarvelCombatant) and self.ai_selector:
                    dec = self.ai_selector.choose_marvel_action(attacker, defender, self.rng)
                    if dec.action_type == "transform" and dec.transformation_id:
                        ok, msg = attacker.activate_transformation(dec.transformation_id)
                        events.append(msg)
                        if ok:
                            action_details.append({"event_type": "transform", "side": side, "move_name": attacker.active_transformation or "Transform"})
                        continue
                    atk = next((a for a in attacker.attacks if a["id"] == dec.move_id), attacker.attacks[0])
                    dmg, msg = self._marvel_vs_any_damage(attacker, defender, atk)
                    events.append(msg)
                    action_details.append({"event_type": "attack", "side": side, "target_side": target_side, "attacker_id": attacker.combatant_id, "defender_id": defender.combatant_id, "move_name": atk["name"], "category": atk.get("category", "physical"), "damage": dmg})
                elif isinstance(attacker, MarvelCombatant):
                    atk = attacker.attacks[0]
                    dmg, msg = self._marvel_vs_any_damage(attacker, defender, atk)
                    events.append(msg)
                    action_details.append({"event_type": "attack", "side": side, "target_side": target_side, "attacker_id": attacker.combatant_id, "defender_id": defender.combatant_id, "move_name": atk["name"], "category": atk.get("category", "physical"), "damage": dmg})
                else:
                    moves = attacker.get_available_moves()
                    if moves:
                        dmg_moves = [m for m in moves if m.get("category") in ("Physical", "Special") and (m.get("power") or 0) > 0]
                        chosen = max(dmg_moves, key=lambda m: m.get("power") or 0) if dmg_moves else moves[0]
                    else:
                        chosen = {"id": "struggle", "name": "Struggle", "type": "Normal", "category": "Physical", "power": 50, "accuracy": None, "meta": {}}
                    dmg, msg = self._pokemon_vs_any_damage(attacker, defender, chosen)
                    events.append(msg)
                    action_details.append({"event_type": "attack", "side": side, "target_side": target_side, "attacker_id": attacker.combatant_id, "defender_id": defender.combatant_id, "move_name": chosen["name"], "category": "elemental" if chosen.get("category") == "Special" else "physical", "damage": dmg})

                if defender.is_fainted:
                    events.append(f"{defender.name} fainted!")
                    action_details.append({"event_type": "faint", "side": target_side})

            for fighter in (act_a, act_b):
                end_nonpokemon_turn(fighter, events)

            cur_a = self.get_active(self.player_a_id)
            cur_b = self.get_active(self.player_b_id)
            self.turn_log.append({
                "turn": turns,
                "events": events,
                "action_details": action_details,
                "active_a": _snapshot_combatant(cur_a, self.images_by_id.get(cur_a.combatant_id, "")) if cur_a else None,
                "active_b": _snapshot_combatant(cur_b, self.images_by_id.get(cur_b.combatant_id, "")) if cur_b else None,
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
