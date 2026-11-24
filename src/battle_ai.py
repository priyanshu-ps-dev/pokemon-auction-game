"""
Strategic Battle AI (Phase 2)
=============================
Selects legal moves, switches, and transformations for both Pokémon and
Anime combatants using reproducible seeded randomness and tactical heuristics.
"""

import random
from typing import List, Optional

from src.battle_engine import PokemonCombatant, get_type_effectiveness
from src.anime_battle_engine import AnimeCombatant, CATEGORY_BASE_POWER
from src.marvel_battle_engine import MarvelCombatant, MARVEL_CATEGORY_POWER
from src.battle_interface import BaseCombatant, BattleAction


class TacticalBattleAI:
    """Heuristic AI for Pokémon and Anime battles."""

    def _estimate_pokemon_move_score(
        self,
        attacker: PokemonCombatant,
        defender: PokemonCombatant,
        move: dict,
    ) -> float:
        mtype = move.get("type", "Normal")
        cat = move.get("category", "Status")
        meta = move.get("meta") or {}

        # Avoid wasting turns on ability-immune moves
        if defender.ability_name == "Levitate" and mtype == "Ground":
            return 0.0
        if defender.ability_name == "Flash Fire" and mtype == "Fire":
            return 0.0
        if defender.ability_name == "Water Absorb" and mtype == "Water":
            return 0.0
        if defender.ability_name == "Volt Absorb" and mtype == "Electric":
            return 0.0

        if cat in ("Physical", "Special"):
            eff = get_type_effectiveness(mtype, defender.types)
            if eff == 0.0:
                return 0.0
            power = move.get("power") or 0
            acc = (move.get("accuracy") or 100) / 100.0
            stab = 1.5 if mtype in attacker.types else 1.0
            stat_ratio = (
                attacker.get_stat("attack") / max(1.0, defender.get_stat("defense"))
                if cat == "Physical"
                else attacker.get_stat("special_attack") / max(1.0, defender.get_stat("special_defense"))
            )
            score = power * stab * eff * acc * min(2.5, max(0.4, stat_ratio))
            if (move.get("priority") or 0) > 0 and defender.current_hp <= defender.max_hp * 0.25:
                score *= 1.3
            return score

        # Status move scoring
        hp_ratio = attacker.current_hp / max(1, attacker.max_hp)
        if (meta.get("healing") or 0) > 0:
            return 95.0 if hp_ratio < 0.45 else 5.0

        ailment = meta.get("ailment")
        if ailment and defender.status is None:
            if ailment == "burn" and "Fire" in defender.types:
                return 0.0
            if ailment == "paralysis" and "Electric" in defender.types:
                return 0.0
            if ailment in ("poison", "badly-poisoned", "toxic") and ("Poison" in defender.types or "Steel" in defender.types):
                return 0.0
            return 55.0 if hp_ratio > 0.4 else 15.0

        if meta.get("stat_changes"):
            return 45.0 if hp_ratio > 0.6 else 10.0

        return 5.0

    def choose_pokemon_action(
        self,
        active: PokemonCombatant,
        team: List[PokemonCombatant],
        opponent: PokemonCombatant,
        rng: random.Random,
    ) -> BattleAction:
        moves = active.get_available_moves()
        if not moves:
            return BattleAction(action_type="attack", move_id="struggle")

        scored = [(self._estimate_pokemon_move_score(active, opponent, m), m) for m in moves]
        best_score = max(s for s, _ in scored)

        # Switch if current Pokémon has no effective move and a healthy teammate has a better matchup
        if best_score <= 15.0:
            for idx, mate in enumerate(team):
                if mate is active or mate.is_fainted:
                    continue
                mate_moves = mate.get_available_moves()
                if not mate_moves:
                    continue
                mate_best = max(self._estimate_pokemon_move_score(mate, opponent, m) for m in mate_moves)
                if mate_best > best_score * 2.0 and mate_best >= 40.0:
                    return BattleAction(action_type="switch", switch_index=idx)

        # Pick among top-scoring moves with small seeded jitter so AI is tactical yet varied
        threshold = best_score * 0.85
        candidates = [m for s, m in scored if s >= threshold and s > 0]
        if not candidates:
            candidates = moves
        chosen = rng.choice(candidates)
        return BattleAction(action_type="attack", move_id=chosen["id"])

    def choose_anime_action(
        self,
        active: AnimeCombatant,
        opponent: AnimeCombatant,
        rng: random.Random,
    ) -> BattleAction:
        transforms = active.get_available_transformations()
        if transforms and active.current_hp <= active.max_hp * 0.75:
            return BattleAction(action_type="transform", transformation_id=transforms[0]["id"])

        attacks = active.get_available_moves()
        if not attacks:
            return BattleAction(action_type="pass")

        hp_ratio = active.current_hp / max(1, active.max_hp)
        scored = []
        for atk in attacks:
            cat = atk.get("category", "unknown")
            if cat == "healing":
                s = 90.0 if hp_ratio < 0.45 else 10.0
            elif cat == "defensive":
                s = 60.0 if active.shield_turns == 0 and hp_ratio < 0.65 else 10.0
            elif cat == "support":
                s = 40.0 if hp_ratio > 0.6 else 10.0
            else:
                s = float(CATEGORY_BASE_POWER.get(cat, 60))
            scored.append((s, atk))

        best = max(s for s, _ in scored)
        top = [a for s, a in scored if s >= best * 0.85]
        chosen = rng.choice(top)
        return BattleAction(action_type="attack", move_id=chosen["id"])

    def choose_marvel_action(
        self,
        active: MarvelCombatant,
        opponent: BaseCombatant,
        rng: random.Random,
    ) -> BattleAction:
        transforms = active.get_available_transformations()
        if transforms and active.current_hp <= active.max_hp * 0.75:
            return BattleAction(action_type="transform", transformation_id=transforms[0]["id"])

        attacks = active.get_available_moves()
        if not attacks:
            return BattleAction(action_type="pass")

        hp_ratio = active.current_hp / max(1, active.max_hp)
        scored = []
        for atk in attacks:
            cat = atk.get("category", "physical")
            if cat == "healing":
                s = 90.0 if hp_ratio < 0.45 else 10.0
            elif cat == "defensive":
                s = 60.0 if active.shield_turns == 0 and hp_ratio < 0.65 else 10.0
            else:
                s = float(MARVEL_CATEGORY_POWER.get(cat, 68))
            scored.append((s, atk))

        best = max(s for s, _ in scored)
        top = [a for s, a in scored if s >= best * 0.85]
        chosen = rng.choice(top)
        return BattleAction(action_type="attack", move_id=chosen["id"])
