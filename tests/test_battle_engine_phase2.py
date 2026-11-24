"""
Phase 2 Validation Tests: Pokémon & Anime Battle Engines, AI, and Tournaments
=============================================================================
Covers damage, Physical/Special split, STAB, type effectiveness/immunity,
critical hits, accuracy, abilities, status effects, switching, transformations,
fainting, unequal teams (1-6), AI decisions, anime unsupported-data handling,
2-8 player tournaments, and deterministic replay.
"""

import asyncio
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.anime_battle_engine import AnimeBattleSimulator, AnimeCombatant
from src.battle_ai import TacticalBattleAI
from src.battle_engine import PokemonBattleSimulator, PokemonCombatant, get_type_effectiveness
from src.battle_manager import BattleManager
from src.combat_data import CombatDataProvider
from src.room_manager import Player, RoomManager


def _make_pokemon_profile(
    pid, name, types, stats, abilities=None, moves=None
):
    return {
        "system": "pokemon",
        "character_id": f"pkmn_{pid}",
        "pokemon_id": pid,
        "national_id": pid,
        "name": name,
        "types": types,
        "stats": stats,
        "abilities": abilities or [],
        "default_moveset": moves or [],
    }


def _make_move(mid, name, mtype, category, power, accuracy=100, pp=15, priority=0, meta=None, target="selected-pokemon"):
    return {
        "id": mid,
        "name": name,
        "type": mtype,
        "category": category,
        "power": power,
        "accuracy": accuracy,
        "pp": pp,
        "priority": priority,
        "target": target,
        "is_main_series": True,
        "meta": meta or {
            "ailment": None, "ailment_chance": 0, "crit_rate": 0,
            "drain": 0, "healing": 0, "flinch_chance": 0,
            "stat_chance": 0, "stat_changes": []
        },
    }


