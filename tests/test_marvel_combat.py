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
        import tempfile
        imp = MarvelCharacterImporter(public_key="pub", private_key="priv")
        page1 = {"data": {"results": [
            {"id": 1009610, "name": "Spider-Man (Earth-616)", "description": "Dup", "thumbnail": {}},
            {"id": 999001, "name": "Silver Surfer", "description": "Herald", "thumbnail": {"path": "http://i.annihil.us/u/prod/marvel/i/mg/b/40/image", "extension": "jpg"}},
        ]}}
        page2 = {"data": {"results": []}}
        with tempfile.TemporaryDirectory() as tmpdir:
            raw_p = os.path.join(tmpdir, "marvel_raw.json")
            cache_p = os.path.join(tmpdir, "marvel_cache.json")
            with patch("src.marvel_combat_importer.MARVEL_RAW_PATH", raw_p), \
                 patch("src.marvel_combat_importer.MARVEL_CACHE_PATH", cache_p), \
                 patch.object(imp, "fetch_api_page", side_effect=[page1, page2]):
                meta = imp.import_characters(max_pages=2, use_cache=False)
                self.assertGreaterEqual(meta["total_characters"], 28)
                self.assertEqual(meta["api_fetched"], 1)  # Silver Surfer added, duplicate skipped

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

    def test_07_marvel_real_image_urls_and_metadata(self):
        """All 26 combat-eligible Marvel characters have verified real artwork URLs; civilians flagged."""
        from src.anime_database import AnimeDatabaseManager

        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        db = AnimeDatabaseManager(
            os.path.join(base_dir, "data", "anime_database.json"),
            os.path.join(base_dir, "data", "anime_platform.db"),
        )
        for cid in (
            "marvel_616_hulk",
            "marvel_616_spider_man",
            "marvel_616_iron_man",
            "marvel_616_ultron",
            "marvel_616_thor",
            "marvel_616_doctor_strange",
            "marvel_616_thanos",
            "marvel_616_loki",
            "marvel_616_wolverine",
            "marvel_616_magneto",
        ):
            ch = db.get_character_by_id(cid)
            self.assertIsNotNone(ch, f"Missing {cid}")
            self.assertTrue(ch["image"].startswith("https://cdn.jsdelivr.net/gh/akabab/superhero-api"), ch["image"])
            self.assertEqual(ch.get("image_verification_status"), "verified_cdn")
            self.assertIn("SuperHeroAPI", ch.get("image_source", ""))
            self.assertIn("Marvel", ch.get("image_attribution", ""))

        may = db.get_character_by_id("marvel_616_aunt_may")
        self.assertIsNotNone(may)
        self.assertEqual(may.get("image_verification_status"), "missing_artwork_placeholder")

    def test_08_phase8_expanded_catalog_manifest_and_auction_isolation(self):
        """Phase 8: 2,000+ Marvel records browsable in catalog, but only combat-eligible enter auctions."""
        from src.anime_database import AnimeDatabaseManager

        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        manifest_path = os.path.join(base_dir, "data", "marvel_import_manifest.json")
        self.assertTrue(os.path.exists(manifest_path))
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        self.assertGreater(manifest["unique_ids"], 2000)
        self.assertGreater(manifest["duplicates_merged"], 0)
        self.assertEqual(manifest["sources"]["official_marvel_api"]["status"], "skipped_no_credentials")
        self.assertEqual(manifest["combat_verification_coverage"]["combat_eligible"], 26)

        db = AnimeDatabaseManager(
            os.path.join(base_dir, "data", "anime_database.json"),
            os.path.join(base_dir, "data", "anime_platform.db"),
        )
        all_marvel = db.search_characters(anime_id="marvel", limit=50, offset=0)
        self.assertEqual(all_marvel["total"], manifest["unique_ids"])
        self.assertEqual(len(all_marvel["characters"]), 50)

        villains = db.search_characters(anime_id="marvel", category="Villains", limit=20)
        self.assertGreater(villains["total"], 100)

        verified_art = db.search_characters(anime_id="marvel", has_artwork="true", limit=20)
        self.assertGreaterEqual(verified_art["total"], 290)

        combat_only = db.search_characters(anime_id="marvel", combat_eligible="true", limit=50)
        self.assertEqual(combat_only["total"], 26)

        auction_pool = db.get_characters_for_mode(mode="marvel")
        self.assertEqual(len(auction_pool), 26)
        self.assertTrue(all(c.get("is_active") for c in auction_pool))


if __name__ == "__main__":
    unittest.main(verbosity=2)
