"""
Regression Tests: Manual PvP Rematch State & Session Isolation
=============================================================
Verifies that rematches in player_vs_player mode start with completely fresh
teams, HP, status, transformations, turn counters, pending actions, and
match_id isolation across rooms and repeated rematches.
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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.anime_battle_engine import AnimeCombatant
from src.battle_engine import PokemonCombatant
from src.combat_data import CombatDataProvider
from src.live_battle_session import LiveBattleSession
from src.room_manager import Player, RoomManager

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestPvPRematchStateIsolation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provider = CombatDataProvider()

    def test_01_reset_for_rematch_invalidates_old_session_and_clears_state(self):
        """Room.reset_for_rematch invalidates active_live_battle, clears teams, and increments match_id."""
        rm = RoomManager([self.provider.pokemon_by_id[25]])
        room = rm.create_room("Red", "red", "s1", battle_control_mode="player_vs_player")
        rm.join_room(room.room_code, "Blue", "blue", "s2")

        pika = PokemonCombatant(self.provider.get_combat_profile("pkmn_25"))
        char = PokemonCombatant(self.provider.get_combat_profile("pkmn_6"))
        old_sess = LiveBattleSession("s1", [pika], "s2", [char], control_mode="player_vs_player", match_id=room.match_id)
        old_sess.turn_number = 5
        old_sess.submit_action("s1", {"action_type": "attack", "move_id": pika.moves[0]["id"], "match_id": room.match_id})
        room.active_live_battle = old_sess

        room.players["s1"].team = [self.provider.pokemon_by_id[25]]
        room.players["s2"].team = [self.provider.pokemon_by_id[6]]

        info = room.reset_for_rematch(rm)
        self.assertTrue(old_sess.is_invalidated)
        self.assertIsNone(room.active_live_battle)
        self.assertEqual(info["match_number"], 2)
        self.assertEqual(room.players["s1"].team, [])
        self.assertEqual(room.players["s2"].team, [])

        # Old session rejects any subsequent action
        ok, msg = old_sess.submit_action("s2", {"action_type": "attack", "move_id": char.moves[0]["id"], "match_id": f"{room.room_code}_m1"})
        self.assertFalse(ok)

    def test_02_stale_match_id_action_rejected_and_no_stat_leak(self):
        """Actions with an old match_id are rejected; HP/status/transformations do not carry over."""
        goku1 = AnimeCombatant(self.provider.get_combat_profile("db_goku"))
        naruto1 = AnimeCombatant(self.provider.get_combat_profile("naruto_naruto"))
        goku1.activate_transformation("db_goku_ssj")
        goku1.take_damage(100)

        # New session for match_2 with fresh combatants
        goku2 = AnimeCombatant(self.provider.get_combat_profile("db_goku"))
        naruto2 = AnimeCombatant(self.provider.get_combat_profile("naruto_naruto"))
        sess2 = LiveBattleSession("s1", [goku2], "s2", [naruto2], control_mode="player_vs_player", match_id="ROOM_m2")

        self.assertEqual(sess2.turn_number, 0)
        self.assertEqual(len(sess2.pending_actions), 0)
        self.assertIsNone(goku2.active_transformation)
        self.assertEqual(goku2.current_hp, goku2.max_hp)

        # Stale match_id rejected
        ok_stale, _ = sess2.submit_action("s1", {"action_type": "attack", "move_id": goku2.attacks[0]["id"], "match_id": "ROOM_m1"})
        self.assertFalse(ok_stale)

        # Current match_id accepted
        ok_cur, _ = sess2.submit_action("s1", {"action_type": "attack", "move_id": goku2.attacks[0]["id"], "match_id": "ROOM_m2"})
        self.assertTrue(ok_cur)

    def test_03_two_rooms_isolated_during_rematches(self):
        """Two separate rooms cannot leak character data into each other's rematches."""
        rm = RoomManager([self.provider.pokemon_by_id[25], self.provider.pokemon_by_id[6]])
        r1 = rm.create_room("R1A", "red", "r1_a", anime_mode="pokemon", battle_control_mode="player_vs_player")
        rm.join_room(r1.room_code, "R1B", "blue", "r1_b")
        r2 = rm.create_room("R2A", "ash", "r2_a", anime_mode="pokemon", battle_control_mode="player_vs_player")
        rm.join_room(r2.room_code, "R2B", "gary", "r2_b")

        r1.players["r1_a"].team = [self.provider.pokemon_by_id[25]]
        r2.players["r2_a"].team = [self.provider.pokemon_by_id[6]]

        r1.reset_for_rematch(rm)
        self.assertEqual(r1.players["r1_a"].team, [])
        self.assertEqual(len(r2.players["r2_a"].team), 1)
        self.assertEqual(r2.players["r2_a"].team[0]["id"], 6)


