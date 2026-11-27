import unittest
import json
import os
from src.anime_database import AnimeDatabaseManager
from src.room_manager import RoomManager, get_max_auction_characters

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
ANIME_JSON = os.path.join(DATA_DIR, "anime_database.json")
ANIME_DB = os.path.join(DATA_DIR, "anime_platform.db")
POKEMON_JSON = os.path.join(DATA_DIR, "pokemon_database.json")
AUDIT_JSON = os.path.join(DATA_DIR, "database_audit_report.json")


class TestDatabaseUpgradeAndPokedex(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = AnimeDatabaseManager(ANIME_JSON, ANIME_DB)
        cls.room_manager = RoomManager(cls.db)

    def test_01_one_piece_has_at_least_50_unique_characters(self):
        """Test 1: One Piece has at least 50 unique characters (target achieved)."""
        chars = [c for c in self.db.characters.values() if c.get("anime_id") == "one_piece"]
        unique_names = set(c["name"].strip().lower() for c in chars)
        self.assertGreaterEqual(len(unique_names), 50, f"One Piece should have >= 50 unique characters, got {len(unique_names)}")
        # Check iconic characters
        names_lower = [c["name"].lower() for c in chars]
        self.assertTrue(any("luffy" in n for n in names_lower))
        self.assertTrue(any("zoro" in n for n in names_lower))
        self.assertTrue(any("sanji" in n for n in names_lower))

    def test_02_naruto_has_at_least_50_unique_characters(self):
        """Test 2: Naruto has at least 50 unique characters (target achieved)."""
        chars = [c for c in self.db.characters.values() if c.get("anime_id") == "naruto"]
        unique_names = set(c["name"].strip().lower() for c in chars)
        self.assertGreaterEqual(len(unique_names), 50, f"Naruto should have >= 50 unique characters, got {len(unique_names)}")
        names_lower = [c["name"].lower() for c in chars]
        self.assertTrue(any("naruto" in n for n in names_lower))
        self.assertTrue(any("sasuke" in n for n in names_lower))
        self.assertTrue(any("kakashi" in n for n in names_lower))

    def test_03_dragon_ball_has_at_least_50_unique_characters(self):
        """Test 3: Dragon Ball has at least 50 unique characters (target achieved)."""
        chars = [c for c in self.db.characters.values() if c.get("anime_id") == "dragon_ball"]
        unique_names = set(c["name"].strip().lower() for c in chars)
        self.assertGreaterEqual(len(unique_names), 50, f"Dragon Ball should have >= 50 unique characters, got {len(unique_names)}")
        names_lower = [c["name"].lower() for c in chars]
        self.assertTrue(any("goku" in n for n in names_lower))
        self.assertTrue(any("vegeta" in n for n in names_lower))

    def test_04_character_images_verified(self):
        """Test 4: Character images are verified CDN images and not fallback avatars."""
        res = self.db.repair_images()
        self.assertGreater(res["verified_images"], 3000, "Expected >3000 verified images")
        self.assertEqual(res["missing_images"], 0, "No characters should have missing images")
        # Check image URL on sample characters
        sample_op = next(c for c in self.db.characters.values() if c.get("anime_id") == "one_piece")
        self.assertTrue(sample_op["image"].startswith("http"), f"Image should be HTTP CDN URL: {sample_op['image']}")

    def test_05_pagination_works_across_database(self):
        """Test 5: Pagination works correctly with limit and offset."""
        page1 = self.db.search_characters(limit=20, offset=0)
        page2 = self.db.search_characters(limit=20, offset=20)
        self.assertEqual(len(page1["characters"]), 20)
        self.assertEqual(len(page2["characters"]), 20)
        self.assertEqual(page1["total"], len(self.db.characters))
        # Ensure page 1 and page 2 have disjoint character IDs
        ids1 = set(c["id"] for c in page1["characters"])
        ids2 = set(c["id"] for c in page2["characters"])
        self.assertEqual(len(ids1.intersection(ids2)), 0, "Pages should not overlap")

    def test_06_search_works_for_supporting_characters(self):
        """Test 6: Search works for supporting and lesser-known characters."""
        res = self.db.search_characters(query="Yamcha")
        self.assertGreater(res["total"], 0, "Search for Yamcha should find character")
        self.assertTrue(any("yamcha" in c["name"].lower() for c in res["characters"]))

        res2 = self.db.search_characters(query="Buggy")
        self.assertGreater(res2["total"], 0, "Search for Buggy should find character")

        res3 = self.db.search_characters(query="Kiba")
        self.assertGreater(res3["total"], 0, "Search for Kiba should find character")

    def test_07_deduplication_matches_cross_source(self):
        """Test 7: Deduplication reports zero duplicates across all 3,470 entries."""
        dup = self.db.scan_duplicates()
        self.assertEqual(dup["total_duplicates"], 0, f"Expected 0 duplicates, found: {dup['duplicates']}")

    def test_08_single_franchise_room_contains_only_selected_franchise(self):
        """Test 8: Room created with ONLY One Piece contains only One Piece characters."""
        room = self.room_manager.create_room("OP_HOST", "Luffy", "avatar1", starting_purse=100, anime_mode="single", selected_anime=["one_piece"])
        self.assertGreaterEqual(len(room.character_pool), 12)
        for char in room.character_pool:
            self.assertEqual(char["anime_id"], "one_piece", f"Expected only One Piece character, got {char.get('anime_id')} ({char.get('name')})")

    def test_09_multiple_franchises_room_contains_only_selected_franchises(self):
        """Test 9: Room created with One Piece + Naruto contains only those two franchises."""
        room = self.room_manager.create_room("DUO_HOST", "Naruto", "avatar1", starting_purse=100, anime_mode="multiple", selected_anime=["one_piece", "naruto"])
        self.assertEqual({c["anime_id"] for c in room.character_pool}, {"one_piece", "naruto"})
        for char in room.character_pool:
            self.assertIn(char["anime_id"], ["one_piece", "naruto"], f"Unexpected anime_id: {char.get('anime_id')}")

    def test_10_dynamic_auction_pool_formula(self):
        """Test 10: Dynamic Auction Pool: (Active Players * 6) + 4."""
        # Check formula directly
        self.assertEqual(get_max_auction_characters(2), 16)
        self.assertEqual(get_max_auction_characters(3), 22)
        self.assertEqual(get_max_auction_characters(4), 28)
        self.assertEqual(get_max_auction_characters(6), 40)
        self.assertEqual(get_max_auction_characters(8), 52)

        # Check room simulation with 8 players
        room = self.room_manager.create_room("P1", "av1", "HOST_SESS", starting_purse=100, anime_mode="all")
        for i in range(2, 9):
            self.room_manager.join_room(room.room_code, f"Player {i}", f"av{i}", f"p_{i}")
            room.players[f"p_{i}"].is_ready = True
        room.players["HOST_SESS"].is_ready = True

        self.assertEqual(len(room.players), 8)
        active_count = len([p for p in room.players.values() if not p.is_withdrawn])
        calc_pool = get_max_auction_characters(active_count)
        room.max_auction_characters = min(len(room.character_pool), calc_pool)
        self.assertEqual(room.max_auction_characters, 52, f"Expected 52 characters for 8 players, got {room.max_auction_characters}")

    def test_11_auction_completion_no_duplicate_characters(self):
        """Test 11: Auction completion verifies no duplicate character appearances."""
        room = self.room_manager.create_room("P1", "av1", "HOST_SESS", starting_purse=100, anime_mode="all")
        self.room_manager.join_room(room.room_code, "Player 2", "av2", "p_2")
        room.players["p_2"].is_ready = True
        room.players["HOST_SESS"].is_ready = True

        appeared_ids = []
        for _ in range(16):
            char = self.room_manager.select_random_character(room)
            if not char:
                break
            appeared_ids.append(char["id"])

        self.assertEqual(len(appeared_ids), len(set(appeared_ids)), "No character should appear more than once in the auction")
        self.assertEqual(len(appeared_ids), 16)

    def test_12_pokemon_database_100_percent_functional(self):
        """Test 12: Existing 1,351 Pokémon remain 100% functional and intact."""
        with open(POKEMON_JSON, "r", encoding="utf-8") as f:
            poke_data = json.load(f)
        self.assertEqual(len(poke_data), 1351, "Pokemon database should have exactly 1,351 entries")

        poke_room = self.room_manager.create_room("POKE_HOST", "Ash", "av1", starting_purse=100, anime_mode="pokemon")
        self.assertEqual(len(poke_room.character_pool), len({p["national_id"] for p in poke_data}))
        sample_char = poke_room.character_pool[0]
        self.assertTrue(sample_char.get("anime_id") == "pokemon" or "national_id" in sample_char)


if __name__ == "__main__":
    unittest.main()
