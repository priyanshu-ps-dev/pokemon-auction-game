"""
Pokémon Turn-Based Battle Engine (Phase 2)
========================================
Implements official-style Pokémon battle mechanics using Phase 1 PokéAPI data:
- Level 50 HP & stat scaling
- Physical / Special / Status split
- STAB, 18-type effectiveness & immunities (via src/type_chart.py)
- Critical hits, accuracy, priority, and speed-based turn order
- Stat-stage modifiers (-6 to +6)
- Status conditions (burn, paralysis, poison, toxic, sleep, freeze, confusion)
- Healing, drain, and recoil
- Ability hooks (Levitate, Intimidate, Sturdy, Overgrow/Blaze/Torrent/Swarm,
  Static, Flame Body, Poison Point, Flash Fire, Water Absorb, Volt Absorb,
  Thick Fat, Guts, Huge Power/Pure Power, Speed Boost, Multiscale)
- Switching, fainting, and unequal team elimination (1 to 6 Pokémon)
- Deterministic seeded RNG for reproducible simulations
"""

import random
from typing import Any, Dict, List, Optional, Tuple

from src.battle_interface import BaseCombatant, BattleAction, BattleResult
from src.type_chart import TYPE_CHART


LEVEL = 50
MAX_TURNS = 200


def get_type_effectiveness(move_type: str, defender_types: List[str]) -> float:
    """Calculates combined type multiplier using src/type_chart.py."""
    atk = move_type.capitalize()
    mult = 1.0
    for dt in defender_types:
        mult *= TYPE_CHART.get(atk, {}).get(dt.capitalize(), 1.0)
    return mult


def _stage_multiplier(stage: int) -> float:
    s = max(-6, min(6, stage))
    return (2.0 + s) / 2.0 if s >= 0 else 2.0 / (2.0 - s)


def _calc_hp(base_hp: int) -> int:
    return ((2 * max(1, base_hp) + 31) * LEVEL) // 100 + LEVEL + 10


def _calc_stat(base_val: int) -> int:
    return ((2 * max(1, base_val) + 31) * LEVEL) // 100 + 5