class TestPvPRepeatedRematchesLive(unittest.TestCase):
    """Runs 3 consecutive manual PvP matches (Match 1 -> Rematch 2 -> Rematch 3) on live server.py."""

    @classmethod
    def setUpClass(cls):
        cls.proc = subprocess.Popen(
            [sys.executable, "server.py"],
            cwd=BASE_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for _ in range(30):
            try:
                with urllib.request.urlopen("http://127.0.0.1:5050/api/stats", timeout=1) as resp:
                    if resp.status == 200:
                        return
            except Exception:
                time.sleep(0.25)
        cls.proc.kill()
        raise RuntimeError("server.py failed to start")

    @classmethod
    def tearDownClass(cls):
        if cls.proc and cls.proc.poll() is None:
            cls.proc.terminate()
            try:
                cls.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cls.proc.kill()

    def test_04_three_consecutive_manual_pvp_matches_clean_teams(self):
        """Match 1, Rematch 2, and Rematch 3 each use only their own newly auctioned teams."""
        async def _run():
            async with websockets.connect("ws://127.0.0.1:5050/ws", ping_timeout=60) as ws1, \
                       websockets.connect("ws://127.0.0.1:5050/ws", ping_timeout=60) as ws2:

                await ws1.send(json.dumps({
                    "action": "create_room",
                    "data": {
                        "name": "P1", "avatar": "red", "session_id": "rem_p1",
                        "starting_purse": 500, "countdown_seconds": 1,
                        "anime_mode": "pokemon", "battle_control_mode": "player_vs_player",
                    },
                }))
                m1 = json.loads(await ws1.recv())
                code = m1["data"]["room_code"]
                await ws2.send(json.dumps({
                    "action": "join_room",
                    "data": {"room_code": code, "name": "P2", "avatar": "blue", "session_id": "rem_p2"},
                }))
                await ws2.recv()
                await ws1.send(json.dumps({"action": "start_game", "data": {}}))

                match_rosters = []
                for match_idx in range(1, 4):
                    expected_p1_chars = set()
                    expected_p2_chars = set()
                    prompt_seen_chars_p1 = set()
                    prompt_seen_chars_p2 = set()
                    p1_bid_done = False
                    p2_bid_done = False
                    stop_p2 = asyncio.Event()

                    async def _p2_loop():
                        while not stop_p2.is_set():
                            try:
                                raw = await asyncio.wait_for(ws2.recv(), timeout=0.4)
                            except asyncio.TimeoutError:
                                continue
                            msg = json.loads(raw)
                            if msg["type"] == "battle_turn_prompt":
                                d = msg["data"]
                                self.assertEqual(d["match_id"], f"{code}_m{match_idx}")
                                if d.get("your_active"):
                                    prompt_seen_chars_p2.add(d["your_active"]["name"])
                                moves = d.get("available_moves", [])
                                if moves:
                                    await ws2.send(json.dumps({
                                        "action": "submit_battle_action",
                                        "data": {"action_type": "attack", "move_id": moves[0]["id"], "match_id": d["match_id"]},
                                    }))

                    t2 = asyncio.create_task(_p2_loop())
                    try:
                        deadline = time.time() + 60
                        while time.time() < deadline:
                            msg = json.loads(await asyncio.wait_for(ws1.recv(), timeout=15))
                            t = msg["type"]
                            if t == "auction_started":
                                if not p1_bid_done:
                                    p1_bid_done = True
                                    await ws1.send(json.dumps({"action": "place_bid", "data": {"amount": 20}}))
                                elif not p2_bid_done:
                                    p2_bid_done = True
                                    await ws2.send(json.dumps({"action": "place_bid", "data": {"amount": 20}}))
                                else:
                                    await ws1.send(json.dumps({"action": "skip_character", "data": {}}))
                                    await ws2.send(json.dumps({"action": "skip_character", "data": {}}))
                            elif t == "auction_sold":
                                wid = msg["data"]["winner_id"]
                                cname = msg["data"]["character"]["name"]
                                if wid == "rem_p1":
                                    expected_p1_chars.add(cname)
                                elif wid == "rem_p2":
                                    expected_p2_chars.add(cname)
                            elif t == "battle_turn_prompt":
                                d = msg["data"]
                                self.assertEqual(d["match_id"], f"{code}_m{match_idx}")
                                if d.get("your_active"):
                                    prompt_seen_chars_p1.add(d["your_active"]["name"])
                                moves = d.get("available_moves", [])
                                if moves:
                                    await ws1.send(json.dumps({
                                        "action": "submit_battle_action",
                                        "data": {"action_type": "attack", "move_id": moves[0]["id"], "match_id": d["match_id"]},
                                    }))
                            elif t == "game_over":
                                break
                    finally:
                        stop_p2.set()
                        await t2

                    # Crucial assertion: prompted characters in match_idx must be subset of match_idx's auctioned teams!
                    self.assertTrue(prompt_seen_chars_p1.issubset(expected_p1_chars), f"Match {match_idx} P1 saw stale chars {prompt_seen_chars_p1 - expected_p1_chars}")
                    self.assertTrue(prompt_seen_chars_p2.issubset(expected_p2_chars), f"Match {match_idx} P2 saw stale chars {prompt_seen_chars_p2 - expected_p2_chars}")
                    match_rosters.append((expected_p1_chars, expected_p2_chars))

                    if match_idx < 3:
                        await ws1.send(json.dumps({"action": "request_rematch", "data": {}}))
                        await ws2.send(json.dumps({"action": "vote_rematch", "data": {"accept": True}}))
                        for _ in range(15):
                            rm_msg = json.loads(await asyncio.wait_for(ws1.recv(), timeout=5))
                            if rm_msg["type"] == "rematch_started":
                                self.assertEqual(rm_msg["data"]["match_number"], match_idx + 1)
                                break

                self.assertEqual(len(match_rosters), 3)

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main(verbosity=2)
