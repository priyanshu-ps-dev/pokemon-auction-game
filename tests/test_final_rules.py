"""
Verification Suite for Finalized Pokémon Auction Rules & Team Ranking Logic
===========================================================================
Tests:
- Scenario 1: Full team (6 Pokémon, 2450 PR) loses to smaller team (4 Pokémon, 2890 PR).
- Scenario 2: Small elite team (3 Pokémon, 2700 PR) beats full team (6 Pokémon, 2500 PR).
- Scenario 3: Incomplete teams (6, 4, 2 Pokémon) when auction pool exhausted.
- Scenario 4: Equal Team Power tie-breaking rules applied without team size (BST -> Highest PR -> Purse -> Tie).
- Scenario 5: Dynamic auction pool validation for 2 through 8 players matches exact table.
- Scenario 6: End-to-end live match verifying dynamic pool locking, both sold/unsold counting, and automatic pool exhaustion termination.
"""

import asyncio
import json
import os
import sys
import websockets
import urllib.request

# Ensure project root in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

sys.stdout.reconfigure(encoding='utf-8')

from src.room_manager import (
    RoomManager, Room, Player, get_max_auction_pokemon,
    AUCTION_POOL_TABLE, TEAM_CAPACITY
)

WS_URL = "ws://127.0.0.1:5050/ws"
HTTP_URL = "http://127.0.0.1:5050"


def test_scenario_5_auction_pool_validation():
    print("\n--- TEST SCENARIO 5: Auction Pool Dynamic Validation (2–8 Players) ---")
    expected_table = {
        2: 16,
        3: 22,
        4: 29,
        5: 36,
        6: 43,
        7: 50,
        8: 57
    }
    for players, expected_pool in expected_table.items():
        calculated_pool = get_max_auction_pokemon(players)
        assert calculated_pool == expected_pool, f"Player count {players}: expected {expected_pool}, got {calculated_pool}"
        print(f"  [PASS] {players} Players -> Fixed Auction Pool: {calculated_pool} Pokémon (matches expected {expected_pool})")
    print("[PASS SCENARIO 5] All player pool sizes match specified dynamic formula & expected values.")


def test_scenario_1_full_team_loses_to_smaller():
    print("\n--- TEST SCENARIO 1: Full Team (6 Pokémon) Loses to Smaller Elite Team (4 Pokémon) ---")
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "pokemon_database.json")
    with open(db_path, "r", encoding="utf-8") as f:
        pokemon_db = json.load(f)

    mgr = RoomManager(pokemon_db)
    room = mgr.create_room(host_name="Player A", host_avatar="ash", session_id="sess_a", starting_purse=500)
    mgr.join_room(room.room_code, player_name="Player B", player_avatar="blue", session_id="sess_b")

    player_a = room.players["sess_a"]
    player_b = room.players["sess_b"]

    # Player A: 6 Pokemon with Combined Team Power = 2450 (e.g. 6 x 408.33)
    player_a.team = [
        {"id": 101 + i, "name": f"PokeA_{i}", "types": ["Normal"], "power_rating": 408.33, "stats": {"hp": 80, "total": 450}}
        for i in range(6)
    ]
    # Player B: 4 Pokemon with Combined Team Power = 2890 (e.g. 4 x 722.5)
    player_b.team = [
        {"id": 201 + i, "name": f"PokeB_{i}", "types": ["Dragon"], "power_rating": 722.5, "stats": {"hp": 100, "total": 600}}
        for i in range(4)
    ]

    leaderboard = mgr.calculate_final_leaderboard(room)
    assert len(leaderboard) == 2

    # Winner must be Player B despite only having 4 Pokemon!
    winner = leaderboard[0]
    runner_up = leaderboard[1]

    assert winner["name"] == "Player B"
    assert winner["pokemon_count"] == 4
    assert round(winner["team_power"]) == 2890

    assert runner_up["name"] == "Player A"
    assert runner_up["pokemon_count"] == 6
    assert round(runner_up["team_power"]) == 2450

    print(f"  [PASS] Rank #1: {winner['name']} ({winner['pokemon_count']}/6 Pokémon, Team Power {winner['team_power']})")
    print(f"  [PASS] Rank #2: {runner_up['name']} ({runner_up['pokemon_count']}/6 Pokémon, Team Power {runner_up['team_power']})")
    print("[PASS SCENARIO 1] Player B with 4 Pokémon defeated Player A with 6 Pokémon based strictly on Team Power.")


