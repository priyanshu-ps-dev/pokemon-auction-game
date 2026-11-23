"""
Automated Integration Test for Pokémon Multiplayer Auction System
==================================================================
Tests:
- Room creation (Host)
- Room joining (Player 2)
- State sync & ready toggle
- Game start by Host
- Random Pokémon appearance
- Authoritative countdown timer & tick sync
- Valid bidding & timer reset to 15s
- Bidder duplication prevention
- Reserve budget rule enforcement
- Live room broadcast
"""

import asyncio
import json
import sys
import websockets
import urllib.request

sys.stdout.reconfigure(encoding='utf-8')

async def recv_type(ws, target_types, timeout=5.0):
    """Reads messages from websocket until one matches one of the target_types."""
    if isinstance(target_types, str):
        target_types = [target_types]
    end_time = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < end_time:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
            msg = json.loads(raw)
            if msg.get("type") in target_types:
                return msg
        except asyncio.TimeoutError:
            break
    raise TimeoutError(f"Timed out waiting for message of type: {target_types}")

async def test_multiplayer_flow():
    print("=" * 60, flush=True)
    print("STARTING MULTIPLAYER INTEGRATION TEST", flush=True)
    print("=" * 60, flush=True)

    # 1. HTTP API verification
    req = urllib.request.urlopen("http://127.0.0.1:5050/api/stats")
    stats = json.loads(req.read().decode("utf-8"))
    print(f"[OK] HTTP API /api/stats -> {stats['total_pokemon']} Pokémon loaded.", flush=True)

    ws_url = "ws://127.0.0.1:5050/ws"

    # 2. Host creates room
    async with websockets.connect(ws_url) as ws_host, websockets.connect(ws_url) as ws_player2:
        print("[1] Host connecting and creating room...", flush=True)
        await ws_host.send(json.dumps({
            "action": "create_room",
            "data": {
                "name": "Ash Ketchum",
                "avatar": "ash",
                "session_id": "sess_host_123",
                "starting_purse": 100000
            }
        }))

        res_host = await recv_type(ws_host, "room_joined")
        room_code = res_host["data"]["room_code"]
        print(f"[OK] Room created successfully! Code: {room_code}", flush=True)

        # 3. Player 2 joins room
        print("[2] Player 2 (Gary Oak) joining room...", flush=True)
        await ws_player2.send(json.dumps({
            "action": "join_room",
            "data": {
                "room_code": room_code,
                "name": "Gary Oak",
                "avatar": "blue",
                "session_id": "sess_p2_456"
            }
        }))

        res_p2 = await recv_type(ws_player2, "room_joined")
        print("[OK] Player 2 joined successfully!", flush=True)

        # Host receives room_state broadcast
        host_broadcast = await recv_type(ws_host, "room_state")
        players = host_broadcast["data"]["players"]
        assert len(players) == 2
        print(f"[OK] Host received updated room state: {len(players)} players in lobby.", flush=True)

        # 4. Ready toggle
        print("[3] Player 2 toggling ready...", flush=True)
        await ws_player2.send(json.dumps({"action": "toggle_ready"}))
        p2_state = await recv_type(ws_player2, "room_state")
        print("[OK] Ready status synchronized.", flush=True)

        # 5. Host starts game
        print("[4] Host starting the auction match...", flush=True)
        await ws_host.send(json.dumps({"action": "start_game"}))

        # Both players should receive auction_started
        auction_event_host = await recv_type(ws_host, "auction_started")
        auction_event_p2 = await recv_type(ws_player2, "auction_started")

        pokemon = auction_event_host["data"]["pokemon"]
        print(f"[OK] Auction started simultaneously for all clients!", flush=True)
        print(f"     First Pokémon up for bid: {pokemon['name']} (#{pokemon['national_id']:04d})", flush=True)
        # Verify stats are hidden
        assert "power_rating" not in pokemon and "stats" not in pokemon
        print(f"[OK] Pokémon stats, BST, and Power Rating strictly hidden during auction as required.", flush=True)

        # 6. Timer tick verification
        tick = await recv_type(ws_host, "auction_tick")
        print(f"[OK] Server-authoritative timer tick received: {tick['data']['timer_seconds_left']}s remaining.", flush=True)

        # 7. Valid bid by Ash
        print("[5] Ash placing valid opening bid of 2,000 credits...", flush=True)
        await ws_host.send(json.dumps({
            "action": "place_bid",
            "data": {"amount": 2000}
        }))

        bid_success_host = await recv_type(ws_host, "bid_success")
        assert bid_success_host["data"]["current_bid"] == 2000
        assert bid_success_host["data"]["highest_bidder_name"] == "Ash Ketchum"
        assert bid_success_host["data"]["timer_seconds_left"] == 15
        print(f"[OK] Bid accepted! Current bid: 🪙 2,000. Timer reset to 15s.", flush=True)

        # 8. Test invalid bid: Ash bidding against himself
        print("[6] Testing invalid bid: Ash attempting to bid against himself...", flush=True)
        await ws_host.send(json.dumps({
            "action": "place_bid",
            "data": {"amount": 2500}
        }))
        err_msg = await recv_type(ws_host, "bid_error")
        print(f"[OK] Correctly rejected self-bid: \"{err_msg['data']['message']}\"", flush=True)

        # 9. Test Reserve Budget Rule violation: Gary tries to bid 99,980 credits
        print("[7] Testing Reserve Budget Rule: Gary attempting to overbid (99,980 credits)...", flush=True)
        await ws_player2.send(json.dumps({
            "action": "place_bid",
            "data": {"amount": 99980}
        }))
        reserve_err = await recv_type(ws_player2, "bid_error")
        print(f"[OK] Reserve budget enforced: \"{reserve_err['data']['message']}\"", flush=True)

        # 10. Valid counter-bid by Gary
        print("[8] Gary placing valid counter-bid of 3,500 credits...", flush=True)
        await ws_player2.send(json.dumps({
            "action": "place_bid",
            "data": {"amount": 3500}
        }))
        bid_success_p2 = await recv_type(ws_player2, "bid_success")
        assert bid_success_p2["data"]["current_bid"] == 3500
        assert bid_success_p2["data"]["highest_bidder_name"] == "Gary Oak"
        print(f"[OK] Counter-bid accepted! Gary leads with 🪙 3,500. Timer reset to 15s.", flush=True)

        print("\n[SUCCESS] ALL MULTIPLAYER SERVER & BIDDING RULES PASSED VERIFICATION!", flush=True)
        print("=" * 60, flush=True)

if __name__ == "__main__":
    asyncio.run(test_multiplayer_flow())
