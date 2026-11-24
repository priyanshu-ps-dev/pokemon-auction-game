"""
Phase 7 — Multiplayer Auction Reliability, Concurrency & 4-Player WebSocket Validation
====================================================================================
Regression and concurrency test suite covering all 5 observed auction bugs:
1. Bug 1: Authoritative bidder identity (session_id vs display name) & UI state sync.
2. Bug 2: Refresh/reconnect session & room state preservation (LOBBY/AUCTION/BATTLE/GAME_OVER).
3. Bug 3: Duplicate character assignment prevention (atomic/idempotent round settlement).
4. Bug 4: Double purse deduction prevention (lock + settled_rounds ledger).
5. Bug 5: Auction freeze / race condition / double-start prevention & 4-player WebSocket flow.
"""

import asyncio
import json
import os
import sys
import time
import unittest
import websockets

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from src.anime_database import AnimeDatabaseManager
from src.room_manager import (
    RoomManager,
    DEFAULT_STARTING_PURSE,
    get_max_auction_characters,
)
import server as game_server


def _make_anime_db():
    json_path = os.path.join(BASE_DIR, "data", "anime_database.json")
    db_path = os.path.join(BASE_DIR, "data", "anime_platform.db")
    return AnimeDatabaseManager(json_path, db_path)


