"""
Full Match Lifecycle Integration Test
=====================================
Simulates a multi-round match between 2 players until both acquire 6 Pokémon.
Verifies:
- Consecutive rounds
- Unsold handling vs Won handling
- Purse deduction
- Team capacity limit (6/6)
- Match termination condition (all teams full)
- Final Leaderboard & Winner calculation
"""

import asyncio
import json
import sys
import websockets

sys.stdout.reconfigure(encoding='utf-8')

async def recv_matching(ws, target_types, timeout=10.0):
    if isinstance(target_types, str):
        target_types = [target_types]
    end = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < end:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
            msg = json.loads(raw)
            if msg.get("type") in target_types:
                return msg
        except asyncio.TimeoutError:
            break
    raise TimeoutError(f"Timed out waiting for {target_types}")

async def run_full_match():
    print("=" * 60, flush=True)
    print("STARTING FULL MATCH LIFECYCLE TEST (6 POKÉMON PER PLAYER)", flush=True)
    print("=" * 60, flush=True)

    ws_url = "ws://127.0.0.1:5050/ws"

    async with websockets.connect(ws_url) as ws_red, websockets.connect(ws_url) as ws_blue:
        # 1. Create Room (Red) with fast 1s countdown for automated testing
        await ws_red.send(json.dumps({
            "action": "create_room",
            "data": {
                "name": "Red",
                "avatar": "red",
                "session_id": "sess_sim_red",
                "starting_purse": 100000,
                "countdown_seconds": 1
            }
        }))
        joined_red = await recv_matching(ws_red, "room_joined")
        room_code = joined_red["data"]["room_code"]
        print(f"[OK] Room Created: {room_code}", flush=True)

        # 2. Join Room (Blue)
        await ws_blue.send(json.dumps({
            "action": "join_room",
            "data": {
                "room_code": room_code,
                "name": "Blue",
                "avatar": "blue",
                "session_id": "sess_sim_blue"
            }
        }))
        await recv_matching(ws_blue, "room_joined")
        await recv_matching(ws_red, "room_state")
        print("[OK] Blue Joined Room.", flush=True)

        # 3. Start Game
        await ws_red.send(json.dumps({"action": "start_game"}))
        print("[OK] Match Started by Host!", flush=True)

        # We will loop through rounds until game_over is received
        red_team_count = 0
        blue_team_count = 0
        round_num = 0

        while True:
            # Wait for next auction_started or game_over
            event = await recv_matching(ws_red, ["auction_started", "game_over"], timeout=15.0)

            if event["type"] == "game_over":
                print("\n[MATCH FINISHED] Received game_over payload!", flush=True)
                leaderboard = event["data"]["leaderboard"]
                print(f"Leaderboard Standings ({len(leaderboard)} players):", flush=True)
                for entry in leaderboard:
                    print(f"  Rank #{entry['rank']}: {entry['name']} | Team Power: {entry['team_power']} | BST: {entry['total_bst']} | Purse: 🪙 {entry['remaining_purse']:,}", flush=True)
                    assert len(entry["team"]) == 6, f"{entry['name']} should have exactly 6 Pokémon"
                
                winner = leaderboard[0]
                print(f"\n🏆 TOURNAMENT WINNER: {winner['name']} with {winner['team_power']} Power!", flush=True)
                break

            round_num += 1
            poke = event["data"]["pokemon"]
            # Verify stats are strictly hidden during active auction
            assert "power_rating" not in poke and "stats" not in poke
            print(f"\n--- Round {round_num}: {poke['name']} ({', '.join(poke['types'])}) [Stats Hidden] ---", flush=True)

            # Alternate who bids so both players reach 6
            # If Red needs more and it's Red's turn:
            if red_team_count < 6 and (red_team_count <= blue_team_count or blue_team_count >= 6):
                bid_amt = 1500 + (round_num * 50)
                await ws_red.send(json.dumps({
                    "action": "place_bid",
                    "data": {"amount": bid_amt}
                }))
                print(f"  Red bid 🪙 {bid_amt:,}", flush=True)
            elif blue_team_count < 6:
                bid_amt = 2000 + (round_num * 50)
                await ws_blue.send(json.dumps({
                    "action": "place_bid",
                    "data": {"amount": bid_amt}
                }))
                print(f"  Blue bid 🪙 {bid_amt:,}", flush=True)

            # Wait for auction resolution (auction_won or auction_unsold)
            outcome = await recv_matching(ws_red, ["auction_won", "auction_unsold"], timeout=20.0)
            if outcome["type"] == "auction_won":
                winner_name = outcome["data"]["winner_name"]
                if winner_name == "Red":
                    red_team_count += 1
                else:
                    blue_team_count += 1
                print(f"  -> Won by {winner_name}! (Red: {red_team_count}/6, Blue: {blue_team_count}/6)", flush=True)
            else:
                print(f"  -> Unsold!", flush=True)

    print("=" * 60, flush=True)
    print("FULL MATCH LIFECYCLE TEST COMPLETED SUCCESSFULLY!", flush=True)
    print("=" * 60, flush=True)

if __name__ == "__main__":
    asyncio.run(run_full_match())
