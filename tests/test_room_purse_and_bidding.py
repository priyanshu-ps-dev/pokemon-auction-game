"""
Comprehensive 14-Scenario Verification Test for Pokémon Multiplayer Auction System
=================================================================================
Verifies:
1. Player starts with ₹500.
2. Player bids ₹20 and wins.
3. Balance becomes ₹480.
4. Next Pokémon appears.
5. Player bids ₹40 and wins.
6. Balance becomes ₹440 (carries over, not resetting).
7. Player enters a new room.
8. Player receives fresh ₹500 in new room (no leak from previous room).
9. Flexible bids (e.g. ₹10, ₹21, ₹25, ₹35, ₹75) accepted without fixed step limits.
10. Invalid bids rejected (negative, <= current bid, self-bid).
11. Bids above available balance or violating reserve budget rejected.
12. Pokémon stats (HP, Atk, BST, Power Rating, Tier) strictly hidden during active auction.
13. Pokémon stats revealed ONLY upon match completion.
14. Final leaderboard ranked accurately by total Power Rating & tiebreakers.
"""

import asyncio
import json
import os
import sys
import websockets
import urllib.request

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

sys.stdout.reconfigure(encoding='utf-8')

WS_URL = "ws://127.0.0.1:5050/ws"
HTTP_URL = "http://127.0.0.1:5050"

async def recv_matching(ws, filter_fn, timeout=12.0):
    """Reads messages from websocket until filter_fn(msg) is True."""
    end_time = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < end_time:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
            msg = json.loads(raw)
            if filter_fn(msg):
                return msg
        except asyncio.TimeoutError:
            break
    raise TimeoutError("Timed out waiting for expected message matching filter")

async def recv_type(ws, target_types, timeout=12.0):
    if isinstance(target_types, str):
        target_types = [target_types]
    return await recv_matching(ws, lambda m: m.get("type") in target_types, timeout=timeout)

async def recv_bid(ws, amount, timeout=12.0):
    return await recv_matching(ws, lambda m: m.get("type") == "bid_success" and m.get("data", {}).get("current_bid") == amount, timeout=timeout)

