"""
Marvel Combat Data & Engine Tests (Phase 6)
===========================================
Covers:
- Marvel character data import (offline fallback, pagination, duplicate detection, missing/failed API)
- Earth-616 Comics vs MCU incarnation separation
- Verified vs incomplete/civilian character handling
- Marvel vs Marvel native battle (shields, regeneration, transformations)
- Marvel vs Pokémon cross-universe battle
- Marvel vs Anime cross-universe battle
- Manual PvP LiveBattleSession with Marvel combatants
"""

import asyncio
import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.battle_ai import TacticalBattleAI
from src.battle_manager import BattleManager
from src.combat_data import CombatDataProvider
from src.live_battle_session import LiveBattleSession
from src.marvel_battle_engine import MarvelBattleSimulator, MarvelCombatant
from src.marvel_combat_importer import MarvelCharacterImporter


class TestMarvelCombatAndImporter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provider = CombatDataProvider()
        cls.manager = BattleManager(cls.provider)

    def test_01_importer_missing_credentials_and_api_failure(self):
        """Missing API credentials fall back cleanly; API failure does not crash."""
        imp_no_keys = MarvelCharacterImporter(public_key="", private_key="")
        self.assertFalse(imp_no_keys.has_api_credentials)
        self.assertIsNone(imp_no_keys.fetch_api_page())

        imp_with_keys = MarvelCharacterImporter(public_key="pub", private_key="priv")
        self.assertTrue(imp_with_keys.has_api_credentials)
        with patch("urllib.request.urlopen", side_effect=OSError("Network unreachable")):
            res = imp_with_keys.fetch_api_page(offset=0, retries=1)
            self.assertIsNone(res)
            self.assertGreater(len(imp_with_keys.errors), 0)

    def test_02_pagination_and_duplicate_detection(self):
        """Mocked paginated API responses deduplicate against existing characters."""
        imp = MarvelCharacterImporter(public_key="pub", private_key="priv")
        page1 = {"data": {"results": [
            {"id": 1009610, "name": "Spider-Man (Earth-616)", "description": "Dup", "thumbnail": {}},
            {"id": 999001, "name": "Silver Surfer", "description": "Herald", "thumbnail": {"path": "http://i.annihil.us/u/prod/marvel/i/mg/b/40/image", "extension": "jpg"}},
        ]}}
        page2 = {"data": {"results": []}}
        with patch.object(imp, "fetch_api_page", side_effect=[page1, page2]):
            meta = imp.import_characters(max_pages=2, use_cache=False)
            self.assertGreaterEqual(meta["total_characters"], 28)
            self.assertEqual(meta["api_fetched"], 1)  # Silver Surfer added, duplicate skipped
        # Restore clean offline seed file
        MarvelCharacterImporter(public_key="", private_key="").import_characters()

    def test_03_incarnation_separation_and_unverified_exclusion(self):
        """Comics and MCU incarnations stay separate; unverified civilians are excluded from battle."""
        im_616 = self.provider.get_combat_profile("marvel_616_iron_man")
        im_mcu = self.provider.get_combat_profile("marvel_mcu_iron_man")
        self.assertIsNotNone(im_616)
        self.assertIsNotNone(im_mcu)
        self.assertNotEqual(im_616["incarnation"], im_mcu["incarnation"])

        aunt_may = self.provider.get_combat_profile("marvel_616_aunt_may")
        self.assertIsNotNone(aunt_may)
        self.assertFalse(aunt_may["combat_eligible"])
        may_comb = MarvelCombatant(aunt_may)
        self.assertFalse(may_comb.has_verified_combat_data)
        self.assertIsNotNone(may_comb.unsupported_reason)

        thor_comb = MarvelCombatant(self.provider.get_combat_profile("marvel_616_thor"))
        sim = MarvelBattleSimulator("may", [may_comb], "thor", [thor_comb], seed=42)
        res = sim.run()
        self.assertEqual(res.winner_id, "thor")
        self.assertEqual(res.reason, "UNSUPPORTED_COMBAT_DATA")

    def test_04_marvel_vs_marvel_native_battle_and_transformation(self):
        """Marvel vs Marvel uses native MarvelBattleSimulator with shields, healing, and transformations."""
        thor = MarvelCombatant(self.provider.get_combat_profile("marvel_616_thor"))
        hulk = MarvelCombatant(self.provider.get_combat_profile("marvel_616_hulk"))
        ok, _ = hulk.activate_transformation("tf_hulk_worldbreaker")
        self.assertTrue(ok)
        self.assertIn("World Breaker", hulk.name)

        sim = MarvelBattleSimulator("a", [thor], "b", [hulk], seed=77, ai_selector=TacticalBattleAI())
        res = sim.run()
        self.assertIn(res.winner_id, ("a", "b"))
        self.assertGreater(res.turns_played, 0)

    def test_05_marvel_vs_pokemon_and_marvel_vs_anime(self):
        """Marvel vs Pokémon and Marvel vs Anime run cleanly via CrossUniverseBattleSimulator."""
        spidey = self.provider.get_combat_profile("marvel_616_spider_man")
        pika = self.provider.get_combat_profile("pkmn_25")
        goku = self.provider.get_combat_profile("db_goku")

        res_pm = self.manager.simulate_1v1("marvel_p", [spidey], "pkmn_p", [pika], seed=101)
        self.assertIn(res_pm.winner_id, ("marvel_p", "pkmn_p"))
        self.assertGreater(res_pm.turns_played, 0)

        res_am = self.manager.simulate_1v1("marvel_p", [self.provider.get_combat_profile("marvel_616_thanos")], "anime_p", [goku], seed=102)
        self.assertIn(res_am.winner_id, ("marvel_p", "anime_p"))
        self.assertGreater(res_am.turns_played, 0)

    def test_06_manual_pvp_live_battle_with_marvel(self):
        """LiveBattleSession supports manual PvP action submission for Marvel combatants."""
        cap = MarvelCombatant(self.provider.get_combat_profile("marvel_616_captain_america"))
        doom = MarvelCombatant(self.provider.get_combat_profile("marvel_616_doctor_doom"))
        sess = LiveBattleSession("p1", [cap], "p2", [doom], control_mode="player_vs_player", turn_timeout_seconds=0.1, match_id="m_marvel_1")
        prompt = sess.build_player_prompt("p1")
        self.assertGreater(len(prompt["available_moves"]), 0)
        ok, _ = sess.submit_action("p1", {"action_type": "attack", "move_id": prompt["available_moves"][0]["id"], "match_id": "m_marvel_1"})
        self.assertTrue(ok)
        res = asyncio.run(sess.run_interactive(max_turns=25))
        self.assertIn(res.winner_id, ("p1", "p2"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
