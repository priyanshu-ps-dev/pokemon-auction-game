"""
Phase 5 Tests: Intelligent Movesets, Cross-Universe Balance, Live PvP,
Championship Brackets, Persistent Player Profiles & Anime Expansion
=====================================================================
"""

import asyncio
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.battle_balance import run_matchup_series
from src.battle_engine import PokemonCombatant
from src.battle_manager import BattleManager
from src.combat_data import CombatDataProvider
from src.live_battle_session import LiveBattleSession
from src.player_profiles import PlayerProfileStore
from src.room_manager import Player

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestPhase5Competitive(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provider = CombatDataProvider()
        cls.manager = BattleManager(cls.provider)

    def test_01_intelligent_pokemon_movesets_avoid_self_ko_and_align_stats(self):
        """Gengar, Snorlax, and Charizard no longer pick Explosion/Self-Destruct/Hyper Beam by default."""
        for pid in ("pkmn_94", "pkmn_143", "pkmn_6"):
            prof = self.provider.get_combat_profile(pid)
            move_idents = {m["identifier"] for m in prof["default_moveset"]}
            self.assertLessEqual(len(prof["default_moveset"]), 4)
            self.assertNotIn("explosion", move_idents)
            self.assertNotIn("self-destruct", move_idents)
            self.assertNotIn("hyper-beam", move_idents)
            self.assertNotIn("focus-punch", move_idents)

    def test_02_cross_universe_balance_improved(self):
        """Charizard vs Luffy cross-universe battle is competitive across multiple turns."""
        tel = run_matchup_series(self.manager, "Charizard_vs_Luffy", ["pkmn_6"], ["anilist_40"], seeds=list(range(200, 210)))
        self.assertGreaterEqual(tel["avg_turns"], 3.0)
        self.assertGreater(len(tel["top_moves"]), 0)

    def test_03_live_battle_session_pvp_validation_and_timeout(self):
        """LiveBattleSession validates moves, rejects duplicates, hides opponent moves, and falls back on timeout."""
        pika = PokemonCombatant(self.provider.get_combat_profile("pkmn_25"))
        charizard = PokemonCombatant(self.provider.get_combat_profile("pkmn_6"))
        bulba = PokemonCombatant(self.provider.get_combat_profile("pkmn_1"))

        sess = LiveBattleSession("p1", [pika, bulba], "p2", [charizard], control_mode="player_vs_player", turn_timeout_seconds=0.1)
        prompt_a = sess.build_player_prompt("p1")
        self.assertFalse(prompt_a["opponent_submitted"])
        self.assertGreater(len(prompt_a["available_moves"]), 0)
        self.assertEqual(len(prompt_a["available_switches"]), 1)

        # Illegal move rejected
        ok_bad, _ = sess.submit_action("p1", {"action_type": "attack", "move_id": 999999})
        self.assertFalse(ok_bad)

        # Valid move accepted; duplicate rejected
        valid_mid = prompt_a["available_moves"][0]["id"]
        ok1, _ = sess.submit_action("p1", {"action_type": "attack", "move_id": valid_mid})
        self.assertTrue(ok1)
        ok_dup, _ = sess.submit_action("p1", {"action_type": "attack", "move_id": valid_mid})
        self.assertFalse(ok_dup)

        # Prompt for p2 shows opponent_submitted=True without leaking p1's move_id
        prompt_b = sess.build_player_prompt("p2")
        self.assertTrue(prompt_b["opponent_submitted"])
        self.assertNotIn("pending_actions", prompt_b)

        # Run interactive loop -> p2 times out cleanly and falls back to AI
        res = asyncio.run(sess.run_interactive(max_turns=30))
        self.assertIn(res.winner_id, ("p1", "p2"))
        self.assertGreater(res.turns_played, 0)

    def test_04_championship_bracket_mode_5_players(self):
        """5-player championship bracket handles automatic bye, Semifinals, Final, and champion."""
        pk_ids = ["pkmn_6", "pkmn_25", "pkmn_150", "pkmn_94", "pkmn_130"]
        players = []
        for i, pk in enumerate(pk_ids):
            p = Player(f"b{i}", f"Challenger_{i}", "red", is_host=(i == 0))
            p.team = [self.provider.get_combat_profile(pk)]
            players.append(p)

        res = asyncio.run(self.manager.run_tournament_async(players, match_id="champ_5", tournament_format="bracket"))
        self.assertEqual(res["format"], "bracket")
        self.assertIsNotNone(res["bracket"])
        self.assertIsNotNone(res["champion"])
        self.assertEqual(res["standings"][0]["session_id"], res["champion"]["session_id"])

    def test_05_persistent_player_profiles(self):
        """PlayerProfileStore persists wins, losses, championships, win %, and history."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "profiles.db")
            store = PlayerProfileStore(db_path)
            store.record_tournament_results({
                "match_id": "m1",
                "format": "bracket",
                "champion": {"session_id": "u1"},
                "standings": [
                    {"session_id": "u1", "name": "Red", "rank": 1, "wins": 2, "losses": 0, "draws": 0},
                    {"session_id": "u2", "name": "Blue", "rank": 2, "wins": 1, "losses": 1, "draws": 0},
                ],
            })
            p1 = store.get_profile("u1")
            p2 = store.get_profile("u2")
            self.assertEqual(p1["championships"], 1)
            self.assertEqual(p1["win_percentage"], 100.0)
            self.assertEqual(p2["wins"], 1)
            self.assertEqual(p2["win_percentage"], 50.0)

    def test_06_expanded_anime_coverage_and_frontend_hooks(self):
        """Newly enriched anime characters have verified data; Phase 5 frontend hooks exist."""
        for cid in ("anilist_27", "anilist_89220", "demon_slayer_zenitsuagatsuma", "demon_slayer_nezukokamado", "jujutsu_kaisen_kentonanami", "one_piece_nami"):
            prof = self.provider.get_combat_profile(cid)
            self.assertIsNotNone(prof)
            self.assertEqual(prof["verification_status"], "verified_curated")
            self.assertGreater(len(prof["attacks"]), 0)

        with open(os.path.join(BASE_DIR, "public", "index.html"), encoding="utf-8") as f:
            html = f.read()
        with open(os.path.join(BASE_DIR, "public", "game.js"), encoding="utf-8") as f:
            js = f.read()
        for hook in ("battle-control-select", "tournament-format-select", "battle-control-panel", "battle-moves-grid"):
            self.assertIn(hook, html)
        for fn in ("renderInteractiveTurnPrompt", "submit_battle_action", "battle_turn_resolved"):
            self.assertIn(fn, js)


if __name__ == "__main__":
    unittest.main(verbosity=2)
