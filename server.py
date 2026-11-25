"""
Multi-Anime Character & Pokémon Auction Local HTTP Server & Real-Time Multiplayer Engine
=======================================================================================
Unified server handling:
- Static file serving (Pokédex & Cross-Anime Multiplayer Arena)
- Multi-Anime REST API (/api/anime, /api/characters, /api/stats, /api/pokemon)
- Real-time WebSocket rooms (/ws) with authoritative timers and flexible bidding
- Room-isolated purse management (Default ₹500)
- Hidden competitive stats during auction & dramatic final cross-anime reveal
- 5 Game Modes: All Anime, Pokémon Only, Single Franchise, Multiple Franchises, Custom Pool
- Transformations Modes: SINGLE_BASE vs SEPARATE_ENTRIES
"""

import os
import sys
import json
import asyncio
import mimetypes
import time
from typing import Any
from urllib.parse import urlparse, parse_qs, unquote

from websockets.asyncio.server import serve, ServerConnection, Response
from websockets.http11 import Headers
from websockets.exceptions import ConnectionClosed

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PUBLIC_DIR = os.path.join(BASE_DIR, "public")
DATA_DIR = os.path.join(BASE_DIR, "data")
POKEMON_JSON_PATH = os.path.join(DATA_DIR, "pokemon_database.json")
ANIME_JSON_PATH = os.path.join(DATA_DIR, "anime_database.json")
ANIME_DB_PATH = os.path.join(DATA_DIR, "anime_platform.db")

# Import database manager & avatar generator
from src.anime_database import AnimeDatabaseManager
from src.avatar_generator import generate_character_svg
from src.battle_manager import BattleManager
from src.live_battle_session import LiveBattleSession
from src.player_profiles import PlayerProfileStore
anime_db = AnimeDatabaseManager(ANIME_JSON_PATH, ANIME_DB_PATH)
battle_manager = BattleManager()
profile_store = PlayerProfileStore()

# Legacy compatibility cache
with open(POKEMON_JSON_PATH, "r", encoding="utf-8") as f:
    POKEMON_DATABASE = json.load(f)
POKEMON_BY_ID = {p["id"]: p for p in POKEMON_DATABASE}

# Import room manager
from src.room_manager import (
    RoomManager, Room, Player, TEAM_CAPACITY,
    AUCTION_COUNTDOWN_SECONDS, DEFAULT_STARTING_PURSE, OPENING_MIN_BID,
    sanitize_character_for_auction, sanitize_pokemon_for_auction,
    get_max_auction_characters, get_max_auction_pokemon
)

room_manager = RoomManager(anime_db)
PORT = 5050

# Map of room_code -> active auction asyncio.Task
room_auction_tasks: dict[str, asyncio.Task] = {}


async def broadcast_to_room(room: Room, message_type: str, data: dict):
    """Broadcasts a JSON message to all connected clients in a room."""
    payload = json.dumps({"type": message_type, "data": data}, ensure_ascii=False)
    for p in list(room.players.values()) + list(room.spectators.values()):
        if p.ws is not None:
            try:
                await p.ws.send(payload)
            except Exception:
                pass