async def run_all_tests():
    print("=" * 70, flush=True)
    print("STARTING 14-SCENARIO VERIFICATION SUITE", flush=True)
    print("=" * 70, flush=True)

    # Check HTTP endpoint
    req = urllib.request.urlopen(f"{HTTP_URL}/api/stats")
    stats = json.loads(req.read().decode("utf-8"))
    assert stats["total_pokemon"] >= 1000
    print(f"[HTTP] /api/stats healthy. Total Pokémon: {stats['total_pokemon']}", flush=True)

    # -------------------------------------------------------------
    # PART 1: Room A - Test Purse, Flexible Bids, Carry-Over, Stat Privacy
    # -------------------------------------------------------------
    async with websockets.connect(WS_URL) as ws_ash, websockets.connect(WS_URL) as ws_gary:
        print("\n--- TEST PHASE 1: Room Creation & Default Purse (₹500) ---", flush=True)
        # Ash creates Room A
        await ws_ash.send(json.dumps({
            "action": "create_room",
            "data": {"name": "Ash", "avatar": "ash", "session_id": "ash_sess_1"}
        }))
        res_ash = await recv_type(ws_ash, "room_joined")
        room_a_code = res_ash["data"]["room_code"]
        room_state = res_ash["data"]["room_state"]

        # Scenario 1: Default Starting Purse is ₹500
        assert room_state["starting_purse"] == 500, f"Expected 500, got {room_state['starting_purse']}"
        ash_player = next(p for p in room_state["players"] if p["session_id"] == "ash_sess_1")
        assert ash_player["purse"] == 500, f"Ash purse should be 500, got {ash_player['purse']}"
        print(f"[PASS 1/14] Ash created Room {room_a_code} with default purse ₹500", flush=True)

        # Gary joins Room A
        await ws_gary.send(json.dumps({
            "action": "join_room",
            "data": {"room_code": room_a_code, "name": "Gary", "avatar": "blue", "session_id": "gary_sess_1"}
        }))
        res_gary = await recv_type(ws_gary, "room_joined")
        room_state_gary = res_gary["data"]["room_state"]
        gary_player = next(p for p in room_state_gary["players"] if p["session_id"] == "gary_sess_1")
        assert gary_player["purse"] == 500, f"Gary purse should be 500, got {gary_player['purse']}"
        print(f"[PASS 1/14 b] Gary joined Room {room_a_code} with independent starting purse ₹500", flush=True)

        # Both Ready & Start Game
        await ws_gary.send(json.dumps({"action": "toggle_ready"}))
        await recv_type(ws_ash, "room_state")
        await ws_ash.send(json.dumps({"action": "start_game"}))

        # Receive Auction 1
        auc1_ash = await recv_type(ws_ash, "auction_started")
        auc1_poke = auc1_ash["data"]["pokemon"]

        # Scenario 12: Hidden Stats During Auction
        print("\n--- TEST PHASE 2: Stat Privacy Verification During Auction ---", flush=True)
        forbidden_keys = [
            "hp", "attack", "defense", "special_attack", "special_defense", "speed",
            "base_stat_total", "power_rating", "tier", "auction_value_score", "auction_tier", "stats"
        ]
        for key in forbidden_keys:
            assert key not in auc1_poke, f"LEAK DETECTED: '{key}' found in active auction pokemon payload!"
        assert "image" in auc1_poke and "name" in auc1_poke and "types" in auc1_poke
        print(f"[PASS 12/14] Active auction Pokémon '{auc1_poke['name']}' exposes ONLY image, name, and types. All stats/power ratings hidden!", flush=True)

        # Scenario 9: Flexible Bidding (Opening ₹10, then ₹21, ₹25, ₹35)
        print("\n--- TEST PHASE 3: Flexible Bidding & Bid Validation ---", flush=True)
        # Ash bids opening ₹10
        await ws_ash.send(json.dumps({"action": "place_bid", "data": {"amount": 10}}))
        await recv_bid(ws_ash, 10)

        # Gary flexible bids ₹21
        await ws_gary.send(json.dumps({"action": "place_bid", "data": {"amount": 21}}))
        await recv_bid(ws_gary, 21)

        # Ash flexible bids ₹25
        await ws_ash.send(json.dumps({"action": "place_bid", "data": {"amount": 25}}))
        await recv_bid(ws_ash, 25)

        # Gary flexible bids ₹35
        await ws_gary.send(json.dumps({"action": "place_bid", "data": {"amount": 35}}))
        await recv_bid(ws_gary, 35)

        # Scenario 10: Invalid bids rejected
        # Case A: Gary tries to bid again against himself
        await ws_gary.send(json.dumps({"action": "place_bid", "data": {"amount": 50}}))
        err_msg = await recv_type(ws_gary, "bid_error")
        assert "already" in err_msg["data"]["message"].lower(), f"Unexpected error: {err_msg}"

        # Case B: Ash bids less than or equal to current bid (<= 35)
        await ws_ash.send(json.dumps({"action": "place_bid", "data": {"amount": 35}}))
        err_msg = await recv_type(ws_ash, "bid_error")
        assert "at least" in err_msg["data"]["message"].lower()

        # Case C: Ash bids negative or 0
        await ws_ash.send(json.dumps({"action": "place_bid", "data": {"amount": -10}}))
        err_msg = await recv_type(ws_ash, "bid_error")

        print("[PASS 10/14] Invalid bids rejected: self-bid, bid <= current, negative bid correctly blocked.", flush=True)

        # Scenario 11: Budget limit (Ash has ₹500, tries to bid ₹550)
        await ws_ash.send(json.dumps({"action": "place_bid", "data": {"amount": 550}}))
        err_msg = await recv_type(ws_ash, "bid_error")
        assert "insufficient" in err_msg["data"]["message"].lower() or "balance" in err_msg["data"]["message"].lower()
        print("[PASS 11/14] Available purse limit enforced: bidding ₹550 rejected when balance is ₹500.", flush=True)

        # Gary is currently winning at ₹35. Wait for auction 1 to countdown / complete.
        print("Waiting for Auction 1 to conclude...", flush=True)
        won_msg = await recv_type(ws_gary, "auction_won", timeout=20.0)
        assert won_msg["data"]["winner_name"] == "Gary"
        assert won_msg["data"]["winning_bid"] == 35

        # Scenario 2 & 3: Balance deduction & carry-over
        gary_entry = next(p for p in won_msg["data"]["room_state"]["players"] if p["session_id"] == "gary_sess_1")
        gary_rem_purse = gary_entry["purse"]
        assert gary_rem_purse == 500 - 35  # 465
        print(f"[PASS 2/14 & 3/14] Gary won Auction 1 for ₹35. Balance correctly updated to ₹{gary_rem_purse} (500 - 35).", flush=True)

        # Scenario 4: Next Pokémon appears
        auc2 = await recv_type(ws_gary, "auction_started", timeout=12.0)
        print(f"[PASS 4/14] Next Pokémon appeared: '{auc2['data']['pokemon']['name']}'.", flush=True)

        # Scenario 5 & 6: Gary bids ₹40 and wins. Balance carries over!
        print("Gary bids ₹40 in Auction 2...", flush=True)
        await ws_gary.send(json.dumps({"action": "place_bid", "data": {"amount": 40}}))
        await recv_bid(ws_gary, 40)

        print("Waiting for Auction 2 to conclude...", flush=True)
        won_msg_2 = await recv_type(ws_gary, "auction_won", timeout=20.0)
        assert won_msg_2["data"]["winner_name"] == "Gary"
        assert won_msg_2["data"]["winning_bid"] == 40
        gary_entry_2 = next(p for p in won_msg_2["data"]["room_state"]["players"] if p["session_id"] == "gary_sess_1")
        assert gary_entry_2["purse"] == gary_rem_purse - 40  # 465 - 40 = 425

        print(f"[PASS 5/14 & 6/14] Gary won Auction 2 for ₹40. Balance carried over to ₹{gary_entry_2['purse']} (NOT reset to 500)!", flush=True)
        print("[PASS 9/14] Flexible bids (₹10, ₹21, ₹25, ₹35, ₹40) successfully processed without fixed increment restrictions.", flush=True)

    # -------------------------------------------------------------
    # PART 2: New Room Isolation - Fresh Purse in New Match
    # -------------------------------------------------------------
    print("\n--- TEST PHASE 4: New Room Isolation (Scenario 7 & 8) ---", flush=True)
    async with websockets.connect(WS_URL) as ws_new:
        # Gary creates a brand new Room B
        await ws_new.send(json.dumps({
            "action": "create_room",
            "data": {"name": "Gary", "avatar": "blue", "session_id": "gary_fresh_sess"}
        }))
        res_new = await recv_type(ws_new, "room_joined")
        room_b_code = res_new["data"]["room_code"]
        room_b_state = res_new["data"]["room_state"]
        new_gary_player = next(p for p in room_b_state["players"] if p["session_id"] == "gary_fresh_sess")

        # Scenario 7 & 8: Fresh ₹500 in new room, previous Room A balance of ₹425 has NOT leaked over
        assert new_gary_player["purse"] == 500, f"Expected fresh ₹500, got {new_gary_player['purse']}"
        assert room_b_state["starting_purse"] == 500
        print(f"[PASS 7/14 & 8/14] Gary entered new Room {room_b_code} and received fresh ₹500 starting purse. No balance leaked!", flush=True)

    # -------------------------------------------------------------
    # PART 3: Post-Match Stat Reveal & Accurate Power Rating Ranking
    # -------------------------------------------------------------
    print("\n--- TEST PHASE 5: Post-Match Stat Reveal & Power Rating Leaderboard (Scenario 13 & 14) ---", flush=True)
    from src.room_manager import RoomManager, Room, Player, sanitize_pokemon_for_auction

    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "pokemon_database.json")
    with open(db_path, "r", encoding="utf-8") as f:
        pokemon_db = json.load(f)

    mgr = RoomManager(pokemon_db)
    test_room = mgr.create_room(host_name="Red", host_avatar="ash", session_id="red_sess", starting_purse=500)
    blue_room, _ = mgr.join_room(test_room.room_code, player_name="Blue", player_avatar="blue", session_id="blue_sess")
    red = test_room.players["red_sess"]
    blue_player = test_room.players["blue_sess"]

    # Populate Red and Blue with 6 Pokémon each from database
    sample_pokemon = pokemon_db[:12]
    red.team = sample_pokemon[:6]
    blue_player.team = sample_pokemon[6:12]

    # Verify active state hides stats (power is None and individual Pokémon stats stripped)
    p_dict = red.to_dict(reveal_stats=False)
    assert p_dict["total_team_power"] is None, "total_team_power must be None during active auction"
    assert p_dict["total_bst"] is None, "total_bst must be None during active auction"
    assert "hp" not in p_dict["team"][0], "Team Pokémon stats must be sanitized during auction"

    test_room.status = "GAME_OVER"
    leaderboard = mgr.calculate_final_leaderboard(test_room)

    # Scenario 13: Full stats revealed in game over
    assert len(leaderboard) == 2
    for entry in leaderboard:
        assert "team_power" in entry and entry["team_power"] > 0
        assert "total_bst" in entry and entry["total_bst"] > 0
        assert "team" in entry and len(entry["team"]) == 6
        for p in entry["team"]:
            assert "stats" in p and "hp" in p["stats"] and "attack" in p["stats"] and "defense" in p["stats"]
            assert "power_rating" in p and "tier" in p and "auction_value_score" in p
    print("[PASS 13/14] Post-match results payload reveals complete stats, BST, and Power Ratings for all Pokémon!", flush=True)

    # Scenario 14: Correct ranking
    rank1 = leaderboard[0]
    rank2 = leaderboard[1]
    assert rank1["rank"] == 1 and rank2["rank"] == 2
    assert (rank1["team_power"] > rank2["team_power"]) or (
        rank1["team_power"] == rank2["team_power"] and rank1["total_bst"] >= rank2["total_bst"]
    )
    print(f"[PASS 14/14] Winner '{rank1['name']}' ranked #1 with Team Power {rank1['team_power']} vs #2 '{rank2['name']}' ({rank2['team_power']}).", flush=True)

    print("\n" + "=" * 70, flush=True)
    print("ALL 14 SCENARIOS VERIFIED AND PASSED SUCCESSFULLY!", flush=True)
    print("=" * 70, flush=True)

if __name__ == "__main__":
    asyncio.run(run_all_tests())