def test_scenario_2_small_elite_team():
    print("\n--- TEST SCENARIO 2: Small Elite Team (3 Pokémon, 2700 PR) vs Full Team (6 Pokémon, 2500 PR) ---")
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "pokemon_database.json")
    with open(db_path, "r", encoding="utf-8") as f:
        pokemon_db = json.load(f)

    mgr = RoomManager(pokemon_db)
    room = mgr.create_room(host_name="Elite Trainer", host_avatar="cynthia", session_id="sess_elite", starting_purse=500)
    mgr.join_room(room.room_code, player_name="Swarm Trainer", player_avatar="ash", session_id="sess_swarm")

    player_elite = room.players["sess_elite"]
    player_swarm = room.players["sess_swarm"]

    # Player A: 3 elite Pokemon with total 2700
    player_elite.team = [
        {"id": 301, "name": "Arceus", "types": ["Normal"], "power_rating": 900.0, "stats": {"hp": 120, "total": 720}},
        {"id": 302, "name": "Rayquaza", "types": ["Dragon", "Flying"], "power_rating": 900.0, "stats": {"hp": 105, "total": 680}},
        {"id": 303, "name": "Mewtwo", "types": ["Psychic"], "power_rating": 900.0, "stats": {"hp": 106, "total": 680}}
    ]

    # Player B: 6 common Pokemon with total 2500
    player_swarm.team = [
        {"id": 401 + i, "name": f"Pidgey_{i}", "types": ["Normal"], "power_rating": 416.67, "stats": {"hp": 60, "total": 400}}
        for i in range(6)
    ]

    leaderboard = mgr.calculate_final_leaderboard(room)
    winner = leaderboard[0]
    runner_up = leaderboard[1]

    assert winner["name"] == "Elite Trainer"
    assert winner["pokemon_count"] == 3
    assert round(winner["team_power"]) == 2700

    assert runner_up["name"] == "Swarm Trainer"
    assert runner_up["pokemon_count"] == 6
    assert round(runner_up["team_power"]) == 2500

    print(f"  [PASS] Rank #1: {winner['name']} ({winner['pokemon_count']}/6 Pokémon, Team Power {winner['team_power']})")
    print(f"  [PASS] Rank #2: {runner_up['name']} ({runner_up['pokemon_count']}/6 Pokémon, Team Power {runner_up['team_power']})")
    print("[PASS SCENARIO 2] Elite team with 3 Pokémon successfully beats full team of 6.")


def test_scenario_3_incomplete_teams():
    print("\n--- TEST SCENARIO 3: Incomplete Teams (6, 4, 2 Pokémon) Scored & Ranked ---")
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "pokemon_database.json")
    with open(db_path, "r", encoding="utf-8") as f:
        pokemon_db = json.load(f)

    mgr = RoomManager(pokemon_db)
    room = mgr.create_room(host_name="Player A", host_avatar="ash", session_id="p_a", starting_purse=500)
    mgr.join_room(room.room_code, player_name="Player B", player_avatar="blue", session_id="p_b")
    mgr.join_room(room.room_code, player_name="Player C", player_avatar="red", session_id="p_c")

    # Player A: 6 Pokemon, Power = 1800
    room.players["p_a"].team = [
        {"id": 501 + i, "name": f"Poke_{i}", "types": ["Normal"], "power_rating": 300.0, "stats": {"hp": 50, "total": 350}}
        for i in range(6)
    ]
    # Player B: 4 Pokemon, Power = 2400
    room.players["p_b"].team = [
        {"id": 601 + i, "name": f"Poke_{i}", "types": ["Water"], "power_rating": 600.0, "stats": {"hp": 90, "total": 550}}
        for i in range(4)
    ]
    # Player C: 2 Pokemon, Power = 1900
    room.players["p_c"].team = [
        {"id": 701 + i, "name": f"Poke_{i}", "types": ["Fire"], "power_rating": 950.0, "stats": {"hp": 110, "total": 680}}
        for i in range(2)
    ]

    leaderboard = mgr.calculate_final_leaderboard(room)
    assert len(leaderboard) == 3

    # Ranking must be: Player B (2400) -> Player C (1900) -> Player A (1800)
    assert leaderboard[0]["name"] == "Player B" and leaderboard[0]["team_power"] == 2400 and leaderboard[0]["pokemon_count"] == 4
    assert leaderboard[1]["name"] == "Player C" and leaderboard[1]["team_power"] == 1900 and leaderboard[1]["pokemon_count"] == 2
    assert leaderboard[2]["name"] == "Player A" and leaderboard[2]["team_power"] == 1800 and leaderboard[2]["pokemon_count"] == 6

    for entry in leaderboard:
        print(f"  [PASS] Rank #{entry['rank']}: {entry['name']} | Roster: {entry['team_size_display']} | Power: {entry['team_power']} | BST: {entry['total_bst']} | HP: {entry['total_hp']}")

    print("[PASS SCENARIO 3] Incomplete teams ranked accurately by Team Power without penalization.")