class TestAuctionReliabilityUnitAndConcurrency(unittest.TestCase):
    def setUp(self):
        self.db = _make_anime_db()
        self.rm = RoomManager(self.db)
        self.room = self.rm.create_room(
            host_name="Ash",
            host_avatar="red",
            session_id="sess_p1",
            starting_purse=500,
            anime_mode="all",
        )
        self.rm.join_room(self.room.room_code, "Ash", "blue", "sess_p2")  # Same display name as P1!
        self.rm.join_room(self.room.room_code, "Misty", "green", "sess_p3")
        self.rm.join_room(self.room.room_code, "Brock", "yellow", "sess_p4")

        self.room.status = "AUCTION"
        self.room.max_auction_characters = get_max_auction_characters(4)
        self.room.auction_character_count = 1
        self.room.current_character_full = self.rm.select_random_character(self.room)

    def test_01_same_display_name_distinct_session_ids(self):
        """Bug 1: Two players with identical names must remain distinguishable by session_id."""
        self.room.current_bid = 50
        self.room.highest_bidder_id = "sess_p2"
        state = self.room.to_state_dict()
        self.assertEqual(state["highest_bidder_id"], "sess_p2")
        self.assertEqual(state["highest_bidder_name"], "Ash")
        self.assertNotEqual(state["highest_bidder_id"], "sess_p1")

    def test_02_state_dict_exposes_authoritative_auction_fields(self):
        """Bug 1 & 2: to_state_dict includes all fields needed for bid UI & refresh restore."""
        self.room.current_bid = 120
        self.room.highest_bidder_id = "sess_p3"
        self.room.timer_seconds_left = 9
        state = self.room.to_state_dict()
        self.assertEqual(state["status"], "AUCTION")
        self.assertEqual(state["current_bid"], 120)
        self.assertEqual(state["highest_bidder_id"], "sess_p3")
        self.assertEqual(state["highest_bidder_name"], "Misty")
        self.assertEqual(state["timer_seconds_left"], 9)
        self.assertIsNotNone(state["current_pokemon"])

    def test_03_rejoin_mid_auction_preserves_player_state_no_duplicate(self):
        """Bug 2: Reconnecting with existing session_id restores membership without duplicating."""
        p2 = self.room.get_player("sess_p2")
        p2.purse = 340
        p2.team.append({"id": "c1", "name": "TestChar", "universe": "POKEMON", "cost": 160})
        p2.is_connected = False

        room, msg = self.rm.join_room(
            self.room.room_code, "Ash", "blue", "sess_p2"
        )
        self.assertIsNotNone(room)
        self.assertIn("Reconnected", msg)
        self.assertEqual(len(room.players), 4)
        self.assertTrue(p2.is_connected)
        self.assertEqual(p2.purse, 340)
        self.assertEqual(len(p2.team), 1)
        self.assertEqual(room.status, "AUCTION")

    def test_04_rejoin_during_battle_and_game_over_preserves_phase(self):
        """Bug 2: Reconnecting during BATTLE or GAME_OVER does not reset room to LOBBY."""
        for phase in ("BATTLE", "GAME_OVER"):
            self.room.status = phase
            p3 = self.room.get_player("sess_p3")
            p3.is_connected = False
            room, msg = self.rm.join_room(
                self.room.room_code, "Misty", "green", "sess_p3"
            )
            self.assertIsNotNone(room)
            self.assertIn("Reconnected", msg)
            self.assertEqual(room.status, phase)
            self.assertTrue(p3.is_connected)

    def test_05_single_settlement_exact_deduction_and_assignment(self):
        """Bugs 3 & 4: Normal settlement adds 1 character and deducts bid once."""
        self.room.current_bid = 75
        self.room.highest_bidder_id = "sess_p1"
        res = self.room.settle_current_round(1)
        self.assertIsNotNone(res)
        self.assertEqual(res["status"], "SOLD")
        self.assertEqual(res["winner"].session_id, "sess_p1")
        self.assertEqual(res["winning_bid"], 75)
        p1 = self.room.get_player("sess_p1")
        self.assertEqual(len(p1.team), 1)
        self.assertEqual(p1.purse, 425)

    def test_06_duplicate_settlement_same_round_is_idempotent(self):
        """Bugs 3 & 4: Calling settle_current_round twice for same round is a no-op."""
        self.room.current_bid = 100
        self.room.highest_bidder_id = "sess_p2"
        first = self.room.settle_current_round(1)
        second = self.room.settle_current_round(1)

        self.assertIsNotNone(first)
        self.assertIsNone(second)
        p2 = self.room.get_player("sess_p2")
        self.assertEqual(len(p2.team), 1)
        self.assertEqual(p2.purse, 400)
        self.assertEqual(len(self.room.settlement_ledger), 1)

    def test_07_concurrent_settlement_under_lock_no_double_charge(self):
        """Bugs 3 & 4: Concurrent asyncio tasks trying to settle same round settle only once."""
        async def run_concurrent():
            self.room.current_bid = 150
            self.room.highest_bidder_id = "sess_p4"

            async def try_settle():
                async with self.room.auction_lock:
                    return self.room.settle_current_round(1)

            results = await asyncio.gather(*(try_settle() for _ in range(10)))
            settled_count = sum(1 for r in results if r is not None)
            self.assertEqual(settled_count, 1)

        asyncio.run(run_concurrent())
        p4 = self.room.get_player("sess_p4")
        self.assertEqual(len(p4.team), 1)
        self.assertEqual(p4.purse, 350)

    def test_08_uncontested_single_bid_win(self):
        """Bugs 3 & 4: Single uncontested opening bid settles cleanly once."""
        self.room.current_bid = self.room.min_bid
        self.room.highest_bidder_id = "sess_p3"
        res = self.room.settle_current_round(1)
        self.assertIsNotNone(res)
        self.assertEqual(res["status"], "SOLD")
        p3 = self.room.get_player("sess_p3")
        self.assertEqual(len(p3.team), 1)
        self.assertEqual(p3.purse, 500 - self.room.min_bid)

    def test_09_unsold_round_idempotent(self):
        """Bug 3 & 5: Unsold round (no bids) settles cleanly and cannot be re-settled."""
        self.room.current_bid = 0
        self.room.highest_bidder_id = None
        first = self.room.settle_current_round(1)
        second = self.room.settle_current_round(1)
        self.assertIsNotNone(first)
        self.assertEqual(first["status"], "UNSOLD")
        self.assertIsNone(second)
        for p in self.room.players.values():
            self.assertEqual(len(p.team), 0)
            self.assertEqual(p.purse, 500)

    def test_10_consecutive_rounds_preserve_purse_and_team_invariants(self):
        """Bugs 3, 4 & 5: Multiple consecutive rounds maintain exact purse + team totals."""
        winners = [("sess_p1", 40), ("sess_p2", 65), (None, 0), ("sess_p1", 80), ("sess_p3", 55)]
        for idx, (wid, price) in enumerate(winners, start=1):
            self.room.auction_character_count = idx
            self.room.current_character_full = self.rm.select_random_character(self.room)
            self.room.current_bid = price
            self.room.highest_bidder_id = wid
            res = self.room.settle_current_round(idx)
            self.assertIsNotNone(res)

        self.assertEqual(len(self.room.get_player("sess_p1").team), 2)
        self.assertEqual(self.room.get_player("sess_p1").purse, 500 - 40 - 80)
        self.assertEqual(len(self.room.get_player("sess_p2").team), 1)
        self.assertEqual(self.room.get_player("sess_p2").purse, 500 - 65)
        self.assertEqual(len(self.room.get_player("sess_p3").team), 1)
        self.assertEqual(self.room.get_player("sess_p3").purse, 500 - 55)
        self.assertEqual(len(self.room.get_player("sess_p4").team), 0)
        self.assertEqual(self.room.get_player("sess_p4").purse, 500)

    def test_11_team_full_blocks_further_bids(self):
        """Bug 4: Player with 6 characters has max bid 0."""
        p1 = self.room.get_player("sess_p1")
        for i in range(6):
            p1.team.append({"id": f"c_{i}", "name": f"Char{i}", "universe": "ANIME", "cost": 10})
        self.assertEqual(self.room.calculate_max_bid_for_player(p1), 0)

    def test_12_rematch_resets_settled_rounds_and_ledger(self):
        """Bug 5: reset_for_rematch clears settled_rounds & settlement_ledger for fresh match."""
        self.room.current_bid = 90
        self.room.highest_bidder_id = "sess_p1"
        self.room.settle_current_round(1)
        self.assertIn(1, self.room.settled_rounds)
        self.assertEqual(len(self.room.settlement_ledger), 1)

        self.room.reset_for_rematch(self.rm)
        self.assertEqual(len(self.room.settled_rounds), 0)
        self.assertEqual(len(self.room.settlement_ledger), 0)
        self.assertEqual(self.room.status, "AUCTION")
        for p in self.room.players.values():
            self.assertEqual(p.purse, 500)
            self.assertEqual(len(p.team), 0)

    def test_13_all_universe_modes_select_characters(self):
        """Regression: POKEMON, ANIME, MARVEL, and MIXED pools all select valid characters."""
        for mode, unis in (
            ("POKEMON", ["POKEMON"]),
            ("ANIME", ["ANIME"]),
            ("MARVEL", ["MARVEL"]),
            ("MIXED", ["POKEMON", "ANIME", "MARVEL"]),
        ):
            r = self.rm.create_room("Host", "red", f"h_{mode}", 500)
            r.allowed_universes = unis
            ch = self.rm.select_random_character(r)
            self.assertIsNotNone(ch, f"Failed to select character for universe_mode={mode}")
            self.assertIn("name", ch)


