import asyncio
from contextlib import AsyncExitStack
import json
import tempfile
import time
import unittest
from unittest.mock import patch

from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

import server
from src.combat_interactions import resolve_technique_damage
from src.player_profiles import PlayerProfileStore
from src.room_manager import RoomManager


class CanonicalGameplayTests(unittest.TestCase):
    def test_curated_pools_and_identity(self):
        db = server.anime_db
        mcu = db.get_characters_for_mode("marvel")
        self.assertEqual(len(mcu), 52)
        self.assertTrue(all(c["incarnation"] == "MCU screen continuity" for c in mcu))
        self.assertTrue(all(c.get("description") for c in mcu))
        self.assertTrue(all(c.get("role") for c in mcu))
        self.assertTrue(all(c.get("portrait_emblem") for c in mcu))
        self.assertTrue(all(c.get("power_rating", 0) > 0 for c in mcu))
        self.assertTrue(all(c.get("power_tier") for c in mcu))
        self.assertTrue(all(c.get("techniques") for c in mcu))
        for mode in ("all", "pokemon_standard", "pokemon_legendary"):
            roster = db.get_characters_for_mode(mode, forms_mode="SEPARATE_ENTRIES")
            self.assertTrue(roster)
            self.assertEqual(len(roster), len({c["id"] for c in roster}))
            self.assertEqual(len(roster), len({c["national_id"] for c in roster if c["anime_id"] == "pokemon"})
                             + sum(c["anime_id"] != "pokemon" for c in roster))
        room = RoomManager([mcu[0], {**mcu[0], "id": "second_form"}])
        instance = room.create_room("Host", "red", "host")
        self.assertIsNotNone(room.select_random_character(instance))
        self.assertIsNone(room.select_random_character(instance))

    def test_canonical_gap_matches_and_seed(self):
        pairs = [
            ("db_goku", "anilist_126071"), ("db_beerus", "one_piece_usopp"),
            ("opm_saitama", "marvel_mcu_kingpin"), ("naruto_madara", "anilist_126071"),
            ("marvel_mcu_thanos", "marvel_mcu_hawkeye"), ("marvel_mcu_thor", "marvel_mcu_black_widow"),
            ("marvel_mcu_scarlet_witch", "marvel_mcu_kingpin"), ("pkmn_493", "pkmn_129"),
            ("pkmn_150", "pkmn_10"), ("pkmn_384", "pkmn_19"),
        ]
        for strong, weak in pairs:
            left = {**server.anime_db.characters[strong], "auction_cost": 1, "power_rating": 0}
            right = {**server.anime_db.characters[weak], "auction_cost": 95, "power_rating": 1000}
            for seed in (1, 42, 1024):
                with self.subTest(pair=(strong, weak), seed=seed):
                    args = ("winner", [left], "other", [right], seed)
                    result = server.battle_manager.simulate_1v1(*args)
                    self.assertEqual(result.winner_id, "winner")
                    self.assertEqual(result, server.battle_manager.simulate_1v1(*args))

    def test_immunity_and_contact_evasion(self):
        import random

        _, thor = server.battle_manager.build_combatant({"id": "marvel_mcu_thor"})
        _, mantis = server.battle_manager.build_combatant({"id": "marvel_mcu_mantis"})
        rng = random.Random(1)
        damage, event = resolve_technique_damage(mantis, thor, mantis.attacks[0], 70, 100, 50, rng)
        self.assertEqual(damage, 0)
        self.assertIn("evaded", event)
        thor.immunities = ["mental"]
        damage, event = resolve_technique_damage(mantis, thor, mantis.attacks[0], 70, 100, 50, rng)
        self.assertEqual(damage, 0)
        self.assertIn("immune", event)


    def test_tournament_formats_use_battle_results(self):
        from src.room_manager import Player

        characters = server.anime_db.characters
        players = [Player(str(i), name, "red") for i, name in enumerate(("Thor", "Widow", "Hawkeye"))]
        for player, cid in zip(players, ("marvel_mcu_thor", "marvel_mcu_black_widow", "marvel_mcu_hawkeye")):
            player.team = [characters[cid]]
        manager = server.battle_manager
        league = manager.run_tournament_sync(players, "test-league")
        self.assertEqual(league["total_matches"], 3)
        self.assertEqual(league["champion"]["session_id"], "0")
        bracket = manager.run_tournament_sync(players, "test-bracket", "bracket")
        self.assertEqual(bracket["total_matches"], 2)
        self.assertEqual(bracket["champion"]["session_id"], "0")

    def test_stamina_type_and_transformations(self):
        from src.battle_engine import get_type_effectiveness
        from src.combat_interactions import spend_stamina

        _, goku = server.battle_manager.build_combatant({"id": "db_goku"})
        abilities = goku.get_available_transformations()
        self.assertTrue(abilities)
        before = goku.effective_speed
        active, _ = goku.activate_transformation(abilities[0]["id"])
        self.assertTrue(active)
        self.assertGreater(goku.effective_speed, before)
        for _ in range(goku.transformation_turns):
            goku.tick_transformation()
        self.assertEqual(goku.effective_speed, before)
        self.assertFalse(goku.get_available_transformations())
        goku.stamina = 0
        self.assertFalse(spend_stamina(goku, goku.attacks[0]))
        self.assertGreater(goku.stamina, 0)
        self.assertEqual(get_type_effectiveness("Electric", ["Water", "Flying"]), 4)
        self.assertEqual(get_type_effectiveness("Electric", ["Ground"]), 0)


class AuctionWebSocketTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.stack = AsyncExitStack()
        await self.stack.__aenter__()
        self.addAsyncCleanup(self.stack.aclose)
        temp = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.manager = RoomManager(server.anime_db)
        self.stack.enter_context(patch.multiple(
            server, room_manager=self.manager, room_auction_tasks={},
            RECONNECT_GRACE_SECONDS=0.6, AUCTION_INTERMISSION_SECONDS=0.02,
            profile_store=PlayerProfileStore(f"{temp}/profiles.sqlite"),
        ))
        listener = await self.stack.enter_async_context(serve(
            server.ws_handler, "127.0.0.1", 0, process_request=server.process_http_request,
        ))
        self.uri = f"ws://127.0.0.1:{listener.sockets[0].getsockname()[1]}/ws"

    async def socket(self):
        return await self.stack.enter_async_context(connect(self.uri))

    async def send(self, ws, action, **data):
        await ws.send(json.dumps({"action": action, "data": data}))

    async def receive(self, ws, *expected):
        async with asyncio.timeout(8):
            while True:
                msg = json.loads(await ws.recv())
                if msg["type"] in expected:
                    return msg

    async def join(self, ws, code, name):
        await self.send(ws, "join_room", room_code=code, name=name)
        return (await self.receive(ws, "room_joined"))["data"]

    async def resume(self, ws, session):
        keys = ("room_code", "session_id", "reconnect_token")
        await self.send(ws, "resume_room", **{key: session[key] for key in keys})
        return await self.receive(ws, "room_joined", "resume_error")

    async def test_auction_race_reconnect_results_and_rematch(self):
        host, guest = await asyncio.gather(self.socket(), self.socket())
        await self.send(host, "create_room", starting_purse=101)
        self.assertEqual((await self.receive(host, "error"))["type"], "error")
        await self.send(host, "create_room", name="Host", countdown_seconds=1, anime_mode="marvel")
        host_session = (await self.receive(host, "room_joined"))["data"]
        code = host_session["room_code"]
        guest_session = await self.join(guest, code, "Guest")
        room = self.manager.rooms[code]

        await self.send(host, "toggle_ready")
        await self.receive(host, "room_state")
        await self.send(host, "start_game")
        stage = (await self.receive(host, "auction_started"))["data"]["room_state"]
        props = {"match_id": stage["match_id"], "round_id": stage["auction_character_count"]}
        await self.send(guest, "place_bid", amount=96, **props)
        self.assertEqual((await self.receive(guest, "bid_error"))["type"], "bid_error")
        await self.send(guest, "place_bid", amount=3, match_id=props["match_id"], round_id=0)
        await self.receive(guest, "bid_error")
        await asyncio.gather(self.send(host, "place_bid", amount=4, **props),
                             self.send(guest, "place_bid", amount=4, **props))
        bid = (await self.receive(host, "bid_success"))["data"]
        self.assertEqual(bid["current_bid"], 4)

        await host.close()
        thief = await self.socket()
        invalid = await self.resume(thief, {**host_session, "reconnect_token": guest_session["reconnect_token"]})
        self.assertEqual(invalid["type"], "resume_error")
        host = await self.socket()
        restored = (await self.resume(host, host_session))["data"]
        self.assertTrue(restored["is_host"])
        self.assertEqual(restored["room_state"]["current_bid"], 4)
        self.assertEqual(restored["room_state"]["timer_deadline"], bid["room_state"]["timer_deadline"])
        sold = (await self.receive(host, "auction_sold"))["data"]
        self.assertEqual(sold["remaining_purse"], 96)
        self.assertEqual(len(room.settlement_ledger), 1)

        for _ in range(15):
            lot = (await self.receive(host, "auction_started"))["data"]
            self.assertIn("stats", lot["character"])
            self.assertGreater(lot["character"]["power_rating"], 0)
            self.assertTrue(lot["character"]["description"])
            self.assertTrue(lot["character"]["techniques"])
            if lot["auction_round"] == 2:
                losing_socket = guest if sold["winner_id"] == host_session["session_id"] else host
                await self.send(losing_socket, "place_bid", amount=1, match_id=stage["match_id"], round_id=2)
                await self.receive(losing_socket, "bid_success")
            else:
                await asyncio.gather(self.send(host, "skip_character"), self.send(guest, "skip_character"))
        result = (await self.receive(host, "game_over"))["data"]
        self.assertEqual(len({entry["character_id"] for entry in room.settlement_ledger}), 16)
        self.assertEqual(sum(p.purse for p in room.players.values()), 195)
        self.assertEqual(result["battle_results"]["total_matches"], 1)
        self.assertIn("combat_mvp", result["battle_results"])

        await guest.close()
        guest = await self.socket()
        restored_guest = (await self.resume(guest, guest_session))["data"]
        self.assertEqual(restored_guest["finish_data"]["leaderboard"], result["leaderboard"])

        await self.send(host, "request_rematch")
        await self.receive(guest, "rematch_requested")
        await self.send(guest, "vote_rematch", accept=True)
        rematch = (await self.receive(host, "rematch_started"))["data"]["room_state"]
        self.assertEqual(rematch["match_number"], 2)
        self.assertTrue(all(p["purse"] == 100 and not p["team"] for p in rematch["players"]))

    async def test_eight_player_room_isolation_and_host_expiry(self):
        started_at = time.monotonic()
        sockets = await asyncio.gather(*(self.socket() for _ in range(10)))
        await self.send(sockets[0], "create_room")
        await self.send(sockets[8], "create_room", tournament_format="bracket")
        large, small = [
            (await self.receive(sockets[index], "room_joined"))["data"] for index in (0, 8)
        ]
        await asyncio.gather(*(self.join(ws, large["room_code"], f"Trainer {i}")
                               for i, ws in enumerate(sockets[1:8])))
        await self.join(sockets[9], small["room_code"], "Other room")
        await self.send(sockets[9], "start_game")
        await self.receive(sockets[9], "error")
        self.assertEqual(len(self.manager.rooms[large["room_code"]].players), 8)
        self.assertEqual(len(self.manager.rooms[small["room_code"]].players), 2)
        await sockets[0].close()
        await asyncio.sleep(server.RECONNECT_GRACE_SECONDS + 0.15)
        remaining = list(self.manager.rooms[large["room_code"]].players.values())
        self.assertEqual(len(remaining), 7)
        self.assertEqual(sum(player.is_host for player in remaining), 1)
        self.assertLess(time.monotonic() - started_at, 5)