def test_scenario_4_equal_power_tiebreakers():
    print("\n--- TEST SCENARIO 4: Equal Team Power Tie-Breaking Rules ---")
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "pokemon_database.json")
    with open(db_path, "r", encoding="utf-8") as f:
        pokemon_db = json.load(f)

    mgr = RoomManager(pokemon_db)

    # 4A. Tie broken by combined BST
    room = mgr.create_room(host_name="Trainer One", host_avatar="ash", session_id="t1", starting_purse=500)
    mgr.join_room(room.room_code, player_name="Trainer Two", player_avatar="blue", session_id="t2")

    # Both have Team Power = 2000.0, but Trainer One has higher BST (1500 vs 1400)
    room.players["t1"].team = [
        {"id": 801, "name": "Poke1", "types": ["Electric"], "power_rating": 2000.0, "stats": {"hp": 100, "total": 1500}}
    ]
    # Trainer Two has 4 Pokemon (to prove team size is NOT used)
    room.players["t2"].team = [
        {"id": 802 + i, "name": f"Poke2_{i}", "types": ["Grass"], "power_rating": 500.0, "stats": {"hp": 50, "total": 350}}
        for i in range(4)
    ]
    # t2 total bst = 1400
    lb1 = mgr.calculate_final_leaderboard(room)
    assert lb1[0]["name"] == "Trainer One" and lb1[1]["name"] == "Trainer Two"
    print("  [PASS 4A] Tie-breaker 1: Higher BST wins (1500 vs 1400), team size ignored.")

    # 4B. Same BST -> Tie broken by highest individual Power Rating
    room2 = mgr.create_room(host_name="Trainer Alpha", host_avatar="ash", session_id="ta", starting_purse=500)
    mgr.join_room(room2.room_code, player_name="Trainer Beta", player_avatar="blue", session_id="tb")

    # Both have Power = 1000, BST = 1000.
    # Alpha has individual PR of 700 & 300.
    # Beta has individual PR of 500 & 500.
    room2.players["ta"].team = [
        {"id": 901, "name": "PokeA1", "types": ["Fire"], "power_rating": 700.0, "stats": {"hp": 100, "total": 600}},
        {"id": 902, "name": "PokeA2", "types": ["Fire"], "power_rating": 300.0, "stats": {"hp": 50, "total": 400}}
    ]
    room2.players["tb"].team = [
        {"id": 903, "name": "PokeB1", "types": ["Water"], "power_rating": 500.0, "stats": {"hp": 75, "total": 500}},
        {"id": 904, "name": "PokeB2", "types": ["Water"], "power_rating": 500.0, "stats": {"hp": 75, "total": 500}}
    ]
    lb2 = mgr.calculate_final_leaderboard(room2)
    assert lb2[0]["name"] == "Trainer Alpha" and lb2[1]["name"] == "Trainer Beta"
    print("  [PASS 4B] Tie-breaker 2: Higher individual PR wins (700 vs 500).")

    # 4C. Same Individual PR -> Tie broken by remaining purse
    room3 = mgr.create_room(host_name="Rich Trainer", host_avatar="ash", session_id="tr", starting_purse=500)
    mgr.join_room(room3.room_code, player_name="Poor Trainer", player_avatar="blue", session_id="tp")
    room3.players["tr"].purse = 350
    room3.players["tp"].purse = 100
    room3.players["tr"].team = [
        {"id": 910, "name": "PokeR", "types": ["Psychic"], "power_rating": 600.0, "stats": {"hp": 80, "total": 500}}
    ]
    room3.players["tp"].team = [
        {"id": 911, "name": "PokeP", "types": ["Psychic"], "power_rating": 600.0, "stats": {"hp": 80, "total": 500}}
    ]
    lb3 = mgr.calculate_final_leaderboard(room3)
    assert lb3[0]["name"] == "Rich Trainer" and lb3[1]["name"] == "Poor Trainer"
    print("  [PASS 4C] Tie-breaker 3: Higher remaining purse wins (₹350 vs ₹100).")

    # 4D. Still tied -> Declare exact same rank (Tie)
    room4 = mgr.create_room(host_name="Twin A", host_avatar="ash", session_id="twa", starting_purse=500)
    mgr.join_room(room4.room_code, player_name="Twin B", player_avatar="blue", session_id="twb")
    room4.players["twa"].purse = 200
    room4.players["twb"].purse = 200
    room4.players["twa"].team = [
        {"id": 920, "name": "Mew", "types": ["Psychic"], "power_rating": 600.0, "stats": {"hp": 100, "total": 600}}
    ]
    room4.players["twb"].team = [
        {"id": 921, "name": "Celebi", "types": ["Psychic", "Grass"], "power_rating": 600.0, "stats": {"hp": 100, "total": 600}}
    ]
    lb4 = mgr.calculate_final_leaderboard(room4)
    assert lb4[0]["rank"] == 1 and lb4[1]["rank"] == 1
    print("  [PASS 4D] All criteria identical -> Both declared Rank #1 (Tie). Team size never used.")

    print("[PASS SCENARIO 4] All tie-breaking rules verified in correct sequence without team size.")


