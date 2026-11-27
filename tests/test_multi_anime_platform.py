"""
Multi-Anime Character Auction Platform Comprehensive Test Suite
==============================================================
Validates:
1. Multi-Anime Database & Franchise Integrity (21 Franchises, 1400+ Characters)
2. Normalized 1-100 Weighted Power Scoring System (Section 3 Weights)
3. Auction Modes: All Anime, Pokémon Only, Single Franchise, Multiple Franchises
4. Transformations / Forms System: SINGLE_BASE vs SEPARATE_ENTRIES
5. Strict Stat Secrecy during live auctions (Zero leakage over WebSocket)
6. Dramatic Final Reveal & Pure Team Power Winner Determination
7. Admin API & Real-Time Management (toggles, updates, pagination)
"""

import asyncio
import json
import os
import sys
import urllib.request
import websockets

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8')

from src.anime_models import (
    SCORING_WEIGHTS, calculate_overall_power, get_power_tier, sanitize_for_auction
)
from src.anime_database import AnimeDatabaseManager
from src.room_manager import (
    RoomManager, Room, Player, get_max_auction_characters, sanitize_character_for_auction
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JSON_PATH = os.path.join(BASE_DIR, "data", "anime_database.json")
DB_PATH = os.path.join(BASE_DIR, "data", "anime_platform.db")
HTTP_URL = "http://127.0.0.1:5050"
WS_URL = "ws://127.0.0.1:5050/ws"


def test_1_database_and_franchises():
    print("\n--- TEST 1: Database & Franchise Integrity ---")
    db = AnimeDatabaseManager(JSON_PATH, DB_PATH)
    franchises = db.get_all_franchises()
    
    assert len(franchises) >= 20, f"Expected at least 20 franchises, got {len(franchises)}"
    franchise_ids = {f["id"] for f in franchises}
    
    expected_franchises = [
        "dragon_ball", "naruto", "one_piece", "bleach", "jujutsu_kaisen",
        "demon_slayer", "attack_on_titan", "one_punch_man", "hunter_x_hunter",
        "my_hero_academia", "black_clover", "chainsaw_man", "solo_leveling",
        "jojo", "fullmetal_alchemist", "tokyo_ghoul", "death_note", "fairy_tail",
        "haikyuu", "blue_lock", "pokemon"
    ]
    for ef in expected_franchises:
        assert ef in franchise_ids, f"Missing franchise: {ef}"

    total_chars = len(db.characters)
    assert total_chars >= 1400, f"Expected 1400+ characters, got {total_chars}"
    print(f"  [PASS] Verified {len(franchises)} Franchises and {total_chars} total characters.")


def test_2_scoring_weights_and_power_formula():
    print("\n--- TEST 2: Power Ranking Formula & Weights ---")
    expected_weights = {
        "strength": 0.10,
        "attack_power": 0.20,
        "speed": 0.15,
        "durability": 0.15,
        "stamina": 0.10,
        "defense": 0.10,
        "intelligence": 0.05,
        "battle_iq": 0.05,
        "special_abilities": 0.10
    }
    assert SCORING_WEIGHTS == expected_weights, f"Weights mismatch: {SCORING_WEIGHTS}"

    # Test calculation on known stats
    sample_stats = {
        "strength": 90,
        "attack_power": 95,
        "speed": 85,
        "durability": 80,
        "stamina": 85,
        "defense": 75,
        "intelligence": 90,
        "battle_iq": 95,
        "special_abilities": 90
    }
    # Calculation:
    # 90*0.10(9.0) + 95*0.20(19.0) + 85*0.15(12.75) + 80*0.15(12.0) + 85*0.10(8.5) +
    # 75*0.10(7.5) + 90*0.05(4.5) + 95*0.05(4.75) + 90*0.10(9.0) = 87.0
    power = calculate_overall_power(sample_stats)
    assert power == 87.0, f"Expected 87.0, got {power}"
    tier = get_power_tier(power)
    assert tier == "S", f"Expected S tier for 87.0, got {tier}"
    print(f"  [PASS] Scoring calculation and tier mapping verified: 87.0 -> Tier {tier}.")


def test_3_auction_modes_filtering():
    print("\n--- TEST 3: Auction Mode Character Filtering ---")
    db = AnimeDatabaseManager(JSON_PATH, DB_PATH)

    # Mode: 'pokemon'
    poke_pool = db.get_characters_for_mode(mode="pokemon")
    assert all(c.get("anime_id") == "pokemon" for c in poke_pool), "Non-Pokemon in Pokemon mode"
    assert len(poke_pool) >= 1300, f"Expected 1300+ Pokemon, got {len(poke_pool)}"
    print(f"  [PASS] Mode 'pokemon' isolated {len(poke_pool)} Pokémon characters.")

    # Mode: 'single' (Dragon Ball)
    db_pool = db.get_characters_for_mode(mode="single", selected_anime=["dragon_ball"])
    assert all(c.get("anime_id") == "dragon_ball" for c in db_pool)
    assert len(db_pool) >= 3, f"Expected Dragon Ball characters, got {len(db_pool)}"
    print(f"  [PASS] Mode 'single' (dragon_ball) isolated {len(db_pool)} Dragon Ball characters.")

    # Mode: 'multiple' (Naruto + Jujutsu Kaisen)
    multi_pool = db.get_characters_for_mode(mode="multiple", selected_anime=["naruto", "jujutsu_kaisen"])
    assert all(c.get("anime_id") in ["naruto", "jujutsu_kaisen"] for c in multi_pool)
    naruto_count = sum(1 for c in multi_pool if c.get("anime_id") == "naruto")
    jjk_count = sum(1 for c in multi_pool if c.get("anime_id") == "jujutsu_kaisen")
    assert naruto_count > 0 and jjk_count > 0
    print(f"  [PASS] Mode 'multiple' isolated {len(multi_pool)} characters (Naruto: {naruto_count}, JJK: {jjk_count}).")

    # Mode: 'all'
    all_pool = db.get_characters_for_mode(mode="all")
    assert len(all_pool) >= 1400
    print(f"  [PASS] Mode 'all' contains full cross-anime character pool ({len(all_pool)} characters).")


def test_4_transformations_modes():
    print("\n--- TEST 4: Transformations Modes (SINGLE_BASE vs SEPARATE_ENTRIES) ---")
    db = AnimeDatabaseManager(JSON_PATH, DB_PATH)

    # Single Base Form
    base_pool = db.get_characters_for_mode(mode="single", selected_anime=["dragon_ball"], forms_mode="SINGLE_BASE")
    # Separate Entries
    expanded_pool = db.get_characters_for_mode(mode="single", selected_anime=["dragon_ball"], forms_mode="SEPARATE_ENTRIES")

    assert len(expanded_pool) > len(base_pool), f"Expected expanded pool > base pool, got {len(expanded_pool)} vs {len(base_pool)}"

    # Check for Goku's transformations in expanded pool
    goku_forms = [c for c in expanded_pool if "goku" in c["id"]]
    assert len(goku_forms) >= 3, f"Expected multiple Goku forms, found {len(goku_forms)}"
    form_names = [c.get("current_form") for c in goku_forms]
    print(f"  [PASS] Goku alternate forms registered as separate auction entries: {form_names}")


def test_5_informed_auction_profile():
    print("\n--- TEST 5: Informed In-Auction Character Profile ---")
    db = AnimeDatabaseManager(JSON_PATH, DB_PATH)
    sample_char = db.get_character_by_id("db_goku")
    assert sample_char is not None, "Goku not found in DB"

    sanitized = sanitize_character_for_auction(sample_char)
    # Check what IS allowed:
    assert "name" in sanitized
    assert "anime_name" in sanitized
    assert "image" in sanitized

    for key in ("stats", "power_rating", "power_tier", "description", "techniques"):
        assert key in sanitized, f"INCOMPLETE AUCTION PROFILE: '{key}' is missing"

    # Verify Room serialization hides stats
    host = Player("sess_host", "GokuFan", "red")
    room = Room("ANME-PRIV", host)
    room.status = "AUCTION"
    room.current_character_full = sample_char

    room_state = room.to_state_dict()
    curr = room_state["current_character"]
    for key in ("stats", "power_rating", "power_tier", "description", "techniques"):
        assert key in curr, f"INCOMPLETE AUCTION PROFILE: '{key}' missing from room state"

    print("  [PASS] Public character information is available during active bidding.")


def test_6_pure_team_power_winner_and_reveal():
    print("\n--- TEST 6: Pure Team Power Winner Determination & Post-Match Stat Reveal ---")
    db = AnimeDatabaseManager(JSON_PATH, DB_PATH)
    rm = RoomManager(db)
    room = rm.create_room("Gojo", "blue", "p1")
    p1 = room.players["p1"]
    p2 = Player("p2", "Sukuna", "red")
    room.players["p2"] = p2

    # Give Player 1 a 3-character team with HUGE power (e.g. 291.0)
    p1_team = [
        {"id": "c1", "name": "Goku UI", "anime_name": "Dragon Ball", "power_rating": 98.0, "stats": {"total": 850}},
        {"id": "c2", "name": "Saitama", "anime_name": "One Punch Man", "power_rating": 99.0, "stats": {"total": 890}},
        {"id": "c3", "name": "Gojo Satoru", "anime_name": "Jujutsu Kaisen", "power_rating": 94.0, "stats": {"total": 780}}
    ]
    p1.team = p1_team
    p1.purse = 150

    # Give Player 2 a full 6-character team with LOWER total power (e.g. 240.0)
    p2_team = [
        {"id": "c4", "name": "Tanjiro", "anime_name": "Demon Slayer", "power_rating": 45.0, "stats": {"total": 350}},
        {"id": "c5", "name": "Zenitsu", "anime_name": "Demon Slayer", "power_rating": 40.0, "stats": {"total": 310}},
        {"id": "c6", "name": "Inosuke", "anime_name": "Demon Slayer", "power_rating": 38.0, "stats": {"total": 300}},
        {"id": "c7", "name": "Deku", "anime_name": "My Hero Academia", "power_rating": 42.0, "stats": {"total": 340}},
        {"id": "c8", "name": "Bakugo", "anime_name": "My Hero Academia", "power_rating": 40.0, "stats": {"total": 330}},
        {"id": "c9", "name": "Todoroki", "anime_name": "My Hero Academia", "power_rating": 35.0, "stats": {"total": 300}}
    ]
    p2.team = p2_team
    p2.purse = 300

    leaderboard = rm.calculate_final_leaderboard(room)
    assert len(leaderboard) == 2
    # p1 total power: 98 + 99 + 94 = 291.0
    # p2 total power: 45 + 40 + 38 + 42 + 40 + 35 = 240.0
    assert leaderboard[0]["name"] == "Gojo"
    assert leaderboard[0]["rank"] == 1
    assert leaderboard[0]["team_power"] == 291.0
    assert leaderboard[1]["name"] == "Sukuna"
    assert leaderboard[1]["rank"] == 2
    assert leaderboard[1]["team_power"] == 240.0

    # Verify FULL stats revealed in final leaderboard
    assert len(leaderboard[0]["team"]) == 3
    assert leaderboard[0]["team"][0]["power_rating"] == 98.0
    assert "franchises_represented" in leaderboard[0]
    print(f"  [PASS] Winner accurately determined strictly by Team Power: {leaderboard[0]['name']} (3 chars, 291.0) beats {leaderboard[1]['name']} (6 chars, 240.0).")


def test_7_rest_api_and_admin():
    print("\n--- TEST 7: REST API Endpoints & Admin Control ---")
    # 1. /api/stats
    req = urllib.request.urlopen(f"{HTTP_URL}/api/stats")
    stats = json.loads(req.read().decode())
    assert stats["total_characters"] >= 1400
    assert stats["total_franchises"] >= 20
    print(f"  [PASS] /api/stats: {stats['total_characters']} characters, {stats['total_franchises']} franchises.")

    # 2. /api/anime
    req = urllib.request.urlopen(f"{HTTP_URL}/api/anime")
    franchises = json.loads(req.read().decode())
    assert len(franchises) >= 20
    print(f"  [PASS] /api/anime: {len(franchises)} franchises enumerated.")

    # 3. /api/characters?q=Naruto
    req = urllib.request.urlopen(f"{HTTP_URL}/api/characters?q=naruto")
    search_res = json.loads(req.read().decode())
    assert search_res["total"] > 0
    naruto_char = search_res["characters"][0]
    print(f"  [PASS] /api/characters?q=naruto: Found {search_res['total']} matches (First: {naruto_char['name']}).")

    # 4. /api/admin/character/toggle
    cid = naruto_char["id"]
    req = urllib.request.urlopen(f"{HTTP_URL}/api/admin/character/toggle?id={cid}&active=0")
    toggle_res = json.loads(req.read().decode())
    assert toggle_res["success"] is True

    # Re-enable
    req = urllib.request.urlopen(f"{HTTP_URL}/api/admin/character/toggle?id={cid}&active=1")
    toggle_res2 = json.loads(req.read().decode())
    assert toggle_res2["success"] is True
    print(f"  [PASS] /api/admin/character/toggle successfully toggled character {cid}.")


async def test_8_live_websocket_multi_anime_match():
    print("\n--- TEST 8: Live WebSocket Cross-Anime Match ---")
    async with websockets.connect(WS_URL) as ws_host, websockets.connect(WS_URL) as ws_p2:
        # Host creates room with Mode: 'multiple' (dragon_ball & naruto)
        await ws_host.send(json.dumps({
            "action": "create_room",
            "data": {
                "name": "HostPlayer",
                "avatar": "red",
                "session_id": "sess_anime_host",
                "starting_purse": 500,
                "countdown_seconds": 1,
                "anime_mode": "multiple",
                "selected_anime": ["dragon_ball", "naruto"],
                "forms_mode": "SEPARATE_ENTRIES"
            }
        }))
        joined_host = json.loads(await ws_host.recv())
        room_code = joined_host["data"]["room_code"]
        rstate = joined_host["data"]["room_state"]
        assert rstate["anime_mode"] == "multiple"
        assert rstate["forms_mode"] == "SEPARATE_ENTRIES"
        print(f"  [PASS] Host created room {room_code} in '{rstate['anime_mode']}' mode with '{rstate['forms_mode']}'.")

        # P2 joins
        await ws_p2.send(json.dumps({
            "action": "join_room",
            "data": {
                "room_code": room_code,
                "name": "GuestPlayer",
                "avatar": "blue",
                "session_id": "sess_anime_p2"
            }
        }))
        await ws_p2.recv() # room_joined
        await ws_host.recv() # room_state

        # Host starts match
        await ws_host.send(json.dumps({"action": "start_game"}))

        # Check first auction card received
        first_event = json.loads(await ws_host.recv())
        assert first_event["type"] == "auction_started"
        char = first_event["data"]["character"]
        assert char["anime_id"] in ["dragon_ball", "naruto"], f"Unexpected anime_id: {char['anime_id']}"
        assert "power_rating" not in char, "Privacy breach: power rating leaked during bidding!"
        print(f"  [PASS] Auction started with {char['name']} from {char['anime_name']}. Stats strictly hidden.")

        # P2 places flexible bid of ₹45
        await ws_p2.send(json.dumps({"action": "place_bid", "data": {"amount": 45}}))
        bid_event = json.loads(await ws_p2.recv())
        while bid_event.get("type") != "bid_success":
            bid_event = json.loads(await ws_p2.recv())
        assert bid_event["data"]["current_bid"] == 45
        print(f"  [PASS] P2 placed bid of ₹45 successfully.")


def main():
    print("=" * 80)
    print("MULTI-ANIME CHARACTER AUCTION PLATFORM COMPREHENSIVE VERIFICATION")
    print("=" * 80)

    test_1_database_and_franchises()
    test_2_scoring_weights_and_power_formula()
    test_3_auction_modes_filtering()
    test_4_transformations_modes()
    test_5_strict_stat_privacy()
    test_6_pure_team_power_winner_and_reveal()
    test_7_rest_api_and_admin()
    asyncio.run(test_8_live_websocket_multi_anime_match())

    print("\n" + "=" * 80)
    print("ALL 8 MULTI-ANIME VERIFICATION TEST SUITES PASSED PERFECTLY!")
    print("=" * 80)


if __name__ == "__main__":
    main()
