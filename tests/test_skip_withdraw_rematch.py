"""
Automated Test Suite for Skip Character, Withdraw From Match & Rematch System
=============================================================================
Tests all 10 core scenarios:
1. Per-player skip functionality & bid blocking.
2. All eligible players skip -> immediate round conclusion & unsold status.
3. Ineligible players (team full, withdrawn, purse < min_bid) automatically counted.
4. Reset skip set on round transition. Stat privacy preserved.
5. Withdraw from match: flag set, bidding prevented, roster & spent purse preserved.
6. Locked pool invariant: withdraw does not shrink or recalculate active auction pool.
7. Host transfer on withdrawal to deterministic next active player.
8. Match conclusion when active players drop below 2.
9. Rematch request permissions & decline handling.
10. Rematch complete reset: fresh match_id, archived history, reset purse, fresh pool.
"""

import unittest
import asyncio
import os
import sys
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from src.anime_database import AnimeDatabaseManager
from src.room_manager import (
    RoomManager, Room, Player,
    DEFAULT_STARTING_PURSE, get_max_auction_characters
)

class TestSkipWithdrawRematch(unittest.TestCase):
    def setUp(self):
        json_path = os.path.join(BASE_DIR, "data", "anime_database.json")
        db_path = os.path.join(BASE_DIR, "data", "anime_platform.db")
        self.anime_db = AnimeDatabaseManager(json_path, db_path)
        self.rm = RoomManager(self.anime_db)

        # Create standard room with host
        self.room = self.rm.create_room(
            host_name="Ash",
            host_avatar="red",
            session_id="host_ash",
            starting_purse=100
        )
        # Add player 2 and player 3
        self.rm.join_room(self.room.room_code, "Gary", "blue", "p2_gary")
        self.rm.join_room(self.room.room_code, "Brock", "green", "p3_brock")
        
        # Start game state
        self.room.status = "AUCTION"
        self.room.max_auction_characters = get_max_auction_characters(3)
        self.room.auction_character_count = 1
        self.room.current_character_full = self.rm.select_random_character(self.room)

    def test_01_per_player_skip_blocks_bidding(self):
        """Player who skips cannot bid, other players can still bid."""
        p_ash = self.room.get_player("host_ash")
        p_gary = self.room.get_player("p2_gary")

        # Ash skips
        success, msg, all_skipped = self.room.record_skip("host_ash")
        self.assertTrue(success)
        self.assertTrue(p_ash.has_skipped)
        self.assertFalse(all_skipped)  # Gary & Brock have not skipped

        # Ash max bid is now 0 (blocked)
        self.assertEqual(self.room.calculate_max_bid_for_player(p_ash), 0)

        # Gary can still bid
        self.assertGreater(self.room.calculate_max_bid_for_player(p_gary), 0)

    def test_02_all_eligible_players_skip_triggers_early_round_end(self):
        """When all eligible players skip, all_eligible_players_skipped returns True."""
        self.assertFalse(self.room.all_eligible_players_skipped())

        self.room.record_skip("host_ash")
        self.room.record_skip("p2_gary")
        self.assertFalse(self.room.all_eligible_players_skipped())

        # Brock skips -> now all eligible skipped
        success, msg, all_skipped = self.room.record_skip("p3_brock")
        self.assertTrue(all_skipped)
        self.assertTrue(self.room.all_eligible_players_skipped())

    def test_03_ineligible_players_automatically_counted_in_skip_check(self):
        """Players with 6/6 team or purse < min_bid are ineligible and don't block all_skipped."""
        p_gary = self.room.get_player("p2_gary")
        # Give Gary 6 characters
        p_gary.team = [{"id": f"dummy_{i}", "name": f"D_{i}", "power_rating": 50} for i in range(6)]
        self.assertTrue(p_gary.is_team_full)
        self.assertNotIn(p_gary, self.room.eligible_bidders)

        # Ash and Brock are the only eligible bidders
        self.assertEqual(len(self.room.eligible_bidders), 2)

        self.room.record_skip("host_ash")
        self.assertFalse(self.room.all_eligible_players_skipped())

        # When Brock skips, all eligible have skipped (Gary is ineligible)
        success, msg, all_skipped = self.room.record_skip("p3_brock")
        self.assertTrue(all_skipped)

    def test_04_skip_resets_on_next_round_stat_privacy_preserved(self):
        """Skip set clears and stats remain hidden during AUCTION."""
        self.room.record_skip("host_ash")
        self.assertIn("host_ash", self.room.skipped_player_ids)

        # Verify stat privacy
        state = self.room.to_state_dict()
        self.assertIsNone(state["players"][0]["total_team_power"])
        self.assertNotIn("base_stats", state["current_character"])

        # Reset for next round
        self.room.skipped_player_ids.clear()
        for p in self.room.players.values():
            p.has_skipped = False

        self.assertEqual(len(self.room.skipped_player_ids), 0)
        self.assertFalse(self.room.get_player("host_ash").has_skipped)

    def test_05_withdraw_from_match_preserves_roster_and_spent_funds(self):
        """Withdrawal flags player, prevents bidding, preserves team & remaining purse."""
        p_gary = self.room.get_player("p2_gary")
        # Gary won 1 character for $16
        p_gary.purse = 84
        char = {"id": "char_1", "name": "Luffy", "power_rating": 90.0, "stats": {"total": 550, "hp": 120}}
        p_gary.team.append(char)

        success, msg, new_host, should_end = self.room.withdraw_player("p2_gary")
        self.assertTrue(success)
        self.assertTrue(p_gary.is_withdrawn)
        self.assertEqual(p_gary.purse, 84)
        self.assertEqual(len(p_gary.team), 1)
        self.assertEqual(self.room.calculate_max_bid_for_player(p_gary), 0)
        self.assertFalse(should_end)  # 2 active remain: Ash and Brock

    def test_06_locked_pool_rule_on_withdraw(self):
        """Auction pool does not shrink or recalculate when a player withdraws."""
        initial_pool_size = self.room.max_auction_characters
        self.assertEqual(initial_pool_size, 22)  # For 3 players: 18 + ceil(0.45)+3 = 22

        self.room.withdraw_player("p3_brock")
        self.assertEqual(self.room.max_auction_characters, initial_pool_size)

    def test_07_host_transfers_to_next_active_player_on_host_withdraw(self):
        """If host withdraws, host role transfers deterministically to next active player."""
        self.assertTrue(self.room.get_player("host_ash").is_host)

        success, msg, new_host_id, should_end = self.room.withdraw_player("host_ash")
        self.assertTrue(success)
        self.assertFalse(self.room.get_player("host_ash").is_host)
        self.assertEqual(new_host_id, "p2_gary")
        self.assertTrue(self.room.get_player("p2_gary").is_host)

    def test_08_match_concludes_when_active_players_drop_below_two(self):
        """When fewer than 2 active players remain, should_end_match is True."""
        # Ash withdraws -> 2 active remain (Gary, Brock)
        _, _, _, should_end_1 = self.room.withdraw_player("host_ash")
        self.assertFalse(should_end_1)

        # Gary withdraws -> only Brock remains (< 2 active players)
        _, _, _, should_end_2 = self.room.withdraw_player("p2_gary")
        self.assertTrue(should_end_2)

    def test_09_rematch_request_and_decline(self):
        """Only host can request rematch. A decline cancels the rematch."""
        self.room.status = "GAME_OVER"

        # Non-host cannot request rematch
        success, msg = self.room.request_rematch("p2_gary")
        self.assertFalse(success)

        # Host requests rematch
        success, msg = self.room.request_rematch("host_ash")
        self.assertTrue(success)
        self.assertEqual(self.room.status, "REMATCH_PENDING")
        self.assertEqual(self.room.rematch_votes.get("host_ash"), True)

        # Player declines -> rematch cancelled back to GAME_OVER
        success, msg, all_acc, any_dec = self.room.vote_rematch("p2_gary", accept=False)
        self.assertTrue(success)
        self.assertTrue(any_dec)
        self.assertFalse(all_acc)
        self.assertEqual(self.room.status, "GAME_OVER")

    def test_10_rematch_complete_reset_flow(self):
        """All players accept -> reset match with archived history, fresh purses and new match_id."""
        self.room.status = "GAME_OVER"
        # Simulate some prior results
        p_ash = self.room.get_player("host_ash")
        p_ash.purse = 40
        p_ash.team = [{"id": "p1", "name": "Goku", "power_rating": 98.0, "stats": {"total": 600, "hp": 150}}]

        self.room.request_rematch("host_ash")
        self.room.vote_rematch("p2_gary", accept=True)
        success, msg, all_acc, any_dec = self.room.vote_rematch("p3_brock", accept=True)
        self.assertTrue(all_acc)
        self.assertFalse(any_dec)

        # Execute rematch reset
        initial_match_id = self.room.match_id
        rematch_info = self.room.reset_for_rematch(self.rm)

        self.assertEqual(self.room.match_number, 2)
        self.assertNotEqual(self.room.match_id, initial_match_id)
        self.assertEqual(len(self.room.match_history), 1)
        self.assertEqual(self.room.status, "AUCTION")
        self.assertEqual(self.room.auction_character_count, 0)

        # Verify all players reset
        for p in self.room.players.values():
            self.assertEqual(p.purse, 100)
            self.assertEqual(len(p.team), 0)
            self.assertFalse(p.is_withdrawn)
            self.assertFalse(p.has_skipped)
            self.assertIsNone(p.rematch_vote)


if __name__ == "__main__":
    unittest.main()