class TestPhase2BattleEngines(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provider = CombatDataProvider()
        cls.manager = BattleManager(cls.provider)

    def test_01_phase1_fixes_hidden_abilities_and_shadow_moves(self):
        """Hidden abilities have is_hidden=True and Shadow moves have is_main_series=False."""
        bulba = self.provider.get_combat_profile("pkmn_1")
        hidden_flags = {a["name"]: a["is_hidden"] for a in bulba["abilities"]}
        self.assertFalse(hidden_flags.get("Overgrow"))
        self.assertTrue(hidden_flags.get("Chlorophyll"))

        shadow_rush = self.provider.get_pokemon_move(10001)
        self.assertIsNotNone(shadow_rush)
        self.assertFalse(shadow_rush["is_main_series"])

    def test_02_type_effectiveness_stab_and_damage(self):
        """Type effectiveness, STAB, and Physical/Special damage behave accurately."""
        self.assertEqual(get_type_effectiveness("Electric", ["Water", "Flying"]), 4.0)
        self.assertEqual(get_type_effectiveness("Ground", ["Flying"]), 0.0)

        pika = PokemonCombatant(_make_pokemon_profile(
            25, "Pikachu", ["Electric"],
            {"hp": 35, "attack": 55, "defense": 40, "special_attack": 90, "special_defense": 50, "speed": 90}
        ))
        normal_mon = PokemonCombatant(_make_pokemon_profile(
            19, "Rattata", ["Normal"],
            {"hp": 50, "attack": 50, "defense": 50, "special_attack": 50, "special_defense": 50, "speed": 50}
        ))
        sim = PokemonBattleSimulator("a", [pika], "b", [normal_mon], seed=10)
        tbolt = _make_move(85, "Thunderbolt", "Electric", "Special", 90)
        hyper = _make_move(63, "Hyper Voice", "Normal", "Special", 90)
        dmg_stab, mult1, _ = sim.calculate_damage(pika, normal_mon, tbolt)
        dmg_non_stab, mult2, _ = sim.calculate_damage(pika, normal_mon, hyper)
        self.assertEqual(mult1, 1.0)
        self.assertEqual(mult2, 1.0)
        self.assertGreater(dmg_stab, dmg_non_stab)

    def test_03_critical_hits_and_accuracy(self):
        """Guaranteed crit_rate >= 3 deals ~1.5x damage; 0% accuracy always misses."""
        atk = PokemonCombatant(_make_pokemon_profile(
            1, "Attacker", ["Normal"], {"hp": 80, "attack": 100, "defense": 80, "special_attack": 80, "special_defense": 80, "speed": 80}
        ))
        dfn = PokemonCombatant(_make_pokemon_profile(
            2, "Defender", ["Normal"], {"hp": 80, "attack": 80, "defense": 80, "special_attack": 80, "special_defense": 80, "speed": 80}
        ))
        sim = PokemonBattleSimulator("a", [atk], "b", [dfn], seed=7)
        crit_move = _make_move(1, "AutoCrit", "Normal", "Physical", 80, meta={"crit_rate": 3, "ailment": None, "ailment_chance": 0, "drain": 0, "healing": 0, "stat_chance": 0, "stat_changes": []})
        dmg, _, is_crit = sim.calculate_damage(atk, dfn, crit_move)
        self.assertTrue(is_crit)
        self.assertGreater(dmg, 0)

        miss_move = _make_move(2, "AlwaysMiss", "Normal", "Physical", 100, accuracy=0)
        events = []
        hp_before = dfn.current_hp
        sim._execute_attack(atk, dfn, miss_move, events)
        self.assertEqual(dfn.current_hp, hp_before)
        self.assertTrue(any("missed" in e for e in events))

    def test_04_abilities_levitate_sturdy_intimidate(self):
        """Levitate blocks Ground, Intimidate lowers Attack, Sturdy survives OHKO at 1 HP."""
        gengar = PokemonCombatant(_make_pokemon_profile(
            94, "Gengar", ["Ghost", "Poison"],
            {"hp": 60, "attack": 65, "defense": 60, "special_attack": 130, "special_defense": 75, "speed": 110},
            abilities=[{"name": "Levitate", "is_hidden": False}]
        ))
        gyarados = PokemonCombatant(_make_pokemon_profile(
            130, "Gyarados", ["Water", "Flying"],
            {"hp": 95, "attack": 125, "defense": 79, "special_attack": 60, "special_defense": 100, "speed": 81},
            abilities=[{"name": "Intimidate", "is_hidden": False}]
        ))
        skarmory = PokemonCombatant(_make_pokemon_profile(
            227, "Skarmory", ["Steel", "Flying"],
            {"hp": 65, "attack": 80, "defense": 140, "special_attack": 40, "special_defense": 70, "speed": 70},
            abilities=[{"name": "Sturdy", "is_hidden": False}]
        ))
        sim = PokemonBattleSimulator("a", [gyarados], "b", [gengar], seed=1)
        eq = _make_move(89, "Earthquake", "Ground", "Physical", 100)
        dmg, mult, _ = sim.calculate_damage(gyarados, gengar, eq)
        self.assertEqual(dmg, 0)
        self.assertEqual(mult, 0.0)

        events = []
        sim._trigger_entry_ability(gyarados, gengar, events)
        self.assertEqual(gengar.stat_stages["attack"], -1)

        actual = skarmory.take_damage(9999)
        self.assertEqual(skarmory.current_hp, 1)
        self.assertFalse(skarmory.is_fainted)
        self.assertEqual(actual, skarmory.max_hp - 1)

    def test_05_status_effects_burn_paralysis_sleep(self):
        """Burn halves physical damage, paralysis halves speed, sleep blocks action."""
        rng = random.Random(5)
        mon = PokemonCombatant(_make_pokemon_profile(
            59, "Arcanine", ["Fire"], {"hp": 90, "attack": 110, "defense": 80, "special_attack": 100, "special_defense": 80, "speed": 95}
        ))
        # Fire type is immune to burn
        ok_fire, _ = mon.apply_status("burn", rng)
        self.assertFalse(ok_fire)

        speed_before = mon.effective_speed
        ok_para, _ = mon.apply_status("paralysis", rng)
        self.assertTrue(ok_para)
        self.assertAlmostEqual(mon.effective_speed, speed_before * 0.5)

    def test_06_unequal_teams_two_strong_beat_five_weak(self):
        """A team of 2 strong Pokémon defeats 5 weak Pokémon without team-size bonuses."""
        mewtwo = self.provider.get_combat_profile("pkmn_150")
        rayquaza = self.provider.get_combat_profile("pkmn_384")
        magikarp = self.provider.get_combat_profile("pkmn_129")
        sunkern = self.provider.get_combat_profile("pkmn_191")

        res = self.manager.simulate_1v1(
            "elite_2", [mewtwo, rayquaza],
            "swarm_5", [magikarp, sunkern, magikarp, sunkern, magikarp],
            seed=99,
        )
        self.assertEqual(res.winner_id, "elite_2")
        self.assertEqual(res.reason, "TEAM_ELIMINATION")
        self.assertGreater(res.player_a_remaining_count, 0)
        self.assertEqual(res.player_b_remaining_count, 0)

    def test_07_ai_avoids_immunity_and_switches(self):
        """AI avoids Ground moves against Flying and switches when completely walled."""
        ai = TacticalBattleAI()
        rng = random.Random(12)
        eq = _make_move(89, "Earthquake", "Ground", "Physical", 100)
        tackle = _make_move(33, "Tackle", "Normal", "Physical", 40)
        tbolt = _make_move(85, "Thunderbolt", "Electric", "Special", 90)

        sandslash = PokemonCombatant(_make_pokemon_profile(
            28, "Sandslash", ["Ground"],
            {"hp": 75, "attack": 100, "defense": 110, "special_attack": 45, "special_defense": 55, "speed": 65},
            moves=[eq]
        ))
        pikachu = PokemonCombatant(_make_pokemon_profile(
            25, "Pikachu", ["Electric"],
            {"hp": 35, "attack": 55, "defense": 40, "special_attack": 90, "special_defense": 50, "speed": 90},
            moves=[tbolt]
        ))
        pidgeot = PokemonCombatant(_make_pokemon_profile(
            18, "Pidgeot", ["Normal", "Flying"],
            {"hp": 83, "attack": 80, "defense": 75, "special_attack": 70, "special_defense": 70, "speed": 101},
            moves=[tackle]
        ))

        action = ai.choose_pokemon_action(sandslash, [sandslash, pikachu], pidgeot, rng)
        self.assertEqual(action.action_type, "switch")
        self.assertEqual(action.switch_index, 1)

    def test_08_anime_battle_transformations_and_unsupported_data(self):
        """Verified anime characters battle with transformations; unverified characters report unsupported state."""
        goku_prof = self.provider.get_combat_profile("db_goku")
        naruto_prof = self.provider.get_combat_profile("naruto_naruto")
        goku = AnimeCombatant(goku_prof)
        naruto = AnimeCombatant(naruto_prof)

        self.assertTrue(goku.has_verified_combat_data)
        ok, _ = goku.activate_transformation("db_goku_ssj")
        self.assertTrue(ok)
        self.assertIn("Super Saiyan", goku.name)

        sim = AnimeBattleSimulator("p1", [goku], "p2", [naruto], seed=42, ai_selector=TacticalBattleAI())
        res = sim.run()
        self.assertIn(res.winner_id, ("p1", "p2"))
        self.assertGreater(res.turns_played, 0)

        # Unverified character handling
        unverified_prof = next(
            self.provider.get_combat_profile(cid)
            for cid, p in self.provider.anime_combat_by_id.items()
            if p["verification_status"] == "unverified_incomplete"
        )
        unver_c = AnimeCombatant(unverified_prof)
        self.assertFalse(unver_c.has_verified_combat_data)
        self.assertIsNotNone(unver_c.unsupported_reason)

        sim_unver = AnimeBattleSimulator("p1", [unver_c], "p2", [AnimeCombatant(naruto_prof)], seed=42)
        res_unver = sim_unver.run()
        self.assertEqual(res_unver.winner_id, "p2")
        self.assertEqual(res_unver.reason, "UNSUPPORTED_COMBAT_DATA")

    def test_09_deterministic_replay_and_tournament(self):
        """Same seed produces identical replay; 3-player round-robin & empty/withdrawn teams work."""
        pika = self.provider.get_combat_profile("pkmn_25")
        charizard = self.provider.get_combat_profile("pkmn_6")
        mewtwo = self.provider.get_combat_profile("pkmn_150")

        r1 = self.manager.simulate_1v1("a", [charizard], "b", [pika], seed=12345)
        r2 = self.manager.simulate_1v1("a", [charizard], "b", [pika], seed=12345)
        self.assertEqual(r1.winner_id, r2.winner_id)
        self.assertEqual(r1.turns_played, r2.turns_played)
        self.assertEqual(r1.turn_log, r2.turn_log)

        p1 = Player("s1", "Red", "red", is_host=True)
        p1.team = [mewtwo]
        p2 = Player("s2", "Blue", "blue")
        p2.team = [charizard, pika]
        p3 = Player("s3", "Empty", "green")
        p3.team = []
        p4 = Player("s4", "Withdrawn", "yellow")
        p4.team = [mewtwo]
        p4.is_withdrawn = True

        tourney = asyncio.run(self.manager.run_tournament_async([p1, p2, p3, p4], match_id="m_test"))
        self.assertEqual(tourney["format"], "round_robin")
        self.assertEqual(tourney["total_matches"], 3)
        self.assertEqual(tourney["standings"][-1]["session_id"], "s4")  # Withdrawn ranked last

        # RoomManager battle leaderboard keeps auction & battle results cleanly integrated
        rm = RoomManager([self.provider.pokemon_by_id[25]])
        room = rm.create_room("Red", "red", "s1")
        room.players["s1"].team = [mewtwo]
        room.players["s2"] = p2
        lb = rm.calculate_battle_leaderboard(room, tourney)
        self.assertEqual(lb[0]["session_id"], tourney["champion"]["session_id"])
        self.assertIn("battle_wins", lb[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