async def run_room_auction_loop(room: Room):
    """
    Server-authoritative auction loop for a match.
    Runs until either:
    Condition A: All active players have reached maximum capacity of 6 characters (room.all_teams_full).
    Condition B: Fixed auction character pool has been exhausted (room.auction_character_count >= room.max_auction_characters).
    Condition C: Less than 2 active players remain (due to withdrawals).

    Both sold and unsold characters count toward the auction limit.
    """
    try:
        finish_reason = "POOL_EXHAUSTED"
        while not room.all_teams_full and room.auction_character_count < room.max_auction_characters:
            active_remaining = [p for p in room.players.values() if not p.is_withdrawn]
            if len(active_remaining) < 2:
                finish_reason = "PLAYERS_WITHDRAWN"
                break

            # 1. Select next random character (full data held on server)
            next_char = room_manager.select_random_character(room)
            if not next_char:
                break

            # Reset per-round skips and initialize skip event
            room.skipped_player_ids.clear()
            for p in room.players.values():
                p.has_skipped = False
            room.skip_event = asyncio.Event()

            # Both sold and unsold count toward the auction limit
            room.auction_character_count += 1
            room.status = "AUCTION"
            room.current_character_full = next_char
            room.current_bid = 0
            room.highest_bidder_id = None
            room.timer_seconds_left = room.countdown_seconds
            room.timer_end_timestamp = time.time() + room.countdown_seconds

            sanitized_char = room.current_character_sanitized

            # Broadcast ONLY sanitized character (Artwork, Name, Anime, Form)
            await broadcast_to_room(room, "auction_started", {
                "character": sanitized_char,
                "pokemon": sanitized_char,  # Legacy backwards compatibility
                "auction_round": room.auction_character_count,
                "max_auction_pokemon": room.max_auction_characters,
                "max_auction_characters": room.max_auction_characters,
                "room_state": room.to_state_dict()
            })

            # Check if all eligible players skipped immediately (e.g. all full)
            if room.all_eligible_players_skipped():
                room.skip_event.set()

            # 2. Server-authoritative countdown loop
            while True:
                active_now = [p for p in room.players.values() if not p.is_withdrawn]
                if len(active_now) < 2:
                    finish_reason = "PLAYERS_WITHDRAWN"
                    break

                now = time.time()
                remaining = room.timer_end_timestamp - now
                room.timer_seconds_left = max(0, int(round(remaining)))

                highest_bidder_name = None
                highest_bidder_avatar = None
                if room.highest_bidder_id and room.highest_bidder_id in room.players:
                    p = room.players[room.highest_bidder_id]
                    highest_bidder_name = p.name
                    highest_bidder_avatar = p.avatar

                await broadcast_to_room(room, "auction_tick", {
                    "timer_seconds_left": room.timer_seconds_left,
                    "current_bid": room.current_bid,
                    "highest_bidder_id": room.highest_bidder_id,
                    "highest_bidder_name": highest_bidder_name,
                    "highest_bidder_avatar": highest_bidder_avatar
                })

                if remaining <= 0 or (room.skip_event and room.skip_event.is_set()):
                    break

                try:
                    await asyncio.wait_for(room.skip_event.wait(), timeout=1.0)
                    break
                except asyncio.TimeoutError:
                    pass

            if len(active_now) < 2:
                break

            # 3. ATOMIC & IDEMPOTENT AUCTION RESOLUTION
            async with room.auction_lock:
                settlement = room.settle_current_round(room.auction_character_count)

            if settlement and settlement["status"] == "SOLD":
                winner = settlement["winner"]
                winning_bid = settlement["winning_bid"]
                sold_data = {
                    "settlement_id": settlement["settlement_id"],
                    "round_id": settlement["round_id"],
                    "winner_id": winner.session_id,
                    "winner_name": winner.name,
                    "winning_bid": winning_bid,
                    "character": settlement["character"],
                    "pokemon": settlement["character"],
                    "remaining_purse": winner.purse,
                    "team_count": winner.team_count,
                    "room_state": room.to_state_dict()
                }
                await broadcast_to_room(room, "auction_sold", sold_data)
                await broadcast_to_room(room, "auction_won", sold_data)
            elif settlement:
                await broadcast_to_room(room, "auction_unsold", {
                    "settlement_id": settlement["settlement_id"],
                    "round_id": settlement["round_id"],
                    "character": settlement["character"],
                    "pokemon": settlement["character"],
                    "consecutive_unsold": room.consecutive_unsold_count,
                    "room_state": room.to_state_dict()
                })

            # Check if match should end now
            active_remaining = [p for p in room.players.values() if not p.is_withdrawn]
            if len(active_remaining) < 2:
                finish_reason = "PLAYERS_WITHDRAWN"
                break

            if room.all_teams_full:
                finish_reason = "ALL_TEAMS_FULL"
                break

            if room.auction_character_count >= room.max_auction_characters:
                finish_reason = "POOL_EXHAUSTED"
                break

            # Brief intermission before next character
            room.status = "SHOWCASE"
            await broadcast_to_room(room, "room_state", room.to_state_dict())
            await asyncio.sleep(2.5)

        # 4. AUCTION COMPLETE -> BATTLE SIMULATION -> FINAL LEADERBOARD
        room.status = "BATTLE"
        await broadcast_to_room(room, "battle_started", {
            "match_id": room.match_id,
            "finish_reason": finish_reason,
            "battle_control_mode": room.battle_control_mode,
            "tournament_format": room.tournament_format,
            "room_state": room.to_state_dict()
        })

        active_players = [p for p in room.players.values() if not p.is_withdrawn]
        if room.battle_control_mode in ("player_vs_ai", "player_vs_player") and len(active_players) == 2:
            pa, pb = active_players[0], active_players[1]
            built_a = [battle_manager.build_combatant(c)[1] for c in pa.team]
            built_b = [battle_manager.build_combatant(c)[1] for c in pb.team]
            current_match_id = room.match_id
            images_map = {
                str(c.get("id", "")): c.get("image", "")
                for c in (pa.team + pb.team)
            }
            live_sess = LiveBattleSession(
                pa.session_id, built_a,
                pb.session_id, built_b,
                control_mode=room.battle_control_mode,
                images_by_id=images_map,
                match_id=current_match_id,
            )
            room.active_live_battle = live_sess

            async def _send_prompt(pid: str, prompt_data: dict):
                if room.match_id != current_match_id or live_sess.is_invalidated:
                    return
                pl = room.players.get(pid)
                if pl and pl.ws is not None:
                    try:
                        enriched = dict(prompt_data)
                        enriched["player_a_name"] = pa.name
                        enriched["player_b_name"] = pb.name
                        await pl.ws.send(json.dumps({"type": "battle_turn_prompt", "data": enriched}, ensure_ascii=False))
                    except Exception:
                        pass

            async def _broadcast_turn(turn_entry: dict):
                if room.match_id != current_match_id or live_sess.is_invalidated:
                    return
                await broadcast_to_room(room, "battle_turn_resolved", {
                    "match_id": current_match_id,
                    "player_a_name": pa.name,
                    "player_b_name": pb.name,
                    "turn_entry": turn_entry,
                })

            res = await live_sess.run_interactive(send_prompt=_send_prompt, broadcast_turn=_broadcast_turn)
            room.active_live_battle = None
            if live_sess.is_invalidated or room.match_id != current_match_id:
                return

            # Build authoritative battle_results directly from the interactive session outcome
            a_wins = 1 if res.winner_id == pa.session_id else 0
            b_wins = 1 if res.winner_id == pb.session_id else 0
            draws = 1 if (res.is_draw or res.winner_id is None) else 0
            standings = []
            for p, w, l, hp in (
                (pa, a_wins, b_wins, res.player_a_remaining_hp),
                (pb, b_wins, a_wins, res.player_b_remaining_hp),
            ):
                standings.append({
                    "session_id": p.session_id,
                    "name": p.name,
                    "avatar": p.avatar,
                    "is_withdrawn": p.is_withdrawn,
                    "wins": w,
                    "losses": l,
                    "draws": draws,
                    "points": (w * 3) + draws,
                    "remaining_hp_total": hp,
                    "matches_played": 1,
                    "team_count": len(p.team),
                })
            for wp in room.players.values():
                if wp.is_withdrawn:
                    standings.append({
                        "session_id": wp.session_id,
                        "name": wp.name,
                        "avatar": wp.avatar,
                        "is_withdrawn": True,
                        "wins": 0, "losses": 0, "draws": 0, "points": 0,
                        "remaining_hp_total": 0, "matches_played": 0, "team_count": len(wp.team),
                    })
            standings.sort(key=lambda s: (not s["is_withdrawn"], s["points"], s["wins"], s["remaining_hp_total"]), reverse=True)
            for r_idx, s in enumerate(standings, start=1):
                s["rank"] = r_idx

            battle_results = {
                "format": "direct_1v1",
                "match_id": current_match_id,
                "total_matches": 1,
                "standings": standings,
                "champion": standings[0] if standings else None,
                "matches": [{
                    "player_a_id": pa.session_id,
                    "player_a_name": pa.name,
                    "player_b_id": pb.session_id,
                    "player_b_name": pb.name,
                    "player_a_team": [{"id": str(c.get("id", "")), "name": c.get("name", ""), "image": c.get("image", "")} for c in pa.team],
                    "player_b_team": [{"id": str(c.get("id", "")), "name": c.get("name", ""), "image": c.get("image", "")} for c in pb.team],
                    "winner_id": res.winner_id,
                    "is_draw": res.is_draw,
                    "reason": res.reason,
                    "turns_played": res.turns_played,
                    "seed": res.seed,
                    "player_a_remaining_hp": res.player_a_remaining_hp,
                    "player_b_remaining_hp": res.player_b_remaining_hp,
                    "turn_log": res.turn_log,
                }],
                "bracket": None,
            }
        else:
            battle_results = await battle_manager.run_tournament_async(
                list(room.players.values()),
                match_id=room.match_id,
                tournament_format=room.tournament_format
            )

        room.battle_results = battle_results
        profile_store.record_tournament_results(battle_results)

        for idx, m in enumerate(battle_results.get("matches", []), start=1):
            await broadcast_to_room(room, "battle_progress", {
                "match_index": idx,
                "total_matches": battle_results.get("total_matches", 0),
                "player_a_id": m["player_a_id"],
                "player_a_name": m["player_a_name"],
                "player_b_id": m["player_b_id"],
                "player_b_name": m["player_b_name"],
                "winner_id": m["winner_id"],
                "is_draw": m["is_draw"],
                "reason": m["reason"],
                "turns_played": m["turns_played"]
            })

        await broadcast_to_room(room, "battle_results", {
            "match_id": room.match_id,
            "format": battle_results.get("format"),
            "champion": battle_results.get("champion"),
            "standings": battle_results.get("standings", []),
            "total_matches": battle_results.get("total_matches", 0)
        })

        room.status = "GAME_OVER"
        leaderboard = room_manager.calculate_battle_leaderboard(room, battle_results)

        finish_data = {
            "leaderboard": leaderboard,
            "winner": leaderboard[0] if leaderboard else None,
            "battle_results": battle_results,
            "room_state": room.to_state_dict(),
            "finish_reason": finish_reason
        }
        await broadcast_to_room(room, "match_finished", finish_data)
        await broadcast_to_room(room, "game_over", finish_data)

    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"[AuctionLoopError] room={room.room_code} match={room.match_id} round={room.auction_character_count}: {e}")
        await broadcast_to_room(room, "room_event", {
            "message": f"Auction loop encountered an error in round {room.auction_character_count}: {e}"
        })