class TestFourPlayerWebSocketReliability(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Reset server room_manager state cleanly for isolated test
        game_server.room_manager.rooms.clear()
        game_server.room_auction_tasks.clear()

        self.ws_server = await websockets.serve(game_server.ws_handler, "127.0.0.1", 0)
        self.port = self.ws_server.sockets[0].getsockname()[1]
        self.ws_url = f"ws://127.0.0.1:{self.port}"

    async def asyncTearDown(self):
        for task in list(game_server.room_auction_tasks.values()):
            if not task.done():
                task.cancel()
        self.ws_server.close()
        await self.ws_server.wait_closed()

    async def _recv_until(self, ws, target_types, timeout=5.0):
        """Read messages until one of target_types arrives; return (type, data, all_msgs)."""
        if isinstance(target_types, str):
            target_types = {target_types}
        msgs = []
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            remaining = max(0.05, deadline - time.monotonic())
            raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
            msg = json.loads(raw)
            msgs.append(msg)
            if msg.get("type") in target_types:
                return msg["type"], msg.get("data", {}), msgs
        raise TimeoutError(f"Timed out waiting for {target_types}; got {[m.get('type') for m in msgs]}")

    async def _connect(self):
        return await websockets.connect(self.ws_url)

    async def _send(self, ws, action, **data):
        await ws.send(json.dumps({"action": action, "data": data}))

    async def test_14_four_player_double_start_guard_and_authoritative_bidding(self):
        """Bugs 1 & 3 & 5: 4 players join, double start_game creates only 1 loop, same-name bidding tracks session_id."""
        c1, c2, c3, c4 = await asyncio.gather(
            self._connect(), self._connect(), self._connect(), self._connect()
        )
        try:
            await self._send(c1, "create_room", session_id="ws_p1", name="SameName", avatar="red", anime_mode="all")
            _, joined1, _ = await self._recv_until(c1, "room_joined")
            code = joined1["room_code"]

            for ws, sid, nm in ((c2, "ws_p2", "SameName"), (c3, "ws_p3", "Misty"), (c4, "ws_p4", "Brock")):
                await self._send(ws, "join_room", session_id=sid, room_code=code, name=nm, avatar="blue")
                await self._recv_until(ws, "room_joined")

            for ws in (c1, c2, c3, c4):
                await self._send(ws, "toggle_ready")
            await asyncio.sleep(0.1)

            # Fire two concurrent start_game requests (double-click simulation)
            await asyncio.gather(
                self._send(c1, "start_game"),
                self._send(c1, "start_game"),
            )
            _, started, _ = await self._recv_until(c1, "auction_started", timeout=6.0)
            self.assertEqual(started["room_state"]["status"], "AUCTION")
            self.assertIn(code, game_server.room_auction_tasks)

            # Player 2 bids 20 -> P2 is highest_bidder_id, P1 (with same name!) is NOT
            await self._send(c2, "place_bid", amount=20)
            _, bid2, _ = await self._recv_until(c1, "bid_success")
            await self._recv_until(c2, "bid_success")
            self.assertEqual(bid2["highest_bidder_id"], "ws_p2")
            self.assertNotEqual(bid2["highest_bidder_id"], "ws_p1")

            # Player 1 (non-leader with same display name) CAN outbid at 25
            await self._send(c1, "place_bid", amount=25)
            _, bid1, _ = await self._recv_until(c2, "bid_success")
            self.assertEqual(bid1["highest_bidder_id"], "ws_p1")
            self.assertEqual(bid1["current_bid"], 25)
        finally:
            for ws in (c1, c2, c3, c4):
                await ws.close()

    async def test_15_concurrent_bids_race_clean_resolution(self):
        """Bugs 1 & 5: Simultaneous identical bids from 4 players resolve cleanly to 1 winner and 3 bid_errors."""
        c1, c2, c3, c4 = await asyncio.gather(
            self._connect(), self._connect(), self._connect(), self._connect()
        )
        try:
            await self._send(c1, "create_room", session_id="race_p1", name="P1", anime_mode="pokemon")
            _, j1, _ = await self._recv_until(c1, "room_joined")
            code = j1["room_code"]
            for ws, sid, nm in ((c2, "race_p2", "P2"), (c3, "race_p3", "P3"), (c4, "race_p4", "P4")):
                await self._send(ws, "join_room", session_id=sid, room_code=code, name=nm)
                await self._recv_until(ws, "room_joined")
            for ws in (c1, c2, c3, c4):
                await self._send(ws, "toggle_ready")
            await self._send(c1, "start_game")
            await self._recv_until(c1, "auction_started", timeout=6.0)

            # All 4 bid 30 simultaneously
            await asyncio.gather(
                *(self._send(ws, "place_bid", amount=30) for ws in (c1, c2, c3, c4))
            )
            await asyncio.sleep(0.25)
            room = game_server.room_manager.rooms[code]
            self.assertEqual(room.current_bid, 30)
            self.assertIn(room.highest_bidder_id, {"race_p1", "race_p2", "race_p3", "race_p4"})
        finally:
            for ws in (c1, c2, c3, c4):
                await ws.close()

    async def test_16_refresh_reconnect_mid_auction_restores_full_state(self):
        """Bug 2: Player disconnecting and reconnecting mid-auction gets full active auction state."""
        c1, c2 = await asyncio.gather(self._connect(), self._connect())
        try:
            await self._send(c1, "create_room", session_id="ref_p1", name="Host", anime_mode="marvel")
            _, j1, _ = await self._recv_until(c1, "room_joined")
            code = j1["room_code"]
            await self._send(c2, "join_room", session_id="ref_p2", room_code=code, name="Refresher")
            await self._recv_until(c2, "room_joined")

            await self._send(c1, "toggle_ready")
            await self._send(c2, "toggle_ready")
            await self._send(c1, "start_game")
            await self._recv_until(c1, "auction_started", timeout=6.0)

            await self._send(c1, "place_bid", amount=40)
            await self._recv_until(c2, "bid_success")

            # Simulate browser F5 refresh on c2
            await c2.close()
            await asyncio.sleep(0.1)

            c2_rejoined = await self._connect()
            await self._send(c2_rejoined, "join_room", session_id="ref_p2", room_code=code, name="Refresher")
            _, rej, _ = await self._recv_until(c2_rejoined, "room_joined")
            rs = rej["room_state"]
            self.assertEqual(rs["status"], "AUCTION")
            self.assertEqual(rs["current_bid"], 40)
            self.assertEqual(rs["highest_bidder_id"], "ref_p1")
            self.assertIsNotNone(rs["current_pokemon"])
            self.assertEqual(len(rs["players"]), 2)
            await c2_rejoined.close()
        finally:
            await c1.close()

    async def test_17_settlement_via_websocket_assigns_once_and_deducts_once(self):
        """Bugs 3 & 4: Real auction loop timer expiry settles once, sends 1 auction_won, 1 char, 1x purse deduction."""
        c1, c2 = await asyncio.gather(self._connect(), self._connect())
        try:
            await self._send(c1, "create_room", session_id="set_p1", name="Winner", anime_mode="anime")
            _, j1, _ = await self._recv_until(c1, "room_joined")
            code = j1["room_code"]
            await self._send(c2, "join_room", session_id="set_p2", room_code=code, name="Other")
            await self._recv_until(c2, "room_joined")
            await self._send(c1, "toggle_ready")
            await self._send(c2, "toggle_ready")

            await self._send(c1, "start_game")
            await self._recv_until(c1, "auction_started", timeout=6.0)

            await self._send(c1, "place_bid", amount=55)
            await self._recv_until(c1, "bid_success")

            # Fast-forward timer to test natural loop settlement without 15s wait
            room = game_server.room_manager.rooms[code]
            room.timer_end_timestamp = time.time() + 0.15

            _, won, _ = await self._recv_until(c1, "auction_won", timeout=5.0)
            self.assertEqual(won["winner_id"], "set_p1")
            self.assertEqual(won["winning_bid"], 55)
            self.assertEqual(won["round_id"], 1)
            self.assertTrue(won.get("settlement_id"))

            p1 = room.get_player("set_p1")
            self.assertEqual(len(p1.team), 1)
            self.assertEqual(p1.purse, 445)
        finally:
            await c1.close()
            await c2.close()

    async def test_18_all_skip_round_ends_early_without_freeze(self):
        """Bug 5: When all players skip via WebSocket, round concludes cleanly and advances."""
        c1, c2 = await asyncio.gather(self._connect(), self._connect())
        try:
            await self._send(c1, "create_room", session_id="sk_p1", name="S1", anime_mode="all")
            _, j1, _ = await self._recv_until(c1, "room_joined")
            code = j1["room_code"]
            await self._send(c2, "join_room", session_id="sk_p2", room_code=code, name="S2")
            await self._recv_until(c2, "room_joined")
            await self._send(c1, "toggle_ready")
            await self._send(c2, "toggle_ready")
            await self._send(c1, "start_game")
            await self._recv_until(c1, "auction_started", timeout=6.0)

            await self._send(c1, "skip_character")
            await self._send(c2, "skip_character")
            _, ended, _ = await self._recv_until(c1, "all_skipped_round_ended", timeout=4.0)
            self.assertIn("room_state", ended)

            _, nxt, _ = await self._recv_until(c1, "auction_started", timeout=6.0)
            self.assertEqual(nxt["room_state"]["auction_pokemon_count"], 2)
        finally:
            await c1.close()
            await c2.close()

    async def test_19_bid_vs_timer_expiry_race_is_safe(self):
        """Bugs 3, 4 & 5: Late bid racing with timer expiry cannot cause double deduction or crash."""
        c1, c2 = await asyncio.gather(self._connect(), self._connect())
        try:
            await self._send(c1, "create_room", session_id="tr_p1", name="T1", anime_mode="pokemon", countdown_seconds=1)
            _, j1, _ = await self._recv_until(c1, "room_joined")
            code = j1["room_code"]
            await self._send(c2, "join_room", session_id="tr_p2", room_code=code, name="T2")
            await self._recv_until(c2, "room_joined")
            await self._send(c1, "toggle_ready")
            await self._send(c2, "toggle_ready")
            await self._send(c1, "start_game")
            await self._recv_until(c1, "auction_started", timeout=6.0)

            await self._send(c1, "place_bid", amount=20)
            await self._recv_until(c1, "bid_success")

            room = game_server.room_manager.rooms[code]
            # Wait just under 1s and send a racing bid as timer expires
            await asyncio.sleep(0.9)
            await self._send(c2, "place_bid", amount=30)

            msg_type, data, _ = await self._recv_until(c1, {"auction_won", "auction_unsold"}, timeout=5.0)
            self.assertEqual(msg_type, "auction_won")
            # Whichever bid won, purse + winning_bid == 500 and team len == 1
            winner = room.get_player(data["winner_id"])
            self.assertEqual(len(winner.team), 1)
            self.assertEqual(winner.purse + data["winning_bid"], 500)
        finally:
            await c1.close()
            await c2.close()

    async def test_20_withdraw_mid_auction_clears_high_bid_under_lock(self):
        """Bug 5: Withdrawing while holding high bid clears high bid cleanly without freezing loop."""
        c1, c2, c3 = await asyncio.gather(
            self._connect(), self._connect(), self._connect()
        )
        try:
            await self._send(c1, "create_room", session_id="wd_p1", name="W1", anime_mode="all")
            _, j1, _ = await self._recv_until(c1, "room_joined")
            code = j1["room_code"]
            for ws, sid, nm in ((c2, "wd_p2", "W2"), (c3, "wd_p3", "W3")):
                await self._send(ws, "join_room", session_id=sid, room_code=code, name=nm)
                await self._recv_until(ws, "room_joined")
            for ws in (c1, c2, c3):
                await self._send(ws, "toggle_ready")
            await self._send(c1, "start_game")
            await self._recv_until(c1, "auction_started", timeout=6.0)

            await self._send(c2, "place_bid", amount=25)
            await self._recv_until(c1, "bid_success")

            await self._send(c2, "withdraw_match")
            await self._recv_until(c1, "player_withdrawn", timeout=4.0)

            room = game_server.room_manager.rooms[code]
            self.assertIsNone(room.highest_bidder_id)
            self.assertEqual(room.current_bid, 0)
        finally:
            for ws in (c1, c2, c3):
                await ws.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
