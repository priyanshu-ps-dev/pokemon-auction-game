"""
Regression & Integration Tests: Host Kick Player & Back to Lobby / Leave Room
=============================================================================
Covers unit-level RoomManager guarantees, live WebSocket multiplayer flows,
and frontend UI/modal integration hooks.
"""

import asyncio
import json
import os
import subprocess
import sys
import time
import unittest
import urllib.request

import websockets

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from src.battle_engine import PokemonCombatant
from src.combat_data import CombatDataProvider
from src.live_battle_session import LiveBattleSession
from src.room_manager import RoomManager


async def recv_until(ws, target_types, timeout=5.0):
    """Receive WS JSON messages until one of target_types arrives."""
    deadline = time.time() + timeout
    collected = []
    while time.time() < deadline:
        rem = max(0.1, deadline - time.time())
        raw = await asyncio.wait_for(ws.recv(), timeout=rem)
        msg = json.loads(raw)
        collected.append(msg)
        if msg.get("type") in target_types:
            return msg, collected
    raise TimeoutError(f"Did not receive {target_types}; got {[m.get('type') for m in collected]}")


class TestKickAndLeaveUnit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provider = CombatDataProvider()
        cls.sample_pool = [
            cls.provider.pokemon_by_id[25],
            cls.provider.pokemon_by_id[6],
            cls.provider.pokemon_by_id[1],
            cls.provider.pokemon_by_id[7],
        ]

    def test_01_host_can_kick_player_and_block_rejoin_same_room(self):
        rm = RoomManager(self.sample_pool)
        room = rm.create_room("HostRed", "red", "s_host")
        rm.join_room(room.room_code, "GuestBlue", "blue", "s_guest")

        ok, msg, info = room.kick_player("s_host", "s_guest")
        self.assertTrue(ok)
        self.assertIn("GuestBlue", msg)
        self.assertNotIn("s_guest", room.players)
        self.assertIn("s_guest", room.kicked_session_ids)

        # Kicked player cannot rejoin the same room
        rejoin_room, err = rm.join_room(room.room_code, "GuestBlue", "blue", "s_guest")
        self.assertIsNone(rejoin_room)
        self.assertEqual(err, "You have been removed from this room by the host.")

        # Kicked player CAN join a different room
        other_room = rm.create_room("OtherHost", "green", "s_other")
        joined_other, ok_msg = rm.join_room(other_room.room_code, "GuestBlue", "blue", "s_guest")
        self.assertIsNotNone(joined_other)
        self.assertIn("s_guest", joined_other.players)

    def test_02_non_host_and_self_kick_rejected(self):
        rm = RoomManager(self.sample_pool)
        room = rm.create_room("HostRed", "red", "s_host")
        rm.join_room(room.room_code, "GuestBlue", "blue", "s_guest")
        rm.join_room(room.room_code, "GuestGreen", "green", "s_guest2")

        ok_non_host, msg_non_host, _ = room.kick_player("s_guest", "s_guest2")
        self.assertFalse(ok_non_host)
        self.assertIn("Only the room host", msg_non_host)
        self.assertIn("s_guest2", room.players)

        ok_self, msg_self, _ = room.kick_player("s_host", "s_host")
        self.assertFalse(ok_self)
        self.assertIn("cannot kick themselves", msg_self)
        self.assertIn("s_host", room.players)

        ok_missing, msg_missing, _ = room.kick_player("s_host", "s_unknown")
        self.assertFalse(ok_missing)
        self.assertIn("not in this room", msg_missing)

    def test_03_kick_clears_highest_bid_if_kicked_player_was_leading(self):
        rm = RoomManager(self.sample_pool)
        room = rm.create_room("HostRed", "red", "s_host")
        rm.join_room(room.room_code, "GuestBlue", "blue", "s_guest")
        rm.join_room(room.room_code, "GuestGreen", "green", "s_guest2")
        room.status = "AUCTION"
        room.current_bid = 50
        room.highest_bidder_id = "s_guest"

        ok, _, info = room.kick_player("s_host", "s_guest")
        self.assertTrue(ok)
        self.assertIsNone(room.highest_bidder_id)
        self.assertEqual(room.current_bid, 0)
        self.assertFalse(info["should_end_match"])

    def test_04_leave_room_transfers_host_and_deletes_empty_room(self):
        rm = RoomManager(self.sample_pool)
        room = rm.create_room("HostRed", "red", "s_host")
        rm.join_room(room.room_code, "GuestBlue", "blue", "s_guest")

        ok1, _, info1 = rm.leave_room(room.room_code, "s_host")
        self.assertTrue(ok1)
        self.assertFalse(info1["room_deleted"])
        self.assertEqual(info1["new_host_id"], "s_guest")
        self.assertTrue(room.players["s_guest"].is_host)

        ok2, _, info2 = rm.leave_room(room.room_code, "s_guest")
        self.assertTrue(ok2)
        self.assertTrue(info2["room_deleted"])
        self.assertNotIn(room.room_code, rm.rooms)


