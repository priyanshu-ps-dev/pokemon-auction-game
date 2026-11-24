"""
Phase 1 Validation Tests: Unified Pokémon & Anime Combat Data Enrichment
========================================================================
Verifies data integrity, referential consistency, <=4-move rules,
duplicate prevention, source/verification metadata, missing-data handling,
and the shared CombatDataProvider interface.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.combat_data import CombatDataProvider

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")


class TestPhase1CombatData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provider = CombatDataProvider(DATA_DIR)
        with open(os.path.join(DATA_DIR, "pokemon_database.json"), "r", encoding="utf-8") as f:
            cls.pokemon_db = json.load(f)
        with open(os.path.join(DATA_DIR, "anime_database.json"), "r", encoding="utf-8") as f:
            cls.anime_db = json.load(f)

    def test_01_existing_databases_intact(self):
        """Existing Pokémon (1,351) and Anime (3,467) databases remain intact."""
        self.assertEqual(len(self.pokemon_db), 1351)
        self.assertEqual(len(self.anime_db.get("characters", [])), 3467)

    def test_02_pokemon_learnsets_and_moves_valid(self):
        """Every Pokémon has a learnset entry, valid move IDs, and <= 4 default moves."""
        self.assertEqual(len(self.provider.pokemon_learnsets), 1351)
        self.assertGreaterEqual(len(self.provider.moves_by_id), 900)
        self.assertGreaterEqual(len(self.provider.pokemon_abilities_by_id), 300)

        for p in self.pokemon_db:
            pid = p["id"]
            self.assertIn(pid, self.provider.pokemon_learnsets)
            ls = self.provider.pokemon_learnsets[pid]
            learnable = set(ls["learnable_move_ids"])
            default_moves = ls["default_moveset"]

            self.assertLessEqual(len(default_moves), 4, f"Pokémon {pid} has >4 default moves")
            self.assertEqual(len(default_moves), len(set(default_moves)), f"Duplicate move in {pid}")
            for mid in default_moves:
                self.assertIn(mid, learnable, f"Default move {mid} not in learnable set for {pid}")
                self.assertIn(mid, self.provider.moves_by_id, f"Move {mid} missing from moves_database.json")

    def test_03_pokemon_alternate_forms_supported(self):
        """Alternate Pokémon forms (e.g. Mega/Alolan/Galarian) resolve via CombatDataProvider."""
        non_default = [p for p in self.pokemon_db if not p.get("is_default", True)]
        self.assertEqual(len(non_default), 326)
        sample_form = non_default[0]
        profile = self.provider.get_combat_profile(sample_form["id"])
        self.assertIsNotNone(profile)
        self.assertEqual(profile["system"], "pokemon")
        self.assertFalse(profile["is_default"])
        self.assertGreater(len(profile["default_moveset"]), 0)
        self.assertLessEqual(len(profile["default_moveset"]), 4)

    def test_04_anime_character_ids_and_links_valid(self):
        """All 2,116 non-Pokémon anime characters are indexed with valid IDs."""
        non_pkmn = {
            str(c["id"]): c
            for c in self.anime_db.get("characters", [])
            if c.get("anime_id") != "pokemon"
        }
        self.assertEqual(len(self.provider.anime_combat_by_id), len(non_pkmn))

        for cid, profile in self.provider.anime_combat_by_id.items():
            self.assertIn(cid, non_pkmn)
            self.assertEqual(profile["anime_id"], non_pkmn[cid]["anime_id"])
            for aid in profile["attack_ids"]:
                self.assertIn(aid, self.provider.anime_attacks_by_id)
                self.assertEqual(self.provider.anime_attacks_by_id[aid]["character_id"], cid)
            for abid in profile["ability_ids"]:
                self.assertIn(abid, self.provider.anime_abilities_by_id)
                self.assertEqual(self.provider.anime_abilities_by_id[abid]["character_id"], cid)
            for tfid in profile["transformation_ids"]:
                self.assertIn(tfid, self.provider.anime_transformations_by_id)
                self.assertEqual(self.provider.anime_transformations_by_id[tfid]["character_id"], cid)

    def test_05_no_placeholder_techniques_and_no_duplicates(self):
        """Placeholder Pokémon techniques are excluded and per-character attacks/abilities are unique."""
        for atk in self.provider.anime_attacks_by_id.values():
            self.assertFalse(atk["name"].endswith("Elemental Technique"))
            self.assertIn("source", atk)
            self.assertIn("verification_status", atk)
            self.assertIn("canon_status", atk)

        for cid in self.provider.anime_combat_by_id:
            atks = [a["name"].lower() for a in self.provider.get_anime_attacks(cid)]
            self.assertEqual(len(atks), len(set(atks)), f"Duplicate attack for {cid}")
            abs_ = [a["name"].lower() for a in self.provider.get_anime_abilities(cid)]
            self.assertEqual(len(abs_), len(set(abs_)), f"Duplicate ability for {cid}")

    def test_06_unverified_and_missing_data_preserved(self):
        """Unverified anime characters are clearly marked and missing fields remain None/empty."""
        unverified = [
            p for p in self.provider.anime_combat_by_id.values()
            if p["verification_status"] != "verified_curated"
        ]
        self.assertGreater(len(unverified), 2000)
        sample = unverified[0]
        self.assertEqual(sample["canon_status"], "unverified")
        self.assertIsNone(sample["weaknesses"])
        self.assertIsNone(sample["resistances"])
        self.assertIsNone(sample["immunities"])

    def test_07_shared_combat_data_provider_interface(self):
        """CombatDataProvider retrieves distinct Pokémon and Anime profiles cleanly."""
        pk_profile = self.provider.get_combat_profile("pkmn_25")
        self.assertIsNotNone(pk_profile)
        self.assertEqual(pk_profile["system"], "pokemon")
        self.assertEqual(pk_profile["name"], "Pikachu")
        self.assertGreater(len(pk_profile["default_moveset"]), 0)
        self.assertIn("power", pk_profile["default_moveset"][0])

        goku_profile = self.provider.get_combat_profile("db_goku")
        self.assertIsNotNone(goku_profile)
        self.assertEqual(goku_profile["system"], "anime")
        self.assertEqual(goku_profile["verification_status"], "verified_curated")
        self.assertGreater(len(goku_profile["attacks"]), 0)
        self.assertGreater(len(goku_profile["transformations"]), 0)

        self.assertIsNone(self.provider.get_combat_profile("nonexistent_id_xyz"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
