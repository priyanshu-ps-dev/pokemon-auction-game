"""
Battle Balancing & Simulation Telemetry Framework (Phase 4)
=========================================================
Runs controlled, seeded repeated simulations across Pokémon, Anime, and
Cross-Universe matchups to measure win rates, duration, HP retention,
move usage, ability activations, transformations, forfeits, and draws.
"""

import json
from collections import Counter
from typing import Any, Dict, List, Optional

from src.battle_manager import BattleManager
from src.combat_data import CombatDataProvider


def run_matchup_series(
    manager: BattleManager,
    label: str,
    team_a_ids: List[str],
    team_b_ids: List[str],
    seeds: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """Runs repeated seeded 1v1 simulations and collects telemetry."""
    seeds = seeds or list(range(100, 110))
    team_a = [manager.provider.get_combat_profile(cid) for cid in team_a_ids]
    team_b = [manager.provider.get_combat_profile(cid) for cid in team_b_ids]

    a_wins = 0
    b_wins = 0
    draws = 0
    forfeits = 0
    total_turns = 0
    total_hp_a = 0
    total_hp_b = 0
    move_usage: Counter = Counter()
    ability_activations = 0
    transform_usage = 0

    for s in seeds:
        res = manager.simulate_1v1("team_a", team_a, "team_b", team_b, seed=s)
        total_turns += res.turns_played
        total_hp_a += res.player_a_remaining_hp
        total_hp_b += res.player_b_remaining_hp

        if "FORFEIT" in res.reason or "UNSUPPORTED" in res.reason:
            forfeits += 1
        if res.is_draw or res.winner_id is None:
            draws += 1
        elif res.winner_id == "team_a":
            a_wins += 1
        else:
            b_wins += 1

        for turn in res.turn_log:
            for d in turn.get("action_details", []):
                if d.get("event_type") == "attack" and d.get("move_name"):
                    move_usage[d["move_name"]] += 1
                elif d.get("event_type") == "transform":
                    transform_usage += 1
            for ev in turn.get("events", []):
                if any(ab in ev for ab in ("Intimidate", "Speed Boost", "Sturdy", "Levitate", "regenerated")):
                    ability_activations += 1

    n = max(1, len(seeds))
    return {
        "matchup": label,
        "runs": len(seeds),
        "seeds": seeds,
        "team_a_win_rate": round(a_wins / n, 3),
        "team_b_win_rate": round(b_wins / n, 3),
        "draw_rate": round(draws / n, 3),
        "forfeit_rate": round(forfeits / n, 3),
        "avg_turns": round(total_turns / n, 2),
        "avg_remaining_hp_a": round(total_hp_a / n, 1),
        "avg_remaining_hp_b": round(total_hp_b / n, 1),
        "top_moves": move_usage.most_common(5),
        "ability_activations": ability_activations,
        "transformation_usage": transform_usage,
    }


def run_balance_suite(runs_per_matchup: int = 10) -> List[Dict[str, Any]]:
    """Executes all 10 controlled balance evaluation scenarios."""
    provider = CombatDataProvider()
    manager = BattleManager(provider)
    seeds = list(range(1000, 1000 + runs_per_matchup))

    scenarios = [
        ("1_S_tier_vs_B_tier", ["pkmn_149"], ["pkmn_25"]),             # Dragonite vs Pikachu
        ("2_Legendary_vs_Ordinary", ["pkmn_150"], ["pkmn_19"]),         # Mewtwo vs Rattata
        ("3_Type_Adv_vs_Raw_Stat", ["pkmn_131"], ["pkmn_149"]),         # Lapras (4x Ice) vs Dragonite
        ("4_Small_Elite_2_vs_Large_Weak_5", ["pkmn_150", "pkmn_384"], ["pkmn_129", "pkmn_191", "pkmn_129", "pkmn_191", "pkmn_129"]),
        ("5_Mixed_Moves_vs_Monotype", ["pkmn_6"], ["pkmn_136"]),        # Charizard vs Flareon
        ("6_Ability_Gyarados_vs_Machamp", ["pkmn_130"], ["pkmn_68"]),   # Intimidate Gyarados vs Machamp
        ("7_Speed_Control_Gengar_vs_Snorlax", ["pkmn_94"], ["pkmn_143"]),
        ("8_Anime_Transform_Goku_vs_Vegeta", ["db_goku"], ["db_vegeta"]),
        ("9_Pokemon_vs_Anime_Charizard_vs_Luffy", ["pkmn_6"], ["anilist_40"]),
        ("10_Anime_Gojo_vs_Sukuna", ["anilist_127691"], ["jjk_sukuna"]),
    ]

    return [run_matchup_series(manager, lbl, a, b, seeds) for lbl, a, b in scenarios]


if __name__ == "__main__":
    results = run_balance_suite(10)
    print(json.dumps(results, indent=2))
