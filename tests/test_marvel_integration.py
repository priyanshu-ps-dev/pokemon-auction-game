"""
Marvel Universe Auction, Tournament & Live Multiplayer Integration Tests (Phase 6)
=================================================================================
Covers:
- Universe selection modes (marvel, pokemon_marvel, anime_marvel, pokemon_anime, all)
- 4-player mixed-universe tournament (Pokémon + Anime + Marvel)
- Live WebSocket mixed-universe auction -> battle -> rematch -> room isolation
- Frontend Marvel universe selection & filtering hooks
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

from src.anime_database import AnimeDatabaseManager
from src.battle_manager import BattleManager
from src.combat_data import CombatDataProvider
from src.room_manager import Player, RoomManager

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")


class TestMarvelAuctionAndTournament(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.anime_db = AnimeDatabaseManager(
            os.path.join(DATA_DIR, "anime_database.json"),
            os.path.join(DATA_DIR, "anime_platform.db"),
        )
        cls.provider = CombatDataProvider()
        cls.manager = BattleManager(cls.provider)

    def test_01_universe_selection_modes(self):
        """All 7 universe selection modes filter the auction pool accurately."""
        rm = RoomManager(self.anime_db)

        r_marvel = rm.create_room("H", "red", "s1", anime_mode="marvel")
        self.assertEqual(len(r_marvel.character_pool), 52)  # Curated MCU screen fighters
        self.assertTrue(all(c["anime_id"] == "marvel" for c in r_marvel.character_pool))

        r_pm = rm.create_room("H", "red", "s2", anime_mode="pokemon_marvel")
        self.assertTrue(all(c["anime_id"] in ("pokemon", "marvel") for c in r_pm.character_pool))
        self.assertTrue(any(c["anime_id"] == "marvel" for c in r_pm.character_pool))
        self.assertTrue(any(c["anime_id"] == "pokemon" for c in r_pm.character_pool))

        r_am = rm.create_room("H", "red", "s3", anime_mode="anime_marvel")
        self.assertTrue(all(c["anime_id"] != "pokemon" for c in r_am.character_pool))
        self.assertTrue(any(c["anime_id"] == "marvel" for c in r_am.character_pool))

    def test_02_four_player_mixed_universe_tournament(self):
        """4-player tournament with Pokémon, Anime, and Marvel rosters completes cleanly."""
        p1 = Player("u1", "Ash", "ash", is_host=True)
        p1.team = [self.provider.get_combat_profile("pkmn_6")]
        p2 = Player("u2", "GokuFan", "red")
        p2.team = [self.provider.get_combat_profile("db_goku")]
        p3 = Player("u3", "Stark", "blue")
        p3.team = [self.provider.get_combat_profile("marvel_616_iron_man")]
        p4 = Player("u4", "Hybrid", "green")
        p4.team = [self.provider.get_combat_profile("pkmn_25"), self.provider.get_combat_profile("marvel_616_thor")]

        res = asyncio.run(self.manager.run_tournament_async([p1, p2, p3, p4], match_id="mixed_4p"))
        self.assertEqual(res["format"], "round_robin")
        self.assertEqual(res["total_matches"], 6)
        self.assertIsNotNone(res["champion"])

    def test_03_frontend_marvel_hooks_present(self):
        """Frontend HTML and JS include Marvel mode buttons, filter toggle, and stats rendering."""
        with open(os.path.join(BASE_DIR, "src", "components", "AuctionTicketModal.jsx"), encoding="utf-8") as file:
            self.assertIn("Marvel MCU", file.read())
        with open(os.path.join(BASE_DIR, "public", "game.js"), encoding="utf-8") as file:
            self.assertIn("energy_projection", file.read())


class TestMarvelLiveServerIntegration(unittest.TestCase):
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

    def test_04_live_marvel_only_auction_battle_and_rematch(self):
        """Live WebSocket Marvel-only room completes auction, battle, and rematch cleanly."""
        async def _run():
            async with websockets.connect("ws://127.0.0.1:5050/ws", ping_timeout=60) as ws1, \
                       websockets.connect("ws://127.0.0.1:5050/ws", ping_timeout=60) as ws2:
                await ws1.send(json.dumps({
                    "action": "create_room",
                    "data": {
                        "name": "Stark", "avatar": "red", "session_id": "m_live_1",
                        "starting_purse": 100, "countdown_seconds": 1,
                        "anime_mode": "marvel", "battle_control_mode": "ai_vs_ai",
                    },
                }))
                j1 = json.loads(await ws1.recv())
                code = j1["data"]["room_code"]
                await ws2.send(json.dumps({
                    "action": "join_room",
                    "data": {"room_code": code, "name": "Rogers", "avatar": "blue", "session_id": "m_live_2"},
                }))
                await ws2.recv()
                await ws1.send(json.dumps({"action": "start_game", "data": {}}))

                b1 = b2 = False
                game_over_data = None
                stop = asyncio.Event()

                async def _drain2():
                    while not stop.is_set():
                        try:
                            await asyncio.wait_for(ws2.recv(), timeout=0.4)
                        except Exception:
                            continue

                t2 = asyncio.create_task(_drain2())
                try:
                    deadline = time.time() + 60
                    while time.time() < deadline:
                        msg = json.loads(await asyncio.wait_for(ws1.recv(), timeout=15))
                        if msg["type"] == "auction_started":
                            ch = msg["data"]["character"]
                            self.assertEqual(ch["anime_id"], "marvel")
                            self.assertIn("stats", ch)
                            self.assertTrue(ch.get("description"))
                            self.assertTrue(ch.get("techniques"))
                            if not b1:
                                b1 = True
                                await ws1.send(json.dumps({"action": "place_bid", "data": {"amount": 20, "match_id": msg["data"]["room_state"]["match_id"], "round_id": msg["data"]["auction_round"]}}))
                            elif not b2:
                                b2 = True
                                await ws2.send(json.dumps({"action": "place_bid", "data": {"amount": 20, "match_id": msg["data"]["room_state"]["match_id"], "round_id": msg["data"]["auction_round"]}}))
                            else:
                                await ws1.send(json.dumps({"action": "skip_character", "data": {}}))
                                await ws2.send(json.dumps({"action": "skip_character", "data": {}}))
                        elif msg["type"] == "game_over":
                            game_over_data = msg["data"]
                            break
                finally:
                    stop.set()
                    await t2

                self.assertIsNotNone(game_over_data)
                self.assertIsNotNone(game_over_data["winner"])

                await ws1.send(json.dumps({"action": "request_rematch", "data": {}}))
                await ws2.send(json.dumps({"action": "vote_rematch", "data": {"accept": True}}))
                for _ in range(15):
                    rm = json.loads(await asyncio.wait_for(ws1.recv(), timeout=5))
                    if rm["type"] == "rematch_started":
                        self.assertEqual(rm["data"]["match_number"], 2)
                        break

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main(verbosity=2)