class TestKickAndLeaveWebSocket(unittest.TestCase):
    server_proc = None

    @classmethod
    def setUpClass(cls):
        cls.server_proc = subprocess.Popen(
            [sys.executable, "server.py"],
            cwd=BASE_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(40):
            try:
                with urllib.request.urlopen("http://127.0.0.1:5050/api/stats", timeout=1) as resp:
                    if resp.status == 200:
                        return
            except Exception:
                time.sleep(0.25)
        raise RuntimeError("Server failed to start on port 5050")

    @classmethod
    def tearDownClass(cls):
        if cls.server_proc:
            cls.server_proc.terminate()
            try:
                cls.server_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cls.server_proc.kill()

    def test_05_ws_host_kick_flow_and_unauthorized_rejection(self):
        async def run():
            uri = "ws://127.0.0.1:5050/ws"
            async with websockets.connect(uri) as ws_host, \
                       websockets.connect(uri) as ws_guest, \
                       websockets.connect(uri) as ws_other:
                await ws_host.send(json.dumps({
                    "action": "create_room",
                    "data": {"name": "HostRed", "avatar": "red", "session_id": "ws_h1"}
                }))
                joined_h, _ = await recv_until(ws_host, {"room_joined"})
                code = joined_h["data"]["room_code"]

                await ws_guest.send(json.dumps({
                    "action": "join_room",
                    "data": {"room_code": code, "name": "GuestBlue", "avatar": "blue", "session_id": "ws_g1"}
                }))
                joined_guest, _ = await recv_until(ws_guest, {"room_joined"})
                await recv_until(ws_host, {"room_state"})

                await ws_other.send(json.dumps({
                    "action": "join_room",
                    "data": {"room_code": code, "name": "GuestGreen", "avatar": "green", "session_id": "ws_g2"}
                }))
                joined_other, _ = await recv_until(ws_other, {"room_joined"})
                await recv_until(ws_host, {"room_state"})
                await recv_until(ws_guest, {"room_state"})

                # Unauthorized non-host kick attempt
                await ws_guest.send(json.dumps({
                    "action": "kick_player",
                    "data": {"target_session_id": joined_other["data"]["session_id"]}
                }))
                err_msg, _ = await recv_until(ws_guest, {"error"})
                self.assertIn("Only the room host", err_msg["data"]["message"])

                # Host kicks ws_g1
                await ws_host.send(json.dumps({
                    "action": "kick_player",
                    "data": {"target_session_id": joined_guest["data"]["session_id"]}
                }))
                kick_ok, _ = await recv_until(ws_host, {"kick_success"})
                self.assertEqual(kick_ok["data"]["target_session_id"], joined_guest["data"]["session_id"])

                kicked_msg, _ = await recv_until(ws_guest, {"player_kicked"})
                self.assertEqual(kicked_msg["data"]["message"], "You have been removed from this room by the host.")

                left_notice, _ = await recv_until(ws_other, {"player_left"})
                self.assertTrue(left_notice["data"].get("kicked"))
                remaining_ids = [p["session_id"] for p in left_notice["data"]["room_state"]["players"]]
                self.assertNotIn(joined_guest["data"]["session_id"], remaining_ids)
                self.assertIn(joined_h["data"]["session_id"], remaining_ids)
                self.assertIn(joined_other["data"]["session_id"], remaining_ids)

                # Kicked player cannot rejoin same room
                await ws_guest.send(json.dumps({
                    "action": "join_room",
                    "data": {"room_code": code, "name": "GuestBlue", "avatar": "blue", "session_id": "ws_g1"}
                }))
                rejoin_err, _ = await recv_until(ws_guest, {"error"})
                self.assertEqual(rejoin_err["data"]["message"], "You have been removed from this room by the host.")

                # Kicked player CAN create/join another room
                await ws_guest.send(json.dumps({
                    "action": "create_room",
                    "data": {"name": "GuestBlue", "avatar": "blue", "session_id": "ws_g1"}
                }))
                new_room, _ = await recv_until(ws_guest, {"room_joined"})
                self.assertNotEqual(new_room["data"]["room_code"], code)

        asyncio.run(run())

    def test_06_ws_leave_room_host_transfer_and_cleanup(self):
        async def run():
            uri = "ws://127.0.0.1:5050/ws"
            async with websockets.connect(uri) as ws_host, \
                       websockets.connect(uri) as ws_guest:
                await ws_host.send(json.dumps({
                    "action": "create_room",
                    "data": {"name": "HostRed", "avatar": "red", "session_id": "lv_h1"}
                }))
                joined_h, _ = await recv_until(ws_host, {"room_joined"})
                code = joined_h["data"]["room_code"]

                await ws_guest.send(json.dumps({
                    "action": "join_room",
                    "data": {"room_code": code, "name": "GuestBlue", "avatar": "blue", "session_id": "lv_g1"}
                }))
                joined_guest, _ = await recv_until(ws_guest, {"room_joined"})
                await recv_until(ws_host, {"room_state"})

                # Host leaves room -> room_left for host, host_transferred + player_left for guest
                await ws_host.send(json.dumps({"action": "leave_room", "data": {}}))
                await recv_until(ws_host, {"room_left"})

                host_xfer, _ = await recv_until(ws_guest, {"host_transferred"})
                self.assertEqual(host_xfer["data"]["new_host_id"], joined_guest["data"]["session_id"])
                p_left, _ = await recv_until(ws_guest, {"player_left"})
                remaining = p_left["data"]["room_state"]["players"]
                self.assertEqual(len(remaining), 1)
                self.assertTrue(remaining[0]["is_host"])

                # Old host cannot place_bid in old room
                await ws_host.send(json.dumps({"action": "place_bid", "data": {"amount": 20}}))

                # Last player leaves -> room deleted
                await ws_guest.send(json.dumps({"action": "leave_room", "data": {}}))
                await recv_until(ws_guest, {"room_left"})

                # Joining deleted room fails
                await ws_host.send(json.dumps({
                    "action": "join_room",
                    "data": {"room_code": code, "name": "HostRed", "avatar": "red", "session_id": "lv_h1"}
                }))
                err, _ = await recv_until(ws_host, {"error"})
                self.assertIn("Room not found", err["data"]["message"])

        asyncio.run(run())


class TestFrontendKickAndLeaveHooks(unittest.TestCase):
    def test_07_html_and_js_contain_kick_and_back_to_lobby_hooks(self):
        with open(os.path.join(BASE_DIR, "public", "index.html"), "r", encoding="utf-8") as f:
            html = f.read()
        with open(os.path.join(BASE_DIR, "public", "game.js"), "r", encoding="utf-8") as f:
            js = f.read()

        for marker in [
            "kick-confirm-modal",
            "leave-room-modal",
            "js-back-to-lobby",
            "← Back to Lobby",
            "Are you sure you want to leave this room?",
            "room-toast-banner",
        ]:
            self.assertIn(marker, html)

        for marker in [
            "btn-kick-player",
            "kick_player",
            "leave_room",
            "player_kicked",
            "kick_success",
            "player_left",
            "You have been removed from this room by the host.",
            "pkmn_auction_room_code",
        ]:
            self.assertIn(marker, js)


class TestBattleActionMembershipGuard(unittest.TestCase):
    def test_08_ws_battle_action_rejected_for_kicked_and_departed_players(self):
        import server as srv
        provider = CombatDataProvider()

        async def run():
            async with websockets.serve(srv.ws_handler, "127.0.0.1", 0) as ws_srv:
                port = ws_srv.sockets[0].getsockname()[1]
                uri = f"ws://127.0.0.1:{port}/ws"

                async with websockets.connect(uri) as ws_host, \
                           websockets.connect(uri) as ws_kicked, \
                           websockets.connect(uri) as ws_left:
                    await ws_host.send(json.dumps({
                        "action": "create_room",
                        "data": {"name": "HostRed", "avatar": "red", "session_id": "ba_h1", "battle_control_mode": "player_vs_player"}
                    }))
                    joined, _ = await recv_until(ws_host, {"room_joined"})
                    code = joined["data"]["room_code"]

                    await ws_kicked.send(json.dumps({
                        "action": "join_room",
                        "data": {"room_code": code, "name": "KickedBlue", "avatar": "blue", "session_id": "ba_k1"}
                    }))
                    joined_kicked, _ = await recv_until(ws_kicked, {"room_joined"})
                    await recv_until(ws_host, {"room_state"})

                    await ws_left.send(json.dumps({
                        "action": "join_room",
                        "data": {"room_code": code, "name": "LeftGreen", "avatar": "green", "session_id": "ba_l1"}
                    }))
                    joined_left, _ = await recv_until(ws_left, {"room_joined"})
                    await recv_until(ws_host, {"room_state"})

                    host_id = joined["data"]["session_id"]
                    kicked_id = joined_kicked["data"]["session_id"]
                    left_id = joined_left["data"]["session_id"]
                    room = srv.room_manager.rooms[code]
                    room.status = "BATTLE"
                    p1_mon = PokemonCombatant(provider.get_combat_profile("pkmn_25"))
                    p2_mon = PokemonCombatant(provider.get_combat_profile("pkmn_6"))
                    live = LiveBattleSession(host_id, [p1_mon], kicked_id, [p2_mon], control_mode="player_vs_player", match_id=room.match_id)
                    live.turn_number = 1
                    room.active_live_battle = live

                    # 1. Host kicks ba_k1, then ba_k1 attempts submit_battle_action
                    await ws_host.send(json.dumps({
                        "action": "kick_player",
                        "data": {"target_session_id": kicked_id}
                    }))
                    await recv_until(ws_host, {"kick_success"})
                    await recv_until(ws_kicked, {"player_kicked"})

                    await ws_kicked.send(json.dumps({
                        "action": "submit_battle_action",
                        "data": {"type": "attack", "move_index": 0}
                    }))
                    kicked_err, _ = await recv_until(ws_kicked, {"battle_action_error"})
                    self.assertFalse(kicked_err["data"]["success"])
                    self.assertIn("removed from this room by the host", kicked_err["data"]["message"])
                    self.assertNotIn(kicked_id, live.pending_actions)

                    # 2. ba_l1 voluntarily leaves, then attempts submit_battle_action
                    await ws_left.send(json.dumps({"action": "leave_room", "data": {}}))
                    await recv_until(ws_left, {"room_left"})

                    await ws_left.send(json.dumps({
                        "action": "submit_battle_action",
                        "data": {"type": "attack", "move_index": 0}
                    }))
                    left_err, _ = await recv_until(ws_left, {"battle_action_error"})
                    self.assertFalse(left_err["data"]["success"])
                    self.assertIn("no longer a member of this room", left_err["data"]["message"])
                    self.assertNotIn(left_id, live.pending_actions)

                    # 3. Valid active member (ba_h1) can still submit a battle action
                    first_move_id = p1_mon.moves[0]["id"]
                    await ws_host.send(json.dumps({
                        "action": "submit_battle_action",
                        "data": {"action_type": "attack", "move_id": first_move_id}
                    }))
                    ack, _ = await recv_until(ws_host, {"battle_action_ack"})
                    self.assertTrue(ack["data"]["success"])
                    self.assertIn(host_id, live.pending_actions)

                    # Cleanup room
                    srv.room_manager.rooms.pop(code, None)

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main(verbosity=2)