async def ws_handler(websocket: ServerConnection):
    """Handles incoming WebSocket connection."""
    client_session_id = None
    client_room_code = None

    try:
        async for raw_msg in websocket:
            try:
                msg = json.loads(raw_msg)
            except json.JSONDecodeError:
                continue

            action = msg.get("action")
            data = msg.get("data", {})

            # 1. CREATE ROOM
            if action == "create_room":
                host_name = data.get("name", "Trainer Red").strip() or "Trainer Red"
                host_avatar = data.get("avatar", "red")
                session_id = data.get("session_id", "")
                starting_purse = int(data.get("starting_purse", DEFAULT_STARTING_PURSE))
                countdown_seconds = int(data.get("countdown_seconds", AUCTION_COUNTDOWN_SECONDS))
                min_bid = int(data.get("min_bid", OPENING_MIN_BID))
                anime_mode = data.get("anime_mode", "all")
                selected_anime = data.get("selected_anime", [])
                forms_mode = data.get("forms_mode", "SINGLE_BASE")
                battle_control_mode = data.get("battle_control_mode", "ai_vs_ai")
                tournament_format = data.get("tournament_format", "round_robin")

                room = room_manager.create_room(
                    host_name, host_avatar, session_id,
                    starting_purse=starting_purse,
                    countdown_seconds=countdown_seconds,
                    min_bid=min_bid,
                    anime_mode=anime_mode,
                    selected_anime=selected_anime,
                    forms_mode=forms_mode,
                    battle_control_mode=battle_control_mode,
                    tournament_format=tournament_format
                )
                client_room_code = room.room_code
                client_session_id = session_id
                player = room.players[session_id]
                player.ws = websocket

                await websocket.send(json.dumps({
                    "type": "room_joined",
                    "data": {
                        "room_code": room.room_code,
                        "session_id": session_id,
                        "is_host": True,
                        "room_state": room.to_state_dict()
                    }
                }))

            # 2. JOIN ROOM
            elif action == "join_room":
                code = data.get("room_code", "").strip().upper()
                player_name = data.get("name", "Trainer Blue").strip() or "Trainer Blue"
                player_avatar = data.get("avatar", "blue")
                session_id = data.get("session_id", "")

                room, err = room_manager.join_room(code, player_name, player_avatar, session_id)
                if not room:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "data": {"message": err}
                    }))
                    continue

                client_room_code = room.room_code
                client_session_id = session_id
                p = room.get_player(session_id)
                if p:
                    p.ws = websocket

                await websocket.send(json.dumps({
                    "type": "room_joined",
                    "data": {
                        "room_code": room.room_code,
                        "session_id": session_id,
                        "is_host": p.is_host if p else False,
                        "room_state": room.to_state_dict()
                    }
                }))

                # If reconnecting mid-battle, re-send active turn prompt for this player
                if room.status == "BATTLE" and room.active_live_battle and p:
                    if room.active_live_battle.is_human_controlled(session_id):
                        prompt_data = room.active_live_battle.build_player_prompt(session_id)
                        await websocket.send(json.dumps({"type": "battle_turn_prompt", "data": prompt_data}, ensure_ascii=False))

                # Broadcast updated state to all
                await broadcast_to_room(room, "room_state", room.to_state_dict())

            # 3. TOGGLE READY
            elif action == "toggle_ready":
                if not client_room_code or not client_session_id:
                    continue
                room = room_manager.rooms.get(client_room_code)
                if room and client_session_id in room.players:
                    p = room.players[client_session_id]
                    p.is_ready = not p.is_ready
                    await broadcast_to_room(room, "room_state", room.to_state_dict())

            # 4. START GAME (Host only)
            elif action == "start_game":
                if not client_room_code or not client_session_id:
                    continue
                room = room_manager.rooms.get(client_room_code)
                if not room:
                    continue
                host = room.players.get(client_session_id)
                if not host or not host.is_host:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "data": {"message": "Only the room host can start the auction."}
                    }))
                    continue

                if len(room.players) < 2:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "data": {"message": "Need at least 2 players to start the auction."}
                    }))
                    continue

                existing_task = room_auction_tasks.get(room.room_code)
                if room.status != "LOBBY" or (existing_task and not existing_task.done()):
                    await websocket.send(json.dumps({
                        "type": "error",
                        "data": {"message": "Auction has already started for this room."}
                    }))
                    continue

                # Lock the dynamic fixed auction pool for the match
                active_count = len([p for p in room.players.values() if not p.is_withdrawn])
                calculated_pool = get_max_auction_characters(active_count)
                if not room.character_pool:
                    room_manager.initialize_room_pool(room)
                if len(room.character_pool) < calculated_pool:
                    room.max_auction_characters = len(room.character_pool)
                    await broadcast_to_room(room, "room_event", {
                        "message": f"Auction pool limited to {len(room.character_pool)} available characters for selected franchise(s)."
                    })
                else:
                    room.max_auction_characters = calculated_pool
                room.auction_character_count = 0

                # Start the background auction loop task
                task = asyncio.create_task(run_room_auction_loop(room))
                room_auction_tasks[room.room_code] = task

            # 5. PLACE FLEXIBLE BID
            elif action == "place_bid":
                if not client_room_code or not client_session_id:
                    continue
                room = room_manager.rooms.get(client_room_code)
                if not room or room.status != "AUCTION":
                    continue

                async with room.auction_lock:
                    if room.status != "AUCTION" or room.auction_character_count in room.settled_rounds:
                        await websocket.send(json.dumps({
                            "type": "bid_error",
                            "data": {"message": "Round already settled!"}
                        }))
                        continue

                    bidder = room.players.get(client_session_id)
                    if not bidder:
                        continue

                    if bidder.is_withdrawn:
                        await websocket.send(json.dumps({
                            "type": "bid_error",
                            "data": {"message": "You have withdrawn from this match and cannot bid!"}
                        }))
                        continue

                    if bidder.has_skipped:
                        await websocket.send(json.dumps({
                            "type": "bid_error",
                            "data": {"message": "You skipped this character and cannot place a bid!"}
                        }))
                        continue

                    try:
                        amount = int(data.get("amount", 0))
                    except (ValueError, TypeError):
                        await websocket.send(json.dumps({
                            "type": "bid_error",
                            "data": {"message": "Invalid bid amount!"}
                        }))
                        continue

                    if amount <= 0:
                        await websocket.send(json.dumps({
                            "type": "bid_error",
                            "data": {"message": "Bid must be a positive amount!"}
                        }))
                        continue

                    if bidder.is_team_full:
                        await websocket.send(json.dumps({
                            "type": "bid_error",
                            "data": {"message": "Your team is already full (6/6 Characters)!"}
                        }))
                        continue

                    if client_session_id == room.highest_bidder_id:
                        await websocket.send(json.dumps({
                            "type": "bid_error",
                            "data": {"message": "You already hold the highest bid!"}
                        }))
                        continue

                    # Minimum required bid: opening bid if 0, else current_bid + 1 (flexible increment!)
                    min_required = room.min_bid if room.current_bid == 0 else room.current_bid + 1
                    if amount < min_required:
                        await websocket.send(json.dumps({
                            "type": "bid_error",
                            "data": {"message": f"Bid must be at least ₹{min_required}."}
                        }))
                        continue

                    max_allowed = room.calculate_max_bid_for_player(bidder)
                    if amount > max_allowed:
                        await websocket.send(json.dumps({
                            "type": "bid_error",
                            "data": {"message": f"Insufficient balance! Available purse: ₹{bidder.purse}."}
                        }))
                        continue

                    # Bid is valid!
                    room.current_bid = amount
                    room.highest_bidder_id = client_session_id
                    bid_record = {
                        "bidderId": client_session_id,
                        "bidderName": bidder.name,
                        "bidAmount": amount,
                        "auctionId": f"{room.room_code}_round_{room.auction_character_count}",
                        "roomId": room.room_code,
                        "timestamp": time.time()
                    }
                    room.last_bid_record = bid_record
                    # Reset countdown timer to 15s
                    room.timer_end_timestamp = time.time() + room.countdown_seconds
                    room.timer_seconds_left = room.countdown_seconds
                    bid_payload = {
                        "current_bid": amount,
                        "highest_bidder_id": client_session_id,
                        "highest_bidder_name": bidder.name,
                        "highest_bidder_avatar": bidder.avatar,
                        "bidderId": client_session_id,
                        "bidderName": bidder.name,
                        "bidAmount": amount,
                        "auctionId": bid_record["auctionId"],
                        "roomId": room.room_code,
                        "timestamp": bid_record["timestamp"],
                        "timer_seconds_left": room.countdown_seconds,
                        "room_state": room.to_state_dict()
                    }

                await broadcast_to_room(room, "bid_success", bid_payload)

            # 6. CHAT MESSAGE
            elif action == "chat":
                if not client_room_code or not client_session_id:
                    continue
                room = room_manager.rooms.get(client_room_code)
                if not room:
                    continue
                sender = room.get_player(client_session_id)
                text = str(data.get("text", "")).strip()[:150]
                if sender and text:
                    await broadcast_to_room(room, "chat", {
                        "sender_name": sender.name,
                        "sender_avatar": sender.avatar,
                        "text": text,
                        "time": time.strftime("%H:%M")
                    })

            # 7. SKIP CURRENT CHARACTER
            elif action == "skip_character":
                if not client_room_code or not client_session_id:
                    continue
                room = room_manager.rooms.get(client_room_code)
                if not room or room.status != "AUCTION":
                    continue

                skip_payload = None
                all_skipped_payload = None
                error_msg = None
                async with room.auction_lock:
                    if room.status != "AUCTION":
                        continue
                    p = room.players.get(client_session_id)
                    if not p:
                        continue
                    if p.is_withdrawn:
                        error_msg = "You have withdrawn from this match."
                    elif not p.has_skipped:
                        success, msg, all_skipped = room.record_skip(client_session_id)
                        if success:
                            state_snap = room.to_state_dict()
                            skip_payload = {
                                "session_id": client_session_id,
                                "player_name": p.name,
                                "all_skipped": all_skipped,
                                "room_state": state_snap
                            }
                            if all_skipped:
                                all_skipped_payload = {
                                    "message": f"All eligible trainers skipped {room.current_character_sanitized.get('name', 'character')}! Round ended early.",
                                    "character": room.current_character_sanitized,
                                    "pokemon": room.current_character_sanitized,
                                    "room_state": state_snap
                                }
                                if room.skip_event and not room.skip_event.is_set():
                                    room.skip_event.set()

                if error_msg:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "data": {"message": error_msg}
                    }))
                    continue
                if skip_payload:
                    await broadcast_to_room(room, "character_skipped", skip_payload)
                if all_skipped_payload:
                    await broadcast_to_room(room, "all_skipped_round_ended", all_skipped_payload)

            # 8. WITHDRAW FROM MATCH
            elif action == "withdraw_match":
                if not client_room_code or not client_session_id:
                    continue
                room = room_manager.rooms.get(client_room_code)
                if not room:
                    continue

                withdraw_payload = None
                host_transfer_payload = None
                async with room.auction_lock:
                    p = room.players.get(client_session_id)
                    if not p or p.is_withdrawn:
                        continue

                    success, msg, new_host_id, should_end = room.withdraw_player(client_session_id)
                    if success:
                        # If withdrawn player held current high bid, clear it before snapshot
                        if room.highest_bidder_id == client_session_id:
                            room.highest_bidder_id = None
                            room.current_bid = 0

                        withdraw_payload = {
                            "session_id": client_session_id,
                            "player_name": p.name,
                            "new_host_id": new_host_id,
                            "should_end_match": should_end,
                            "room_state": room.to_state_dict()
                        }
                        if new_host_id:
                            new_host = room.players.get(new_host_id)
                            host_transfer_payload = {
                                "new_host_id": new_host_id,
                                "new_host_name": new_host.name if new_host else "Trainer",
                                "message": f"Host status transferred to {new_host.name if new_host else 'Trainer'}."
                            }

                        if should_end:
                            if room.skip_event and not room.skip_event.is_set():
                                room.skip_event.set()
                        elif room.all_eligible_players_skipped():
                            if room.skip_event and not room.skip_event.is_set():
                                room.skip_event.set()

                if withdraw_payload:
                    await broadcast_to_room(room, "player_withdrawn", withdraw_payload)
                if host_transfer_payload:
                    await broadcast_to_room(room, "host_transferred", host_transfer_payload)

            # 9. REQUEST REMATCH (Host only)
            elif action == "request_rematch":
                if not client_room_code or not client_session_id:
                    continue
                room = room_manager.rooms.get(client_room_code)
                if not room:
                    continue
                host = room.players.get(client_session_id)
                if not host or not host.is_host:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "data": {"message": "Only the room host can initiate a rematch."}
                    }))
                    continue

                success, msg = room.request_rematch(client_session_id)
                if success:
                    connected = [pl for pl in room.players.values() if pl.is_connected]
                    if len(connected) < 2:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "data": {"message": "Need at least 2 connected players for a rematch."}
                        }))
                        room.status = "GAME_OVER"
                        continue

                    await broadcast_to_room(room, "rematch_requested", {
                        "host_session_id": client_session_id,
                        "host_name": host.name,
                        "votes": room.rematch_votes,
                        "total_needed": len(connected),
                        "accepted_count": 1,
                        "message": f"Trainer {host.name} wants a rematch!",
                        "room_state": room.to_state_dict()
                    })

            # 10. VOTE ON REMATCH
            elif action == "vote_rematch":
                if not client_room_code or not client_session_id:
                    continue
                room = room_manager.rooms.get(client_room_code)
                if not room:
                    continue
                voter = room.players.get(client_session_id)
                if not voter:
                    continue
                accept = bool(data.get("accept", False))

                success, msg, all_accepted, any_declined = room.vote_rematch(client_session_id, accept)
                if not success:
                    await websocket.send(json.dumps({"type": "error", "data": {"message": msg}}))
                    continue

                connected = [pl for pl in room.players.values() if pl.is_connected]
                accepted_count = sum(1 for pl in connected if room.rematch_votes.get(pl.session_id) is True)

                if any_declined:
                    await broadcast_to_room(room, "rematch_declined", {
                        "declined_by_id": client_session_id,
                        "declined_by_name": voter.name,
                        "message": f"{voter.name} declined the rematch request.",
                        "room_state": room.to_state_dict()
                    })
                elif all_accepted:
                    if room.active_live_battle and hasattr(room.active_live_battle, "invalidate"):
                        room.active_live_battle.invalidate()
                    old_task = room_auction_tasks.get(room.room_code)
                    if old_task and not old_task.done():
                        old_task.cancel()

                    rematch_info = room.reset_for_rematch(room_manager)
                    await broadcast_to_room(room, "rematch_started", {
                        "match_id": rematch_info["match_id"],
                        "match_number": rematch_info["match_number"],
                        "max_auction_characters": rematch_info["max_auction_characters"],
                        "message": "All trainers accepted! Starting fresh rematch!",
                        "room_state": room.to_state_dict()
                    })

                    new_task = asyncio.create_task(run_room_auction_loop(room))
                    room_auction_tasks[room.room_code] = new_task
                else:
                    await broadcast_to_room(room, "rematch_vote_update", {
                        "voter_id": client_session_id,
                        "voter_name": voter.name,
                        "vote": accept,
                        "accepted_count": accepted_count,
                        "total_needed": len(connected),
                        "votes": room.rematch_votes,
                        "room_state": room.to_state_dict()
                    })

            # 11B. SUBMIT LIVE BATTLE ACTION
            elif action == "submit_battle_action":
                if not client_room_code or not client_session_id:
                    continue
                room = room_manager.rooms.get(client_room_code)
                if not room or not room.active_live_battle:
                    await websocket.send(json.dumps({
                        "type": "battle_action_error",
                        "data": {"message": "No interactive battle is currently active."}
                    }))
                    continue
                ok, msg = room.active_live_battle.submit_action(client_session_id, data)
                await websocket.send(json.dumps({
                    "type": "battle_action_ack" if ok else "battle_action_error",
                    "data": {"success": ok, "message": msg}
                }))

            # 11. EXIT ROOM
            elif action == "exit_room":
                if not client_room_code or not client_session_id:
                    continue
                room = room_manager.rooms.get(client_room_code)
                if not room:
                    continue
                p = room.players.pop(client_session_id, None)
                if not p:
                    room.spectators.pop(client_session_id, None)
                else:
                    if p.is_host:
                        connected = [pl for pl in room.players.values() if pl.is_connected and not pl.is_withdrawn]
                        if connected:
                            connected[0].is_host = True
                            await broadcast_to_room(room, "host_transferred", {
                                "new_host_id": connected[0].session_id,
                                "new_host_name": connected[0].name,
                                "message": f"Host status transferred to {connected[0].name}."
                            })
                    await broadcast_to_room(room, "player_left", {
                        "session_id": client_session_id,
                        "player_name": p.name,
                        "room_state": room.to_state_dict()
                    })
                await websocket.send(json.dumps({
                    "type": "room_left",
                    "data": {"message": "You left the room."}
                }))
                client_room_code = None

            # 7. ADMIN WEBSOCKET ACTIONS
            elif action == "admin_toggle_character":
                cid = data.get("character_id")
                is_act = data.get("is_active")
                success = anime_db.toggle_character(cid, is_act)
                await websocket.send(json.dumps({
                    "type": "admin_result",
                    "data": {"action": "toggle_character", "success": success, "character_id": cid}
                }))

            elif action == "admin_toggle_franchise":
                fid = data.get("anime_id")
                is_act = data.get("is_active")
                success = anime_db.toggle_franchise(fid, is_act)
                await websocket.send(json.dumps({
                    "type": "admin_result",
                    "data": {"action": "toggle_franchise", "success": success, "anime_id": fid}
                }))

            elif action == "admin_update_character":
                cid = data.get("character_id")
                updates = data.get("updates", {})
                updated_char = anime_db.update_character_stats(cid, updates)
                await websocket.send(json.dumps({
                    "type": "admin_result",
                    "data": {"action": "update_character", "success": updated_char is not None, "character": updated_char}
                }))

    except ConnectionClosed:
        pass
    finally:
        if client_room_code and client_session_id:
            room = room_manager.rooms.get(client_room_code)
            if room:
                p = room.get_player(client_session_id)
                if p:
                    p.is_connected = False
                    p.ws = None
                if room.status == "LOBBY" and p and p.is_host:
                    connected = [pl for pl in room.players.values() if pl.is_connected and pl != p]
                    if connected:
                        p.is_host = False
                        connected[0].is_host = True
                await broadcast_to_room(room, "room_state", room.to_state_dict())


