"""
Regression Tests: 4-Player Manual PvP & AI Tournament Flow
========================================================
Reproduces the bug where 4 players selecting Manual PvP skipped the battle
and jumped straight to Results, and verifies that:
- 4-player Manual PvP (round_robin & championship_bracket) runs interactive
  1v1 battles sequentially via LiveBattleSession.
- All clients receive battle_started and do NOT receive premature game_over.
- Players can submit battle actions and receive battle_action_ack.
- Results/game_over appear only after all scheduled matches complete.
- 2-player Manual PvP and 4-player AI vs AI remain unaffected.
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

import server as srv
from src.combat_data import CombatDataProvider


class TestFourPlayerManualPvP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provider = CombatDataProvider()

    def _run_4p_tournament(self, control_mode: str, tournament_format: str, expected_matches: int, expected_format: str):
        # Use a fast 1v1 team per player (1 weak vs 1 strong or 1v1 quick battle)
        # Note: Caterpie vs Caterpie or Pikachu vs Caterpie resolves in 1-2 turns!
        pika = dict(self.provider.pokemon_by_id[25])
        charizard = dict(self.provider.pokemon_by_id[6])
        mewtwo = dict(self.provider.pokemon_by_id[150])
        caterpie = dict(self.provider.pokemon_by_id[10])

        async def run():
            async with websockets.serve(srv.ws_handler, "127.0.0.1", 0) as ws_srv:
                port = ws_srv.sockets[0].getsockname()[1]
                uri = f"ws://127.0.0.1:{port}/ws"

                sids = ["pvp4_1", "pvp4_2", "pvp4_3", "pvp4_4"]
                names = ["Ash", "Misty", "Brock", "Gary"]
                conns = []
                for sid in sids:
                    conns.append(await websockets.connect(uri))

                code = None
                try:
                    # Create room as host
                    await conns[0].send(json.dumps({
                        "action": "create_room",
                        "data": {
                            "name": names[0],
                            "avatar": "red",
                            "session_id": sids[0],
                            "battle_control_mode": control_mode,
                            "tournament_format": tournament_format,
                        }
                    }))
                    joined0 = json.loads(await conns[0].recv())
                    self.assertEqual(joined0["type"], "room_joined")
                    code = joined0["data"]["room_code"]
                    sids[0] = joined0["data"]["session_id"]

                    for idx in range(1, 4):
                        await conns[idx].send(json.dumps({
                            "action": "join_room",
                            "data": {"room_code": code, "name": names[idx], "avatar": "blue", "session_id": sids[idx]}
                        }))
                        jmsg = json.loads(await conns[idx].recv())
                        self.assertEqual(jmsg["type"], "room_joined")
                        sids[idx] = jmsg["data"]["session_id"]

                    room = srv.room_manager.rooms[code]
                    # Simulate completed auction: assign 1 character to each player and exhaust pool
                    room.players[sids[0]].team = [pika]
                    room.players[sids[1]].team = [charizard]
                    room.players[sids[2]].team = [mewtwo]
                    room.players[sids[3]].team = [caterpie]
                    room.max_auction_characters = 0
                    room.auction_character_count = 0

                    # Run the post-auction battle phase directly via run_room_auction_loop
                    loop_task = asyncio.create_task(srv.run_room_auction_loop(room))

                    ws_by_sid = {sids[i]: conns[i] for i in range(4)}
                    battle_started_seen = {s: False for s in sids}
                    game_over_data = {}
                    premature_game_over = False
                    prompts_answered = 0
                    acks_received = 0

                    async def reader(sid, ws):
                        nonlocal premature_game_over, prompts_answered, acks_received
                        while True:
                            raw = await asyncio.wait_for(ws.recv(), timeout=25)
                            msg = json.loads(raw)
                            mtype = msg.get("type")
                            mdata = msg.get("data", {})
                            if mtype == "battle_started":
                                battle_started_seen[sid] = True
                            elif mtype == "battle_turn_prompt":
                                if not battle_started_seen[sid]:
                                    premature_game_over = True
                                # Submit first move
                                moves = mdata.get("available_moves") or []
                                if moves:
                                    best_move = max(moves, key=lambda m: m.get("power") or 0)
                                    await ws.send(json.dumps({
                                        "action": "submit_battle_action",
                                        "data": {
                                            "match_id": mdata.get("match_id"),
                                            "action_type": "attack",
                                            "move_id": best_move["id"],
                                        }
                                    }))
                                    prompts_answered += 1
                            elif mtype == "battle_action_ack":
                                acks_received += 1
                            elif mtype == "game_over":
                                if not battle_started_seen[sid]:
                                    premature_game_over = True
                                if control_mode == "player_vs_player" and prompts_answered == 0:
                                    premature_game_over = True
                                game_over_data[sid] = mdata
                                break

                    await asyncio.gather(*(reader(s, ws_by_sid[s]) for s in sids))
                    await loop_task

                    self.assertFalse(premature_game_over, "game_over arrived prematurely before battle!")
                    for s in sids:
                        self.assertTrue(battle_started_seen[s], f"{s} did not receive battle_started")
                        br = game_over_data[s]["battle_results"]
                        self.assertEqual(br["total_matches"], expected_matches)
                        self.assertEqual(br["format"], expected_format)

                    if control_mode == "player_vs_player":
                        self.assertGreater(prompts_answered, 0, "Manual PvP must prompt players")
                        self.assertGreater(acks_received, 0, "Manual PvP must acknowledge battle actions")
                finally:
                    for ws in conns:
                        await ws.close()
                    srv.room_manager.rooms.pop(code, None)

        asyncio.run(run())

    def test_01_four_player_manual_pvp_round_robin(self):
        """4 players in Manual PvP (round_robin) play all 6 interactive matches before game_over."""
        self._run_4p_tournament("player_vs_player", "round_robin", expected_matches=6, expected_format="round_robin")

    def test_02_four_player_manual_pvp_championship_bracket(self):
        """4 players in Manual PvP (championship_bracket) play 2 Semifinals + 1 Final before game_over."""
        self._run_4p_tournament("player_vs_player", "championship_bracket", expected_matches=3, expected_format="championship_bracket")

    def test_03_four_player_ai_vs_ai_unaffected(self):
        """4 players in AI vs AI mode still complete all 6 matches automatically."""
        self._run_4p_tournament("ai_vs_ai", "round_robin", expected_matches=6, expected_format="round_robin")


if __name__ == "__main__":
    unittest.main(verbosity=2)