async def test_scenario_6_live_auction_pool_exhaustion():
    print("\n--- TEST SCENARIO 6: Live Multiplayer Auction with Pool Exhaustion ---")
    async with websockets.connect(WS_URL) as ws_host, websockets.connect(WS_URL) as ws_p2:
        # Host creates room with 2 players -> Pool locked at 16 Pokemon!
        # Use fast 0.5s countdown
        await ws_host.send(json.dumps({
            "action": "create_room",
            "data": {"name": "Gary", "avatar": "blue", "session_id": "sess_live_gary", "countdown_seconds": 1}
        }))
        joined_host = json.loads(await ws_host.recv())
        room_code = joined_host["data"]["room_code"]

        await ws_p2.send(json.dumps({
            "action": "join_room",
            "data": {"room_code": room_code, "name": "Ash", "avatar": "ash", "session_id": "sess_live_ash"}
        }))
        await ws_p2.recv() # room_joined
        await ws_host.recv() # room_state

        # Start game
        await ws_host.send(json.dumps({"action": "start_game"}))

        # 2 players => pool must be locked to 16
        first_event = json.loads(await ws_host.recv())
        assert first_event["type"] == "auction_started"
        assert first_event["data"]["max_auction_pokemon"] == 16
        print(f"  [PASS] Fixed Auction Pool authoritative lock: {first_event['data']['max_auction_pokemon']} Pokémon.")

        # Let the rounds progress. Ash buys 1 Pokemon, Gary buys 1 Pokemon, others go unsold.
        round_count = 0
        game_over_event = None

        while True:
            raw = await asyncio.wait_for(ws_host.recv(), timeout=25.0)
            msg = json.loads(raw)
            mtype = msg.get("type")

            if mtype == "auction_started":
                round_count = msg["data"]["auction_round"]
                # Round 1: Gary bids
                if round_count == 1:
                    await ws_host.send(json.dumps({"action": "place_bid", "data": {"amount": 25}}))
                # Round 2: Ash bids
                elif round_count == 2:
                    await ws_p2.send(json.dumps({"action": "place_bid", "data": {"amount": 30}}))
                # Rest of rounds: nobody bids (unsold counts toward pool)

            elif mtype == "game_over":
                game_over_event = msg
                break

        assert game_over_event is not None
        assert game_over_event["data"]["finish_reason"] == "POOL_EXHAUSTED"
        assert round_count == 16
        leaderboard = game_over_event["data"]["leaderboard"]
        assert len(leaderboard) == 2

        print(f"  [PASS] Auction terminated immediately upon reaching pool limit of 16 Pokémon!")
        print(f"  [PASS] Finish Reason: {game_over_event['data']['finish_reason']}")
        for p in leaderboard:
            print(f"    Rank #{p['rank']}: {p['name']} | Team: {p['team_size_display']} | Team Power: {p['team_power']}")

    print("[PASS SCENARIO 6] Live match with pool exhaustion completed successfully!")


def main():
    print("=" * 75)
    print("STARTING COMPREHENSIVE VERIFICATION FOR FINAL AUCTION & RANKING RULES")
    print("=" * 75)

    test_scenario_5_auction_pool_validation()
    test_scenario_1_full_team_loses_to_smaller()
    test_scenario_2_small_elite_team()
    test_scenario_3_incomplete_teams()
    test_scenario_4_equal_power_tiebreakers()
    asyncio.run(test_scenario_6_live_auction_pool_exhaustion())

    print("\n" + "=" * 75)
    print("ALL 5 PROMPT SCENARIOS + LIVE MULTIPLAYER FLOW VERIFIED & PASSED!")
    print("=" * 75)


if __name__ == "__main__":
    main()