def json_response(status_code: int, status_text: str, data: Any) -> Response:
    """Helper to return JSON response with CORS headers."""
    return Response(
        status_code, status_text,
        Headers([
            ("Content-Type", "application/json; charset=utf-8"),
            ("Access-Control-Allow-Origin", "*"),
            ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
            ("Access-Control-Allow-Headers", "Content-Type")
        ]),
        json.dumps(data, ensure_ascii=False).encode("utf-8")
    )


def process_http_request(connection, request):
    """
    Handles HTTP requests for static assets and REST API on the exact same port.
    Returns Response(...) for HTTP requests, or None to allow WebSocket upgrade.
    """
    parsed = urlparse(request.path)
    path = parsed.path
    query = parse_qs(parsed.query)

    if path == "/ws":
        return None

    # Dynamic SVG Avatar Generator Endpoint (Guarantees zero broken images)
    if path.startswith("/api/avatar/"):
        parts = path.split("/")
        cid = unquote(parts[3]) if len(parts) > 3 else "default"
        char = anime_db.get_character_by_id(cid)
        if not char:
            is_marvel = cid.startswith("marvel_")
            char = {
                "id": cid,
                "name": cid.replace("_", " ").title(),
                "universe": "marvel" if is_marvel else "anime",
                "anime_id": "marvel" if is_marvel else "anime",
                "anime_name": "Marvel Comics" if is_marvel else "Anime Character",
                "power_tier": "A"
            }
        svg_content = generate_character_svg(char)
        return Response(
            200, "OK",
            Headers([
                ("Content-Type", "image/svg+xml; charset=utf-8"),
                ("Cache-Control", "public, max-age=86400"),
                ("Access-Control-Allow-Origin", "*")
            ]),
            svg_content.encode("utf-8")
        )

    # Accurate Database Metrics Endpoint
    if path == "/api/anime/stats":
        stats = anime_db.get_database_stats()
        return json_response(200, "OK", stats)

    # Platform & Franchise Stats
    if path == "/api/stats":
        stats = anime_db.get_database_stats()
        franchises = anime_db.get_all_franchises()
        payload = {
            "total_pokemon": stats["pokemon_count"],
            "total_characters": stats["total_characters"],
            "total_franchises": stats["total_franchises"],
            "pokemon_count": stats["pokemon_count"],
            "anime_characters_count": stats["anime_count"],
            "total_character_forms": stats["total_character_forms"],
            "characters_with_images": stats["characters_with_images"],
            "characters_with_power_data": stats["characters_with_power_data"],
            "default_purse": DEFAULT_STARTING_PURSE,
            "multiplayer_status": "ready",
            "active_rooms": len(room_manager.rooms)
        }
        return json_response(200, "OK", payload)

    # Franchise list
    if path == "/api/anime":
        franchises = anime_db.get_all_franchises()
        return json_response(200, "OK", franchises)

    # Search, Filter, Sort & Paginate Characters
    if path == "/api/characters":
        q = query.get("q", [""])[0]
        anime_id = query.get("anime_id", [None])[0]
        power_tier = query.get("power_tier", [None])[0]
        rarity = query.get("rarity", [None])[0]
        species = query.get("species", [None])[0]
        category = query.get("category", [None])[0]
        affiliation = query.get("affiliation", [None])[0]
        continuity = query.get("continuity", [None])[0]
        combat_eligible = query.get("combat_eligible", [None])[0]
        has_artwork = query.get("has_artwork", [None])[0]
        sort = query.get("sort", ["power_desc"])[0]
        try:
            limit = int(query.get("limit", [50])[0])
            offset = int(query.get("offset", [0])[0])
        except ValueError:
            limit = 50
            offset = 0

        res = anime_db.search_characters(
            query=q,
            anime_id=anime_id,
            power_tier=power_tier,
            rarity=rarity,
            species=species,
            category=category,
            affiliation=affiliation,
            continuity=continuity,
            combat_eligible=combat_eligible,
            has_artwork=has_artwork,
            sort=sort,
            limit=limit,
            offset=offset
        )
        return json_response(200, "OK", res)

    # Single character by ID
    if path.startswith("/api/characters/") and len(path.split("/")) > 3:
        char_id = path.split("/")[3]
        char = anime_db.get_character_by_id(char_id)
        if char:
            return json_response(200, "OK", char)
        return json_response(404, "Not Found", {"error": f"Character {char_id} not found"})

    # Admin GET toggles for quick testing / bookmarklet / integration
    if path == "/api/admin/character/toggle":
        cid = query.get("id", [""])[0]
        val = query.get("active", [None])[0]
        is_active = None if val is None else (val.lower() in ["1", "true", "yes"])
        success = anime_db.toggle_character(cid, is_active)
        return json_response(200 if success else 400, "OK", {"success": success, "character_id": cid})

    if path == "/api/admin/franchise/toggle":
        fid = query.get("id", [""])[0]
        val = query.get("active", [None])[0]
        is_active = None if val is None else (val.lower() in ["1", "true", "yes"])
        success = anime_db.toggle_franchise(fid, is_active)
        return json_response(200 if success else 400, "OK", {"success": success, "anime_id": fid})

    # Admin Automated Import Endpoints (AniList + Jikan + Kitsu)
    if path == "/api/admin/audit":
        audit_file = os.path.join(DATA_DIR, "database_audit_report.json")
        if os.path.exists(audit_file) and query.get("refresh", ["0"])[0] != "1":
            with open(audit_file, "r", encoding="utf-8") as f:
                audit_data = json.load(f)
        else:
            audit_data = anime_db.generate_audit_report(audit_file)
        return json_response(200, "OK", audit_data)

    if path == "/api/admin/repair/images":
        res = anime_db.repair_images()
        return json_response(200, "OK", res)

    if path == "/api/admin/duplicates/scan":
        res = anime_db.scan_duplicates()
        return json_response(200, "OK", res)

    if path == "/api/admin/reload":
        anime_db.reload()
        return json_response(200, "OK", {"success": True, "stats": anime_db.get_database_stats()})

    if path == "/api/admin/import/status":
        status = anime_db.import_manager.get_status()
        return json_response(200, "OK", status)

    if path == "/api/admin/import/start":
        source = query.get("source", ["anilist"])[0]
        try:
            pages = int(query.get("pages", [5])[0])
        except ValueError:
            pages = 5
        success, msg = anime_db.import_manager.start_job(source=source, max_pages=pages)
        return json_response(200 if success else 400, "OK", {"success": success, "message": msg, "source": source})

    if path == "/api/admin/import/stop":
        success, msg = anime_db.import_manager.stop_job()
        return json_response(200, "OK", {"success": success, "message": msg})

    # Player persistent profiles endpoint
    if path.startswith("/api/profiles/") and len(path.split("/")) > 3:
        player_id = path.split("/")[3]
        prof = profile_store.get_profile(player_id)
        if prof:
            return json_response(200, "OK", prof)
        return json_response(404, "Not Found", {"error": f"Profile {player_id} not found"})

    # Legacy Pokemon API endpoints
    if path == "/api/pokemon" or path.startswith("/api/pokemon/"):
        if path.startswith("/api/pokemon/") and len(path.split("/")) > 3:
            try:
                pid = int(path.split("/")[3])
                poke = POKEMON_BY_ID.get(pid)
                if poke:
                    return json_response(200, "OK", poke)
                return json_response(404, "Not Found", {"error": "Not Found"})
            except ValueError:
                return json_response(400, "Bad Request", {"error": "Invalid ID"})

        return json_response(200, "OK", POKEMON_DATABASE)

    # Static file routing
    file_rel = "index.html" if path in ["", "/"] else path.lstrip("/")
    file_path = os.path.join(PUBLIC_DIR, file_rel)
    if not os.path.exists(file_path):
        file_path = os.path.join(DATA_DIR, file_rel)

    if os.path.exists(file_path) and os.path.isfile(file_path):
        mime, _ = mimetypes.guess_type(file_path)
        content_type = mime or "application/octet-stream"
        if "text/" in content_type or "javascript" in content_type or "json" in content_type:
            content_type += "; charset=utf-8"

        with open(file_path, "rb") as f:
            data = f.read()

        return Response(
            200, "OK",
            Headers([
                ("Content-Type", content_type),
                ("Access-Control-Allow-Origin", "*"),
                ("Cache-Control", "no-cache")
            ]),
            data
        )

    return Response(404, "Not Found", Headers([("Content-Type", "text/plain")]), b"404 Not Found")


async def main():
    print(f"Starting Multi-Anime Character & Pokémon Auction Server on http://127.0.0.1:{PORT}/")
    server = await serve(
        ws_handler,
        "0.0.0.0",
        PORT,
        process_request=process_http_request
    )
    print(f"Server ready on port {PORT}. Press Ctrl+C to stop.")
    await server.wait_closed()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nServer stopped.")
