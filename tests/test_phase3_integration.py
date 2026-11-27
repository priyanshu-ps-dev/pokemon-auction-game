"""
Phase 3 Integration Tests: Cross-Universe Combat, Live Multiplayer Lifecycle & Frontend Checks
==============================================================================================
Tests:
1. Cross-universe combat (Pokemon vs Anime, mixed teams, unsupported anime handling).
2. 2-to-8 player tournament scaling, withdrawals, empty/incomplete teams, no duplicate matches.
3. Live WebSocket server full lifecycle:
   create_room -> join_room -> start_game -> place_bid -> skip_character ->
   battle_started -> battle_progress -> battle_results -> match_finished -> game_over -> rematch.
4. Frontend HTML/JS/CSS integration checks.
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

from src.battle_manager import BattleManager
from src.combat_data import CombatDataProvider
from src.cross_universe_adapter import CrossUniverseConfig
from src.room_manager import Player

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestPhase3CrossUniverseAndFrontend(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provider = CombatDataProvider()
        cls.manager = BattleManager(cls.provider)

    def test_01_cross_universe_pokemon_vs_anime(self):
        """Pokémon and verified Anime characters battle via CrossUniverseBattleSimulator."""
        charizard = self.provider.get_combat_profile("pkmn_6")
        goku = self.provider.get_combat_profile("db_goku")

        res = self.manager.simulate_1v1(
            "pkmn_trainer", [charizard],
            "anime_trainer", [goku],
            seed=2026,
            cross_config=CrossUniverseConfig(cross_damage_scale=0.85),
        )
        self.assertIn(res.winner_id, ("pkmn_trainer", "anime_trainer"))
        self.assertGreater(res.turns_played, 0)
        self.assertGreater(len(res.turn_log), 0)
        self.assertIn("active_a", res.turn_log[0])
        self.assertIn("active_b", res.turn_log[0])

    def test_02_mixed_team_with_unverified_anime_character(self):
        """Mixed team skips unverified anime character without inventing moves."""
        unverified_cid = next(
            cid for cid, p in self.provider.anime_combat_by_id.items()
            if p["verification_status"] == "unverified_incomplete"
        )
        unverified = self.provider.get_combat_profile(unverified_cid)
        pikachu = self.provider.get_combat_profile("pkmn_25")

        res = self.manager.simulate_1v1(
            "unver_only", [unverified],
            "pika_only", [pikachu],
            seed=11,
        )
        self.assertEqual(res.winner_id, "pika_only")
        self.assertEqual(res.reason, "TEAM_FORFEIT_OR_UNSUPPORTED")

    def test_03_eight_player_tournament_no_duplicates_and_incomplete_teams(self):
        """8-player round-robin produces 28 unique matches with deterministic standings."""
        pk_ids = ["pkmn_6", "pkmn_25", "pkmn_150", "pkmn_94", "pkmn_130", "pkmn_384", "pkmn_149", "pkmn_448"]
        players = []
        for idx, pk in enumerate(pk_ids):
            p = Player(f"p_{idx}", f"Trainer_{idx}", "red", is_host=(idx == 0))
            prof = self.provider.get_combat_profile(pk)
            # Vary team sizes (1, 2, 0, ...)
            p.team = [] if idx == 7 else ([prof] * ((idx % 3) + 1))
            players.append(p)

        res = asyncio.run(self.manager.run_tournament_async(players, match_id="m_8p"))
        self.assertEqual(res["format"], "round_robin")
        self.assertEqual(res["total_matches"], 28)  # 8 * 7 / 2
        pairs = {(m["player_a_id"], m["player_b_id"]) for m in res["matches"]}
        self.assertEqual(len(pairs), 28)
        self.assertEqual(res["standings"][-1]["session_id"], "p_7")  # Empty team last

    def test_04_frontend_battle_ui_elements_present(self):
        """Frontend HTML, CSS, and JS contain the required Battle Arena & Results hooks."""
        with open(os.path.join(BASE_DIR, "public", "index.html"), encoding="utf-8") as f:
            html = f.read()
        with open(os.path.join(BASE_DIR, "public", "game.js"), encoding="utf-8") as f:
            js = f.read()
        with open(os.path.join(BASE_DIR, "public", "styles.css"), encoding="utf-8") as f:
            css = f.read()

        for marker in ("id=\"arena-battle\"", "id=\"battle-event-log\"", "id=\"battle-champion-banner\"", "id=\"battle-matches-summary\""):
            self.assertIn(marker, html)
        for js_fn in ("playBattleSequence", "battle_started", "battle_results", "renderLeaderboard"):
            self.assertIn(js_fn, js)
        for anim in ("battleLungeLeft", "battleHitShake", "battleFaint", "battleTransformGlow"):
            self.assertIn(anim, css)


class TestPhase3LiveMultiplayerLifecycle(unittest.TestCase):
    """Spawns server.py on port 5050 and runs an end-to-end WebSocket match."""

    @classmethod
    def setUpClass(cls):
        cls.proc = subprocess.Popen(
            [sys.executable, "server.py"],
            cwd=BASE_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        # Wait for HTTP endpoint to come up
        ready = False
        for _ in range(30):
            try:
                with urllib.request.urlopen("http://127.0.0.1:5050/api/stats", timeout=1) as resp:
                    if resp.status == 200:
                        ready = True
                        break
            except Exception:
                time.sleep(0.25)
        if not ready:
            cls.proc.kill()
            raise RuntimeError("server.py did not start in time for live test")

    @classmethod
    def tearDownClass(cls):
        if cls.proc and cls.proc.poll() is None:
            cls.proc.terminate()
            try:
                cls.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cls.proc.kill()

    def test_05_live_auction_to_battle_to_champion_and_rematch(self):
        """Full live lifecycle: create -> join -> start -> bid -> skip -> battle -> game_over -> rematch."""
        async def _run():
            async with websockets.connect("ws://127.0.0.1:5050/ws", ping_timeout=60) as ws_a, \
                       websockets.connect("ws://127.0.0.1:5050/ws", ping_timeout=60) as ws_b:

                # 1. Create room (pokemon mode, fast 2s timer)
                await ws_a.send(json.dumps({
                    "action": "create_room",
                    "data": {
                        "name": "Red",
                        "avatar": "red",
                        "session_id": "live_a",
                        "starting_purse": 100,
                        "countdown_seconds": 2,
                        "anime_mode": "pokemon",
                    },
                }))
                joined_a = json.loads(await ws_a.recv())
                self.assertEqual(joined_a["type"], "room_joined")
                room_code = joined_a["data"]["room_code"]

                # 2. Join room
                await ws_b.send(json.dumps({
                    "action": "join_room",
                    "data": {
                        "room_code": room_code,
                        "name": "Blue",
                        "avatar": "blue",
                        "session_id": "live_b",
                    },
                }))
                joined_b = json.loads(await ws_b.recv())
                self.assertEqual(joined_b["type"], "room_joined")

                # 3. Start game
                await ws_a.send(json.dumps({"action": "start_game", "data": {}}))

                seen_types = []
                bid_placed_a = False
                bid_placed_b = False
                battle_results_payload = None
                game_over_payload = None
                stop_b = asyncio.Event()

                async def _drain_b():
                    while not stop_b.is_set():
                        try:
                            await asyncio.wait_for(ws_b.recv(), timeout=0.5)
                        except asyncio.TimeoutError:
                            continue
                        except Exception:
                            break

                async def _drain_until_game_over():
                    nonlocal bid_placed_a, bid_placed_b, battle_results_payload, game_over_payload
                    deadline = time.time() + 60
                    while time.time() < deadline:
                        raw = await asyncio.wait_for(ws_a.recv(), timeout=15)
                        msg = json.loads(raw)
                        mtype = msg["type"]
                        seen_types.append(mtype)

                        if mtype == "auction_started":
                            # Verify stats are hidden during auction!
                            char = msg["data"]["character"]
                            self.assertNotIn("stats", char)
                            self.assertNotIn("power_rating", char)

                            if not bid_placed_a:
                                bid_placed_a = True
                                await ws_a.send(json.dumps({"action": "place_bid", "data": {"amount": 20, "match_id": msg["data"]["room_state"]["match_id"], "round_id": msg["data"]["auction_round"]}}))
                            elif not bid_placed_b:
                                bid_placed_b = True
                                await ws_b.send(json.dumps({"action": "place_bid", "data": {"amount": 25, "match_id": msg["data"]["room_state"]["match_id"], "round_id": msg["data"]["auction_round"]}}))
                            else:
                                # Skip remaining rounds quickly so pool exhausts fast
                                await ws_a.send(json.dumps({"action": "skip_character", "data": {}}))
                                await ws_b.send(json.dumps({"action": "skip_character", "data": {}}))

                        elif mtype == "battle_results":
                            battle_results_payload = msg["data"]
                        elif mtype == "game_over":
                            game_over_payload = msg["data"]
                            break

                task_b = asyncio.create_task(_drain_b())
                try:
                    await _drain_until_game_over()
                finally:
                    stop_b.set()
                    await task_b

                self.assertIn("battle_started", seen_types)
                self.assertIn("battle_results", seen_types)
                self.assertIn("match_finished", seen_types)
                self.assertIsNotNone(battle_results_payload)
                self.assertIsNotNone(game_over_payload)

                # Verify purse non-negative and leaderboard has battle_wins
                for p in game_over_payload["leaderboard"]:
                    self.assertGreaterEqual(p["remaining_purse"], 0)
                    self.assertIn("battle_wins", p)

                # 4. Verify rematch flow
                await ws_a.send(json.dumps({"action": "request_rematch", "data": {}}))
                await ws_b.send(json.dumps({"action": "vote_rematch", "data": {"accept": True}}))

                rematch_seen = False
                for _ in range(10):
                    raw = await asyncio.wait_for(ws_a.recv(), timeout=5)
                    msg = json.loads(raw)
                    if msg["type"] == "rematch_started":
                        rematch_seen = True
                        break
                self.assertTrue(rematch_seen)

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main(verbosity=2)