class PokemonCombatant(BaseCombatant):
    """Stateful in-battle representation of a single Pokémon."""

    def __init__(self, profile: dict):
        self._profile = profile
        self._id = str(profile.get("character_id") or f"pkmn_{profile.get('pokemon_id')}")
        self._name = profile.get("name", "Pokémon")
        self.pokemon_id = profile.get("pokemon_id")
        self.types: List[str] = list(profile.get("types", ["Normal"]))

        stats = profile.get("stats", {})
        base_hp = int(stats.get("hp", 50))
        base_atk = int(stats.get("attack", 50))
        base_def = int(stats.get("defense", stats.get("defense_raw", 50)))
        base_spa = int(stats.get("special_attack", 50))
        base_spd = int(stats.get("special_defense", 50))
        base_spe = int(stats.get("speed", stats.get("speed_raw", 50)))

        self._max_hp = _calc_hp(base_hp)
        self._current_hp = self._max_hp
        self.base_stats = {
            "attack": _calc_stat(base_atk),
            "defense": _calc_stat(base_def),
            "special_attack": _calc_stat(base_spa),
            "special_defense": _calc_stat(base_spd),
            "speed": _calc_stat(base_spe),
        }

        self.stat_stages: Dict[str, int] = {
            "attack": 0,
            "defense": 0,
            "special_attack": 0,
            "special_defense": 0,
            "speed": 0,
        }

        # Pick primary non-hidden ability by default
        abilities = profile.get("abilities", [])
        non_hidden = [a for a in abilities if not a.get("is_hidden")]
        chosen_ab = non_hidden[0] if non_hidden else (abilities[0] if abilities else {})
        self.ability_name: str = chosen_ab.get("name", "")
        self.flash_fire_boost: bool = False

        # Moveset (up to 4 legitimate moves, each with mutable PP)
        self.moves: List[Dict[str, Any]] = []
        for m in profile.get("default_moveset", [])[:4]:
            if m.get("is_main_series", True):
                m_copy = dict(m)
                m_copy["current_pp"] = m.get("pp") or 10
                self.moves.append(m_copy)

        self._status: Optional[str] = None
        self.status_turns: int = 0
        self.toxic_counter: int = 0
        self.confusion_turns: int = 0

    @property
    def combatant_id(self) -> str:
        return self._id

    @property
    def name(self) -> str:
        return self._name

    @property
    def system(self) -> str:
        return "pokemon"

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
        spe = self.base_stats["speed"] * _stage_multiplier(self.stat_stages["speed"])
        if self._status == "paralysis":
            spe *= 0.5
        return spe

    def get_stat(self, key: str, ignore_negative: bool = False, ignore_positive: bool = False) -> float:
        stage = self.stat_stages.get(key, 0)
        if ignore_negative and stage < 0:
            stage = 0
        if ignore_positive and stage > 0:
            stage = 0
        val = self.base_stats[key] * _stage_multiplier(stage)
        if key == "attack" and self.ability_name in ("Huge Power", "Pure Power"):
            val *= 2.0
        if key == "attack" and self.ability_name == "Guts" and self._status is not None:
            val *= 1.5
        return val

    def reset_stages(self):
        for k in self.stat_stages:
            self.stat_stages[k] = 0
        self.confusion_turns = 0
        self.toxic_counter = 0

    def take_damage(self, amount: int) -> int:
        if amount <= 0 or self.is_fainted:
            return 0
        # Sturdy: survive from full HP with 1 HP
        if (
            self.ability_name == "Sturdy"
            and self._current_hp == self._max_hp
            and amount >= self._current_hp
            and self._max_hp > 1
        ):
            amount = self._current_hp - 1
        actual = min(self._current_hp, amount)
        self._current_hp -= actual
        return actual

    def heal(self, amount: int) -> int:
        if amount <= 0 or self.is_fainted:
            return 0
        actual = min(self._max_hp - self._current_hp, amount)
        self._current_hp += actual
        return actual

    def apply_status(self, ailment: str, rng: random.Random) -> Tuple[bool, str]:
        if self.is_fainted or not ailment:
            return False, ""
        ail = ailment.lower()
        if ail == "confusion":
            if self.confusion_turns > 0:
                return False, f"{self.name} is already confused."
            self.confusion_turns = rng.randint(2, 5)
            return True, f"{self.name} became confused!"

        if self._status is not None:
            return False, f"{self.name} already has {self._status}."

        if ail == "burn" and "Fire" in self.types:
            return False, f"{self.name} is immune to burn."
        if ail == "paralysis" and "Electric" in self.types:
            return False, f"{self.name} is immune to paralysis."
        if ail in ("poison", "badly-poisoned", "toxic") and ("Poison" in self.types or "Steel" in self.types):
            return False, f"{self.name} is immune to poison."
        if ail == "freeze" and "Ice" in self.types:
            return False, f"{self.name} is immune to freeze."

        self._status = "toxic" if ail in ("badly-poisoned", "toxic") else ail
        self.status_turns = rng.randint(1, 3) if ail == "sleep" else 0
        self.toxic_counter = 1 if self._status == "toxic" else 0
        return True, f"{self.name} was afflicted with {self._status}!"

    def modify_stage(self, stat: str, delta: int) -> int:
        if stat not in self.stat_stages or delta == 0:
            return 0
        old = self.stat_stages[stat]
        new = max(-6, min(6, old + delta))
        self.stat_stages[stat] = new
        return new - old

    def get_available_moves(self) -> List[Dict[str, Any]]:
        return [m for m in self.moves if m.get("current_pp", 0) > 0]

    def get_available_transformations(self) -> List[Dict[str, Any]]:
        return []

    def to_summary_dict(self) -> Dict[str, Any]:
        return {
            "id": self.combatant_id,
            "name": self.name,
            "system": self.system,
            "types": self.types,
            "ability": self.ability_name,
            "current_hp": self._current_hp,
            "max_hp": self._max_hp,
            "status": self._status,
            "fainted": self.is_fainted,
        }


class PokemonBattleSimulator:
    """Deterministic, seeded turn-based Pokémon team battle simulator."""

    def __init__(
        self,
        player_a_id: str,
        team_a: List[PokemonCombatant],
        player_b_id: str,
        team_b: List[PokemonCombatant],
        seed: int = 42,
        ai_selector: Any = None,
    ):
        self.player_a_id = player_a_id
        self.player_b_id = player_b_id
        self.teams: Dict[str, List[PokemonCombatant]] = {
            player_a_id: list(team_a),
            player_b_id: list(team_b),
        }
        self.active_idx: Dict[str, int] = {player_a_id: 0, player_b_id: 0}
        self.rng = random.Random(seed)
        self.seed = seed
        self.ai_selector = ai_selector
        self.turn_log: List[Dict[str, Any]] = []

    def get_active(self, pid: str) -> Optional[PokemonCombatant]:
        team = self.teams[pid]
        idx = self.active_idx[pid]
        if 0 <= idx < len(team) and not team[idx].is_fainted:
            return team[idx]
        for i, mon in enumerate(team):
            if not mon.is_fainted:
                self.active_idx[pid] = i
                return mon
        return None

    def remaining_count(self, pid: str) -> int:
        return sum(1 for m in self.teams[pid] if not m.is_fainted)

    def remaining_hp(self, pid: str) -> int:
        return sum(max(0, m.current_hp) for m in self.teams[pid])

    def _trigger_entry_ability(self, entrant: PokemonCombatant, opponent: Optional[PokemonCombatant], events: List[str]):
        if opponent and not opponent.is_fainted and entrant.ability_name == "Intimidate":
            delta = opponent.modify_stage("attack", -1)
            if delta != 0:
                events.append(f"{entrant.name}'s Intimidate lowered {opponent.name}'s Attack!")

    def calculate_damage(
        self,
        attacker: PokemonCombatant,
        defender: PokemonCombatant,
        move: dict,
    ) -> Tuple[int, float, bool]:
        """Returns (damage, type_multiplier, is_crit)."""
        power = move.get("power") or 0
        if power <= 0:
            return 0, 1.0, False

        move_type = move.get("type", "Normal")
        category = move.get("category", "Physical")

        # Ability-based immunities & absorption
        if defender.ability_name == "Levitate" and move_type == "Ground":
            return 0, 0.0, False
        if defender.ability_name == "Flash Fire" and move_type == "Fire":
            defender.flash_fire_boost = True
            return 0, 0.0, False
        if defender.ability_name == "Water Absorb" and move_type == "Water":
            defender.heal(max(1, defender.max_hp // 4))
            return 0, 0.0, False
        if defender.ability_name == "Volt Absorb" and move_type == "Electric":
            defender.heal(max(1, defender.max_hp // 4))
            return 0, 0.0, False

        type_mult = get_type_effectiveness(move_type, defender.types)
        if type_mult == 0.0:
            return 0, 0.0, False

        # Critical hit check
        crit_stage = (move.get("meta") or {}).get("crit_rate", 0) or 0
        crit_chances = {0: 1 / 24, 1: 1 / 8, 2: 1 / 2}
        is_crit = self.rng.random() < crit_chances.get(crit_stage, 1.0)

        if category == "Physical":
            atk_stat = attacker.get_stat("attack", ignore_negative=is_crit)
            def_stat = defender.get_stat("defense", ignore_positive=is_crit)
        else:
            atk_stat = attacker.get_stat("special_attack", ignore_negative=is_crit)
            def_stat = defender.get_stat("special_defense", ignore_positive=is_crit)

        base_dmg = (((2 * LEVEL / 5 + 2) * power * (atk_stat / max(1.0, def_stat))) / 50) + 2

        # STAB
        stab = 1.5 if move_type in attacker.types else 1.0
        if stab > 1.0 and attacker.ability_name == "Adaptability":
            stab = 2.0

        # Pinch abilities (Overgrow / Blaze / Torrent / Swarm)
        pinch_map = {"Overgrow": "Grass", "Blaze": "Fire", "Torrent": "Water", "Swarm": "Bug"}
        if pinch_map.get(attacker.ability_name) == move_type and attacker.current_hp <= attacker.max_hp / 3:
            base_dmg *= 1.5

        if attacker.flash_fire_boost and move_type == "Fire":
            base_dmg *= 1.5

        if defender.ability_name == "Thick Fat" and move_type in ("Fire", "Ice"):
            base_dmg *= 0.5

        if defender.ability_name == "Multiscale" and defender.current_hp == defender.max_hp:
            base_dmg *= 0.5

        crit_mult = 1.5 if is_crit else 1.0
        roll = self.rng.uniform(0.85, 1.0)
        burn_mod = 0.5 if (category == "Physical" and attacker.status == "burn" and attacker.ability_name != "Guts") else 1.0

        final_dmg = max(1, int(base_dmg * stab * type_mult * crit_mult * roll * burn_mod))
        return final_dmg, type_mult, is_crit

    def _choose_action(self, pid: str, opp_id: str) -> BattleAction:
        active = self.get_active(pid)
        opp = self.get_active(opp_id)
        if not active or not opp:
            return BattleAction(action_type="pass")
        if self.ai_selector is not None:
            return self.ai_selector.choose_pokemon_action(active, self.teams[pid], opp, self.rng)
        moves = active.get_available_moves()
        if moves:
            return BattleAction(action_type="attack", move_id=moves[0]["id"])
        return BattleAction(action_type="attack", move_id="struggle")

    def _execute_attack(
        self,
        attacker: PokemonCombatant,
        defender: PokemonCombatant,
        move: dict,
        events: List[str],
        action_details: Optional[List[dict]] = None,
        side: str = "a",
        target_side: str = "b",
    ):
        # Status pre-checks
        if attacker.status == "sleep":
            if attacker.status_turns > 0:
                attacker.status_turns -= 1
                events.append(f"{attacker.name} is fast asleep.")
                return
            attacker._status = None
            events.append(f"{attacker.name} woke up!")

        if attacker.status == "freeze":
            if move.get("type") == "Fire" or self.rng.random() < 0.20:
                attacker._status = None
                events.append(f"{attacker.name} thawed out!")
            else:
                events.append(f"{attacker.name} is frozen solid!")
                return

        if attacker.status == "paralysis" and self.rng.random() < 0.25:
            events.append(f"{attacker.name} is paralyzed and couldn't move!")
            return

        if attacker.confusion_turns > 0:
            attacker.confusion_turns -= 1
            if attacker.confusion_turns == 0:
                events.append(f"{attacker.name} snapped out of confusion!")
            elif self.rng.random() < 0.33:
                self_dmg = max(1, int((((2 * LEVEL / 5 + 2) * 40 * (attacker.get_stat("attack") / max(1.0, attacker.get_stat("defense")))) / 50) + 2))
                attacker.take_damage(self_dmg)
                events.append(f"{attacker.name} hurt itself in its confusion for {self_dmg} damage!")
                return

        if "current_pp" in move and move["current_pp"] > 0:
            move["current_pp"] -= 1

        acc = move.get("accuracy")
        if acc is not None and self.rng.random() * 100 >= acc:
            events.append(f"{attacker.name} used {move['name']}, but it missed!")
            return

        category = move.get("category", "Status")
        meta = move.get("meta") or {}

        if category in ("Physical", "Special"):
            dmg, type_mult, is_crit = self.calculate_damage(attacker, defender, move)
            if type_mult == 0.0:
                events.append(f"{attacker.name} used {move['name']}, but it doesn't affect {defender.name}!")
                return

            actual = defender.take_damage(dmg)
            eff_tag = " (Super effective!)" if type_mult > 1.0 else (" (Not very effective)" if type_mult < 1.0 else "")
            crit_tag = " Critical hit!" if is_crit else ""
            events.append(f"{attacker.name} used {move['name']} for {actual} damage!{crit_tag}{eff_tag}")
            if action_details is not None:
                action_details.append({
                    "event_type": "attack",
                    "side": side,
                    "target_side": target_side,
                    "move_name": move["name"],
                    "category": "elemental" if move.get("category") == "Special" else "physical",
                    "damage": actual,
                    "is_crit": is_crit,
                    "effectiveness": type_mult,
                })

            # Drain or recoil
            drain_pct = meta.get("drain", 0) or 0
            if drain_pct > 0 and actual > 0:
                healed = attacker.heal(max(1, (actual * drain_pct) // 100))
                if healed > 0:
                    events.append(f"{attacker.name} drained {healed} HP!")
            elif drain_pct < 0 and actual > 0:
                recoil = max(1, (actual * abs(drain_pct)) // 100)
                attacker.take_damage(recoil)
                events.append(f"{attacker.name} took {recoil} recoil damage!")

            # Contact-style ability triggers on Physical hits
            if category == "Physical" and not defender.is_fainted:
                if defender.ability_name == "Static" and self.rng.random() < 0.30:
                    ok, msg = attacker.apply_status("paralysis", self.rng)
                    if ok:
                        events.append(msg)
                elif defender.ability_name == "Flame Body" and self.rng.random() < 0.30:
                    ok, msg = attacker.apply_status("burn", self.rng)
                    if ok:
                        events.append(msg)
                elif defender.ability_name == "Poison Point" and self.rng.random() < 0.30:
                    ok, msg = attacker.apply_status("poison", self.rng)
                    if ok:
                        events.append(msg)
        else:
            events.append(f"{attacker.name} used {move['name']}!")

        # Healing move
        heal_pct = meta.get("healing", 0) or 0
        if heal_pct > 0 and not attacker.is_fainted:
            healed = attacker.heal(max(1, (attacker.max_hp * heal_pct) // 100))
            if healed > 0:
                events.append(f"{attacker.name} restored {healed} HP!")

        # Secondary / Status ailments
        ailment = meta.get("ailment")
        ail_chance = meta.get("ailment_chance", 0) or (100 if category == "Status" and ailment else 0)
        if ailment and not defender.is_fainted and self.rng.random() * 100 < ail_chance:
            ok, msg = defender.apply_status(ailment, self.rng)
            if ok:
                events.append(msg)

        # Stat-stage changes
        stat_changes = meta.get("stat_changes", [])
        stat_chance = meta.get("stat_chance", 0) or (100 if category == "Status" and stat_changes else 0)
        if stat_changes and self.rng.random() * 100 < stat_chance:
            target_mon = attacker if move.get("target") == "user" else defender
            if not target_mon.is_fainted:
                for sc in stat_changes:
                    delta = target_mon.modify_stage(sc["stat"], sc["change"])
                    if delta != 0:
                        direction = "rose" if delta > 0 else "fell"
                        events.append(f"{target_mon.name}'s {sc['stat']} {direction}!")

    def _end_of_turn(self, events: List[str]):
        for pid in (self.player_a_id, self.player_b_id):
            mon = self.get_active(pid)
            if not mon or mon.is_fainted:
                continue
            if mon.status == "burn":
                dmg = max(1, mon.max_hp // 16)
                mon.take_damage(dmg)
                events.append(f"{mon.name} was hurt by its burn ({dmg} dmg).")
            elif mon.status == "poison":
                dmg = max(1, mon.max_hp // 8)
                mon.take_damage(dmg)
                events.append(f"{mon.name} was hurt by poison ({dmg} dmg).")
            elif mon.status == "toxic":
                dmg = max(1, (mon.max_hp * mon.toxic_counter) // 16)
                mon.toxic_counter += 1
                mon.take_damage(dmg)
                events.append(f"{mon.name} was hurt by toxic ({dmg} dmg).")

            if not mon.is_fainted and mon.ability_name == "Speed Boost":
                if mon.modify_stage("speed", 1) > 0:
                    events.append(f"{mon.name}'s Speed Boost raised its Speed!")

    def run(self) -> BattleResult:
        # Handle empty teams immediately
        rem_a = self.remaining_count(self.player_a_id)
        rem_b = self.remaining_count(self.player_b_id)
        if rem_a == 0 and rem_b == 0:
            return BattleResult(None, None, True, "BOTH_TEAMS_EMPTY", 0, self.seed, 0, 0, 0, 0, [])
        if rem_a == 0:
            return BattleResult(self.player_b_id, self.player_a_id, False, "TEAM_FORFEIT", 0, self.seed, 0, self.remaining_hp(self.player_b_id), 0, rem_b, [])
        if rem_b == 0:
            return BattleResult(self.player_a_id, self.player_b_id, False, "TEAM_FORFEIT", 0, self.seed, self.remaining_hp(self.player_a_id), 0, rem_a, 0, [])

        init_events: List[str] = []
        act_a = self.get_active(self.player_a_id)
        act_b = self.get_active(self.player_b_id)
        if act_a and act_b:
            self._trigger_entry_ability(act_a, act_b, init_events)
            self._trigger_entry_ability(act_b, act_a, init_events)

        turns = 0
        while turns < MAX_TURNS:
            if self.remaining_count(self.player_a_id) == 0 or self.remaining_count(self.player_b_id) == 0:
                break
            turns += 1
            events: List[str] = []
            action_details: List[dict] = []

            action_a = self._choose_action(self.player_a_id, self.player_b_id)
            action_b = self._choose_action(self.player_b_id, self.player_a_id)

            def _priority_key(pid: str, act: BattleAction) -> Tuple[int, float, float]:
                if act.action_type == "switch":
                    return (6, 9999.0, self.rng.random())
                mon = self.get_active(pid)
                prio = 0
                if act.action_type == "attack" and mon:
                    m = next((mv for mv in mon.moves if mv["id"] == act.move_id), None)
                    prio = m.get("priority", 0) if m else 0
                spe = mon.effective_speed if mon else 0.0
                return (prio, spe, self.rng.random())

            order = sorted(
                [(self.player_a_id, self.player_b_id, action_a), (self.player_b_id, self.player_a_id, action_b)],
                key=lambda item: _priority_key(item[0], item[2]),
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
                        mon.reset_stages()
                        self.active_idx[pid] = act.switch_index
                        new_mon = team[act.switch_index]
                        events.append(f"{pid} switched {mon.name} out for {new_mon.name}!")
                        action_details.append({"event_type": "switch", "side": side, "move_name": f"Switch -> {new_mon.name}"})
                        self._trigger_entry_ability(new_mon, opp, events)
                elif act.action_type == "attack":
                    move = next((mv for mv in mon.moves if mv["id"] == act.move_id and mv.get("current_pp", 0) > 0), None)
                    if move is None:
                        move = {
                            "id": "struggle",
                            "name": "Struggle",
                            "type": "Normal",
                            "category": "Physical",
                            "power": 50,
                            "accuracy": None,
                            "priority": 0,
                            "meta": {"drain": -25},
                        }
                    self._execute_attack(mon, opp, move, events, action_details, side, target_side)
                    if opp.is_fainted:
                        events.append(f"{opp.name} fainted!")
                        action_details.append({"event_type": "faint", "side": target_side})

            self._end_of_turn(events)

            # Force switch for any fainted active Pokémon
            for pid, opp_id in ((self.player_a_id, self.player_b_id), (self.player_b_id, self.player_a_id)):
                team = self.teams[pid]
                idx = self.active_idx[pid]
                if 0 <= idx < len(team) and team[idx].is_fainted:
                    next_mon = self.get_active(pid)
                    if next_mon:
                        events.append(f"{next_mon.name} entered the battle!")
                        self._trigger_entry_ability(next_mon, self.get_active(opp_id), events)

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

        # Turn limit tiebreaker by remaining HP% / HP
        if hp_a > hp_b:
            return BattleResult(self.player_a_id, self.player_b_id, False, "TIME_LIMIT_HP", turns, self.seed, hp_a, hp_b, rem_a, rem_b, self.turn_log)
        if hp_b > hp_a:
            return BattleResult(self.player_b_id, self.player_a_id, False, "TIME_LIMIT_HP", turns, self.seed, hp_a, hp_b, rem_a, rem_b, self.turn_log)
        return BattleResult(None, None, True, "DRAW", turns, self.seed, hp_a, hp_b, rem_a, rem_b, self.turn_log)
