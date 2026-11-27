"""
Multi-Anime Character & Pokémon Auction Local HTTP Server & Real-Time Multiplayer Engine
=======================================================================================
Unified server handling:
- Static file serving (Pokédex & Cross-Anime Multiplayer Arena)
- Multi-Anime REST API (/api/anime, /api/characters, /api/stats, /api/pokemon)
- Real-time WebSocket rooms (/ws) with authoritative timers and flexible bidding
- Room-isolated purse management (Default $100)
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
import secrets
import re
from collections import deque
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
from src.local_avatars import LocalAvatarLibrary
from src.battle_manager import BattleManager
from src.battle_report import describe_tournament
from src.live_battle_session import LiveBattleSession
from src.player_profiles import PlayerProfileStore
anime_db = AnimeDatabaseManager(ANIME_JSON_PATH, ANIME_DB_PATH)
local_avatars = LocalAvatarLibrary(PUBLIC_DIR)
battle_manager = BattleManager()
profile_store = PlayerProfileStore()

# Legacy compatibility cache
with open(POKEMON_JSON_PATH, "r", encoding="utf-8") as f:
    POKEMON_DATABASE = json.load(f)
POKEMON_BY_ID = {p["id"]: p for p in POKEMON_DATABASE}

# Import room manager
from src.room_manager import (
    RoomManager, Room, Player, TEAM_CAPACITY,
    AUCTION_COUNTDOWN_SECONDS, DEFAULT_STARTING_PURSE, OPENING_MIN_BID, MAX_STARTING_PURSE,
    sanitize_character_for_auction, sanitize_pokemon_for_auction,
    get_max_auction_characters, get_max_auction_pokemon
)

room_manager = RoomManager(anime_db)
PORT = int(sys.argv[1]) if __name__ == "__main__" and len(sys.argv) > 1 else 5050

# Map of room_code -> active auction asyncio.Task
room_auction_tasks: dict[str, asyncio.Task] = {}

RECONNECT_GRACE_SECONDS = float(os.getenv("ARENA_RECONNECT_GRACE_SECONDS", "120"))
MAX_ROOMS = 200
AUCTION_INTERMISSION_SECONDS = 2.5
ADMIN_TOKEN = os.getenv("ARENA_ADMIN_TOKEN", "")


def is_admin(headers):
    supplied = headers.get("Authorization", "")
    return bool(ADMIN_TOKEN) and secrets.compare_digest(
        supplied.encode(), f"Bearer {ADMIN_TOKEN}".encode()
    )


def sanitize_avatar(value):
    if re.fullmatch(r"(?:/)?assets/avatars/[a-zA-Z0-9_/-]+\.(?:png|jpg|jpeg|webp|avif)", value):
        return "/" + value.lstrip("/")
    return value if re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", value) else "red"


async def expire_disconnected_player(room, player):
    await asyncio.sleep(RECONNECT_GRACE_SECONDS)
    async with room.auction_lock:
        if room_manager.rooms.get(room.room_code) is not room or player.ws is not None:
            return
        ok, _, info = room_manager.leave_room(room.room_code, player.session_id)
        if not ok:
            return
        if room.skip_event and (info.get("should_end_match") or info.get("all_skipped")):
            room.skip_event.set()
        if info.get("room_deleted"):
            task = room_auction_tasks.pop(room.room_code, None)
            if task:
                task.cancel()
            return
    await broadcast_to_room(room, "room_state", room.to_state_dict())


async def broadcast_to_room(room: Room, message_type: str, data: dict):
    """Broadcasts a JSON message to all connected clients in a room."""
    payload = json.dumps({"type": message_type, "data": data}, ensure_ascii=False)
    for p in list(room.players.values()) + list(room.spectators.values()):
        if p.ws is not None:
            try:
                await p.ws.send(payload)
            except Exception:
                pass


async def _run_interactive_1v1(room: Room, pa, pb, current_match_id: str):
    """Runs a single interactive LiveBattleSession 1v1 between pa and pb."""
    built_a = [battle_manager.build_combatant(c)[1] for c in pa.team]
    built_b = [battle_manager.build_combatant(c)[1] for c in pb.team]
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
    room.live_progress = None

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
        room.live_progress = {
            "match_id": current_match_id,
            "player_a_name": pa.name,
            "player_b_name": pb.name,
            "turn_entry": turn_entry,
        }
        await broadcast_to_room(room, "battle_turn_resolved", room.live_progress)

    res = await live_sess.run_interactive(send_prompt=_send_prompt, broadcast_turn=_broadcast_turn)
    room.active_live_battle = None
    aborted = live_sess.is_invalidated or room.match_id != current_match_id
    return res, aborted


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

                await broadcast_to_room(room, "auction_tick", {
                    "timer_seconds_left": room.timer_seconds_left,
                    "round_id": room.auction_character_count,
                    "match_id": room.match_id
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
            await asyncio.sleep(AUCTION_INTERMISSION_SECONDS)

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
        if room.battle_control_mode in ("player_vs_ai", "player_vs_player") and len(active_players) >= 2:
            current_match_id = room.match_id
            standings_map = {
                p.session_id: {
                    "session_id": p.session_id,
                    "name": p.name,
                    "avatar": p.avatar,
                    "is_withdrawn": p.is_withdrawn,
                    "wins": 0,
                    "losses": 0,
                    "draws": 0,
                    "points": 0,
                    "remaining_hp_total": 0,
                    "matches_played": 0,
                    "team_count": len(p.team),
                }
                for p in room.players.values()
            }
            matches = []
            bracket_rounds = []
            is_bracket = room.tournament_format in ("bracket", "championship_bracket") and len(active_players) > 2

            def _record_match_outcome(pa, pb, res, round_label=None):
                standings_map[pa.session_id]["matches_played"] += 1
                standings_map[pb.session_id]["matches_played"] += 1
                standings_map[pa.session_id]["remaining_hp_total"] += res.player_a_remaining_hp
                standings_map[pb.session_id]["remaining_hp_total"] += res.player_b_remaining_hp
                if is_bracket:
                    if res.winner_id == pb.session_id:
                        winner, loser = pb, pa
                    elif res.winner_id == pa.session_id:
                        winner, loser = pa, pb
                    else:
                        winner, loser = (pa, pb) if res.player_a_remaining_hp >= res.player_b_remaining_hp else (pb, pa)
                    standings_map[winner.session_id]["wins"] += 1
                    standings_map[winner.session_id]["points"] += 3
                    standings_map[loser.session_id]["losses"] += 1
                else:
                    if res.is_draw or res.winner_id is None:
                        standings_map[pa.session_id]["draws"] += 1
                        standings_map[pb.session_id]["draws"] += 1
                        standings_map[pa.session_id]["points"] += 1
                        standings_map[pb.session_id]["points"] += 1
                        winner = None
                    elif res.winner_id == pa.session_id:
                        standings_map[pa.session_id]["wins"] += 1
                        standings_map[pb.session_id]["losses"] += 1
                        standings_map[pa.session_id]["points"] += 3
                        winner = pa
                    else:
                        standings_map[pb.session_id]["wins"] += 1
                        standings_map[pa.session_id]["losses"] += 1
                        standings_map[pb.session_id]["points"] += 3
                        winner = pb

                rec = {
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
                }
                if round_label:
                    rec["round"] = round_label
                matches.append(rec)
                return winner, rec

            if len(active_players) == 2:
                pa, pb = active_players[0], active_players[1]
                res, aborted = await _run_interactive_1v1(room, pa, pb, current_match_id)
                if aborted:
                    return
                _record_match_outcome(pa, pb, res)
                battle_format = "direct_1v1"
            elif is_bracket:
                battle_format = "championship_bracket"
                current_pool = list(active_players)
                round_num = 1
                total_est = max(1, len(active_players) - 1)
                match_counter = 0
                while len(current_pool) > 1:
                    round_label = "Final" if len(current_pool) == 2 else ("Semifinals" if len(current_pool) <= 4 else f"Round {round_num}")
                    next_pool = []
                    round_matches = []
                    idx = 0
                    while idx < len(current_pool):
                        if idx + 1 >= len(current_pool):
                            bye_p = current_pool[idx]
                            next_pool.append(bye_p)
                            round_matches.append({"bye": True, "player_id": bye_p.session_id, "player_name": bye_p.name})
                            idx += 1
                            continue
                        pa, pb = current_pool[idx], current_pool[idx + 1]
                        idx += 2
                        match_counter += 1
                        await broadcast_to_room(room, "battle_progress", {
                            "is_match_start": True,
                            "match_index": match_counter,
                            "total_matches": total_est,
                            "player_a_id": pa.session_id,
                            "player_a_name": pa.name,
                            "player_b_id": pb.session_id,
                            "player_b_name": pb.name,
                            "round": round_label,
                        })
                        res, aborted = await _run_interactive_1v1(room, pa, pb, current_match_id)
                        if aborted:
                            return
                        winner, rec = _record_match_outcome(pa, pb, res, round_label=round_label)
                        next_pool.append(winner)
                        round_matches.append(rec)
                    bracket_rounds.append({"round": round_label, "matches": round_matches})
                    current_pool = next_pool
                    round_num += 1
            else:
                battle_format = "round_robin"
                n = len(active_players)
                pairings = [(active_players[i], active_players[j]) for i in range(n) for j in range(i + 1, n)]
                total_m = len(pairings)
                for m_idx, (pa, pb) in enumerate(pairings, start=1):
                    await broadcast_to_room(room, "battle_progress", {
                        "is_match_start": True,
                        "match_index": m_idx,
                        "total_matches": total_m,
                        "player_a_id": pa.session_id,
                        "player_a_name": pa.name,
                        "player_b_id": pb.session_id,
                        "player_b_name": pb.name,
                    })
                    res, aborted = await _run_interactive_1v1(room, pa, pb, current_match_id)
                    if aborted:
                        return
                    _record_match_outcome(pa, pb, res)

            standings = list(standings_map.values())
            standings.sort(key=lambda s: (not s["is_withdrawn"], s["points"], s["wins"], s["remaining_hp_total"]), reverse=True)
            for r_idx, s in enumerate(standings, start=1):
                s["rank"] = r_idx

            battle_results = {
                "format": battle_format,
                "match_id": current_match_id,
                "total_matches": len(matches),
                "standings": standings,
                "champion": standings[0] if standings else None,
                "matches": matches,
                "bracket": {"rounds": bracket_rounds} if is_bracket else None,
            }
        else:
            battle_results = await battle_manager.run_tournament_async(
                list(room.players.values()),
                match_id=room.match_id,
                tournament_format=room.tournament_format
            )

        describe_tournament(battle_results, room.players.values())
        room.battle_results = battle_results
        await asyncio.to_thread(profile_store.record_tournament_results, battle_results)

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
        room.finish_data = finish_data
        await broadcast_to_room(room, "match_finished", finish_data)
        await broadcast_to_room(room, "game_over", finish_data)

    except asyncio.CancelledError:
        raise
    except Exception as e:
        print(f"[AuctionLoopError] room={room.room_code} match={room.match_id} round={room.auction_character_count}: {e}")
        room.status = "LOBBY"
        room.current_character_full = None
        room.timer_end_timestamp = 0
        for player in room.players.values():
            player.purse = room.starting_purse
            player.team.clear()
        room.used_character_ids.clear()
        room.settled_rounds.clear()
        room.settlement_ledger.clear()
        room.auction_history.clear()
        room.auction_character_count = room.current_bid = 0
        room.highest_bidder_id = None
        await broadcast_to_room(room, "room_event", {"message": "The auction ended unexpectedly. The lobby is ready to restart."})
        await broadcast_to_room(room, "room_state", room.to_state_dict())
    finally:
        if room_auction_tasks.get(room.room_code) is asyncio.current_task():
            room_auction_tasks.pop(room.room_code, None)


async def ws_handler(websocket: ServerConnection):
    """Handles incoming WebSocket connection."""
    client_session_id = None
    client_room_code = None
    recent_messages = deque()

    async def send_error(message, message_type="error"):
        await websocket.send(json.dumps({"type": message_type, "data": {"message": message}}))

    try:
        async for raw_msg in websocket:
            now = time.monotonic()
            while recent_messages and recent_messages[0] <= now - 10:
                recent_messages.popleft()
            if len(recent_messages) >= 80:
                await websocket.close(1008, "Message rate limit exceeded")
                break
            recent_messages.append(now)

            try:
                msg = json.loads(raw_msg)
            except (ValueError, UnicodeError, RecursionError):
                await send_error("Invalid JSON message.")
                continue
            if not isinstance(msg, dict) or not isinstance(msg.get("action"), str):
                await send_error("Invalid message format.")
                continue
            action = msg["action"]
            data = msg.get("data", {})
            if not isinstance(data, dict):
                await send_error("Invalid message data.")
                continue

            if action.startswith(("admin_", "avatar_admin_")) and not is_admin(websocket.request.headers):
                await send_error("Administrator access required.")
                continue

            if client_room_code:
                active_room = room_manager.rooms.get(client_room_code)
                active_player = active_room.get_player(client_session_id) if active_room else None
                if active_player and active_player.ws is not websocket:
                    await websocket.close(4001, "Session resumed in another tab")
                    break
                if not active_player and action in ("create_room", "join_room", "resume_room"):
                    kicked = active_room and client_session_id in active_room.kicked_session_ids
                    target = data.get("room_code")
                    if kicked and isinstance(target, str) and target.strip().upper() == client_room_code:
                        await send_error("You have been removed from this room by the host.")
                        continue
                    client_room_code = client_session_id = None
                elif not active_player and action != "submit_battle_action":
                    await send_error("You are no longer in this room.")
                    continue


            if action in ("create_room", "join_room", "resume_room"):
                if client_room_code:
                    await send_error("Leave the current room first.")
                    continue
                room_code = data.get("room_code", "")
                if not isinstance(room_code, str):
                    await send_error("Invalid room code.")
                    continue
                room_code = room_code.strip().upper()
                if action == "resume_room":
                    room = room_manager.rooms.get(room_code)
                    sid = data.get("session_id")
                    token = data.get("reconnect_token")
                    player = room.get_player(sid) if room and isinstance(sid, str) else None
                    if not player or not isinstance(token, str) or not secrets.compare_digest(
                        player.reconnect_token.encode(), token.encode()
                    ):
                        await send_error("Room session expired or is invalid.", "resume_error")
                        continue
                else:
                    name = data.get("name", "Trainer")
                    avatar = data.get("avatar", "red")
                    if not isinstance(name, str) or not isinstance(avatar, str):
                        await send_error("Name and avatar must be text.")
                        continue
                    name = name.strip()[:32] or "Trainer"
                    avatar = sanitize_avatar(avatar)
                    sid = secrets.token_hex(16)
                    if action == "create_room":
                        if len(room_manager.rooms) >= MAX_ROOMS:
                            await send_error("The server has reached its room limit.")
                            continue
                        purse = data.get("starting_purse", DEFAULT_STARTING_PURSE)
                        seconds = data.get("countdown_seconds", AUCTION_COUNTDOWN_SECONDS)
                        floor = data.get("min_bid", OPENING_MIN_BID)
                        mode = data.get("anime_mode", "all")
                        selected = data.get("selected_anime", [])
                        control = data.get("battle_control_mode", "ai_vs_ai")
                        tournament = data.get("tournament_format", "round_robin")
                        if tournament == "championship_bracket":
                            tournament = "bracket"
                        control = {"pvai": "player_vs_ai", "pvp": "player_vs_player"}.get(control, control) if isinstance(control, str) else None
                        if type(seconds) is not int or not 1 <= seconds <= 60:
                            await send_error("Auction countdown must be between 1 and 60 seconds.")
                            continue
                        if (mode in ("single", "multiple") and not selected) or (mode not in ("all", "anime", "anime_only", "marvel", "pokemon",
                                         "pokemon_standard", "pokemon_legendary", "pokemon_anime",
                                         "pokemon_marvel", "anime_marvel", "single", "multiple")
                            or not isinstance(selected, list) or len(selected) > 32
                            or any(not isinstance(item, str) or item not in anime_db.franchises for item in selected)
                            or control not in ("ai_vs_ai", "player_vs_ai", "player_vs_player", "pvai", "pvp")
                            or tournament not in ("round_robin", "bracket")):
                            await send_error("Invalid room settings.")
                            continue
                        try:
                            room = room_manager.create_room(
                                name, avatar, sid, starting_purse=purse, countdown_seconds=seconds,
                                min_bid=floor, anime_mode=mode, selected_anime=selected,
                                battle_control_mode=control, tournament_format=tournament,
                            )
                        except ValueError as error:
                            await send_error(str(error))
                            continue
                        if not room.character_pool:
                            room_manager.rooms.pop(room.room_code, None)
                            await send_error("No eligible characters match this draft selection.")
                            continue
                    else:
                        room, message = room_manager.join_room(room_code, name, avatar, sid)
                        if not room:
                            await send_error(message)
                            continue
                    player = room.get_player(sid)

                old_socket = player.ws
                player.ws = websocket
                player.is_connected = True
                if player.disconnect_task:
                    player.disconnect_task.cancel()
                    player.disconnect_task = None
                client_room_code = room.room_code
                client_session_id = sid
                if old_socket is not None and old_socket is not websocket:
                    asyncio.create_task(old_socket.close(4001, "Session resumed in another tab"))
                await websocket.send(json.dumps({
                    "type": "room_joined",
                    "data": {
                        "room_code": room.room_code, "session_id": sid,
                        "reconnect_token": player.reconnect_token,
                        "is_host": player.is_host, "room_state": room.to_state_dict(),
                        "auction_history": room.auction_history, "chat_history": room.chat_history,
                        "finish_data": room.finish_data, "live_progress": room.live_progress,
                    }
                }))
                if room.active_live_battle and room.active_live_battle.is_human_controlled(sid):
                    prompt = room.active_live_battle.build_player_prompt(sid)
                    if room.live_progress:
                        prompt.update({key: room.live_progress[key] for key in ("player_a_name", "player_b_name")})
                    await websocket.send(json.dumps({"type": "battle_turn_prompt", "data": prompt}))
                await broadcast_to_room(room, "room_state", room.to_state_dict())

            # 3. TOGGLE READY
            elif action == "toggle_ready":
                if not client_room_code or not client_session_id:
                    continue
                room = room_manager.rooms.get(client_room_code)
                if room and room.status == "LOBBY" and client_session_id in room.players:
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

                if room.connected_players_count < 2:
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
                room.status = "STARTING"
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
                    if (room.status != "AUCTION" or room.auction_character_count in room.settled_rounds
                        or time.time() >= room.timer_end_timestamp or (room.skip_event and room.skip_event.is_set())):
                        await websocket.send(json.dumps({
                            "type": "bid_error",
                            "data": {"message": "Round already settled!"}
                        }))
                        continue

                    bidder = room.players.get(client_session_id)
                    if not bidder:
                        await websocket.send(json.dumps({
                            "type": "bid_error",
                            "data": {"message": "You are no longer in this room." if client_session_id not in room.kicked_session_ids else "You have been removed from this room by the host."}
                        }))
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

                    amount = data.get("amount")
                    if type(amount) is not int:
                        await send_error("Enter a whole-dollar bid.", "bid_error")
                        continue
                    if data.get("match_id") != room.match_id or data.get(
                        "round_id"
                    ) != room.auction_character_count:
                        await send_error("This bid belongs to an earlier auction lot.", "bid_error")
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
                            "data": {"message": f"Bid must be at least ${min_required}."}
                        }))
                        continue

                    max_allowed = room.calculate_max_bid_for_player(bidder)
                    if amount > max_allowed:
                        await websocket.send(json.dumps({
                            "type": "bid_error",
                            "data": {"message": f"Maximum bid after reserving funds for open slots: ${max_allowed}."}
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
                    message = {
                        "sender_name": sender.name,
                        "sender_avatar": sender.avatar,
                        "text": text,
                        "time": time.strftime("%H:%M")
                    }
                    room.chat_history.append(message)
                    del room.chat_history[:-50]
                    await broadcast_to_room(room, "chat", message)

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
                        error_msg = "You have been removed from this room by the host." if client_session_id in room.kicked_session_ids else "You are no longer in this room."
                    elif p.is_withdrawn:
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

            # 9. UPDATE PROFILE (Live Name & Avatar Sync)
            elif action == "update_profile":
                new_name = str(data.get("name", "")).strip()[:20]
                new_avatar = str(data.get("avatar", "")).strip()
                if client_room_code and client_session_id:
                    room = room_manager.rooms.get(client_room_code)
                    if room:
                        p = room.get_player(client_session_id)
                        if p:
                            if new_name:
                                p.name = new_name
                            if new_avatar:
                                p.avatar = sanitize_avatar(new_avatar)
                            await broadcast_to_room(room, "room_state", room.to_state_dict())

            # 10. LOCAL ANIME AVATAR LIBRARY MANAGEMENT (Zero External APIs)
            elif action == "avatar_admin_list":
                manifest = local_avatars.sync_and_get_manifest()
                await websocket.send(json.dumps({
                    "type": "avatar_library_updated",
                    "data": manifest
                }))

            elif action == "avatar_admin_upload":
                items = data.get("items") or []
                if not items and data.get("image_data"):
                    items = [data]
                added = []
                errors = []
                for item in items:
                    try:
                        entry = local_avatars.upload_character(
                            name=str(item.get("name", "")),
                            anime=str(item.get("anime", "other-anime")),
                            image_data=str(item.get("image_data", "")),
                            filename=str(item.get("filename", "avatar.png")),
                            description=str(item.get("description", "")),
                            source=str(item.get("source", "")),
                            license_info=str(item.get("license", "")),
                        )
                        added.append(entry)
                    except Exception as ex:
                        errors.append(str(ex))
                manifest = local_avatars.sync_and_get_manifest()
                await websocket.send(json.dumps({
                    "type": "avatar_admin_result",
                    "data": {
                        "action": "upload",
                        "success": len(added) > 0 and len(errors) == 0,
                        "added": added,
                        "errors": errors,
                        "message": f"Imported {len(added)} character(s)." + (f" Errors: {'; '.join(errors)}" if errors else "")
                    }
                }))
                await websocket.send(json.dumps({
                    "type": "avatar_library_updated",
                    "data": manifest
                }))

            elif action == "avatar_admin_edit":
                try:
                    updated = local_avatars.edit_character(
                        char_id=str(data.get("id", "")),
                        new_name=str(data.get("name", "")),
                        new_anime=str(data.get("anime", "")),
                    )
                    manifest = local_avatars.sync_and_get_manifest()
                    await websocket.send(json.dumps({
                        "type": "avatar_admin_result",
                        "data": {"action": "edit", "success": True, "character": updated, "message": f"Updated {updated['name']}."}
                    }))
                    await websocket.send(json.dumps({
                        "type": "avatar_library_updated",
                        "data": manifest
                    }))
                except Exception as ex:
                    await websocket.send(json.dumps({
                        "type": "avatar_admin_result",
                        "data": {"action": "edit", "success": False, "message": str(ex)}
                    }))

            elif action == "avatar_admin_replace":
                try:
                    updated = local_avatars.replace_portrait(
                        char_id=str(data.get("id", "")),
                        image_data=str(data.get("image_data", "")),
                        filename=str(data.get("filename", "avatar.png")),
                    )
                    manifest = local_avatars.sync_and_get_manifest()
                    await websocket.send(json.dumps({
                        "type": "avatar_admin_result",
                        "data": {"action": "replace", "success": True, "character": updated, "message": f"Replaced portrait for {updated['name']}."}
                    }))
                    await websocket.send(json.dumps({
                        "type": "avatar_library_updated",
                        "data": manifest
                    }))
                except Exception as ex:
                    await websocket.send(json.dumps({
                        "type": "avatar_admin_result",
                        "data": {"action": "replace", "success": False, "message": str(ex)}
                    }))

            elif action == "avatar_admin_delete":
                ok = local_avatars.delete_character(str(data.get("id", "")))
                manifest = local_avatars.sync_and_get_manifest()
                await websocket.send(json.dumps({
                    "type": "avatar_admin_result",
                    "data": {"action": "delete", "success": ok, "message": "Character removed from library." if ok else "Character not found."}
                }))
                await websocket.send(json.dumps({
                    "type": "avatar_library_updated",
                    "data": manifest
                }))

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
                    await websocket.send(json.dumps({
                        "type": "battle_action_error",
                        "data": {"success": False, "message": "You are no longer a member of this room."}
                    }))
                    continue
                room = room_manager.rooms.get(client_room_code)
                if not room:
                    await websocket.send(json.dumps({
                        "type": "battle_action_error",
                        "data": {"success": False, "message": "Room not found or no longer active."}
                    }))
                    continue

                async with room.auction_lock:
                    if client_session_id not in room.players:
                        err_msg = (
                            "You have been removed from this room by the host."
                            if client_session_id in room.kicked_session_ids
                            else "You are no longer a member of this room."
                        )
                        await websocket.send(json.dumps({
                            "type": "battle_action_error",
                            "data": {"success": False, "message": err_msg}
                        }))
                        continue

                    if not room.active_live_battle:
                        await websocket.send(json.dumps({
                            "type": "battle_action_error",
                            "data": {"success": False, "message": "No interactive battle is currently active."}
                        }))
                        continue

                    ok, msg = room.active_live_battle.submit_action(client_session_id, data)

                await websocket.send(json.dumps({
                    "type": "battle_action_ack" if ok else "battle_action_error",
                    "data": {"success": ok, "message": msg}
                }))

            # 11. EXIT / LEAVE ROOM
            elif action in ("exit_room", "leave_room"):
                if not client_room_code or not client_session_id:
                    continue
                room = room_manager.rooms.get(client_room_code)
                if not room:
                    await websocket.send(json.dumps({
                        "type": "room_left",
                        "data": {"message": "You left the room."}
                    }))
                    client_room_code = None
                    continue

                leave_info = None
                state_snap = None
                async with room.auction_lock:
                    ok, msg, info = room_manager.leave_room(client_room_code, client_session_id)
                    if ok:
                        leave_info = info
                        if not info.get("room_deleted"):
                            if info.get("should_end_match") or info.get("all_skipped"):
                                if room.skip_event and not room.skip_event.is_set():
                                    room.skip_event.set()
                            state_snap = room.to_state_dict()
                        else:
                            if room.skip_event and not room.skip_event.is_set():
                                room.skip_event.set()

                if leave_info:
                    if leave_info.get("room_deleted"):
                        old_task = room_auction_tasks.pop(client_room_code, None)
                        if old_task and not old_task.done():
                            old_task.cancel()
                    else:
                        if leave_info.get("new_host_id"):
                            await broadcast_to_room(room, "host_transferred", {
                                "new_host_id": leave_info["new_host_id"],
                                "new_host_name": leave_info["new_host_name"],
                                "message": f"Host status transferred to {leave_info['new_host_name']}."
                            })
                        if not leave_info.get("was_spectator"):
                            await broadcast_to_room(room, "player_left", {
                                "session_id": client_session_id,
                                "player_name": leave_info["player"].name,
                                "room_state": state_snap
                            })

                await websocket.send(json.dumps({
                    "type": "room_left",
                    "data": {"message": "You left the room."}
                }))
                client_room_code = None

            # 12. KICK PLAYER (Host only)
            elif action == "kick_player":
                if not client_room_code or not client_session_id:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "data": {"message": "You are not currently in a room."}
                    }))
                    continue

                room = room_manager.rooms.get(client_room_code)
                if not room:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "data": {"message": "Room not found."}
                    }))
                    continue

                target_session_id = data.get("target_session_id")
                target_session_id = target_session_id.strip() if isinstance(target_session_id, str) else ""
                if not target_session_id:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "data": {"message": "Target player is required."}
                    }))
                    continue

                kick_ok = False
                kick_msg = ""
                kick_info = None
                state_snap = None
                async with room.auction_lock:
                    kick_ok, kick_msg, kick_info = room.kick_player(client_session_id, target_session_id)
                    if kick_ok and kick_info:
                        if kick_info.get("should_end_match") or kick_info.get("all_skipped"):
                            if room.skip_event and not room.skip_event.is_set():
                                room.skip_event.set()
                        state_snap = room.to_state_dict()

                if not kick_ok or not kick_info:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "data": {"message": kick_msg or "Unable to kick player."}
                    }))
                    continue

                target_player = kick_info["target_player"]
                if target_player.ws:
                    try:
                        await target_player.ws.send(json.dumps({
                            "type": "player_kicked",
                            "data": {
                                "room_code": room.room_code,
                                "target_session_id": target_session_id,
                                "message": "You have been removed from this room by the host."
                            }
                        }))
                    except Exception:
                        pass
                    target_player.ws = None

                await websocket.send(json.dumps({
                    "type": "kick_success",
                    "data": {
                        "target_session_id": target_session_id,
                        "target_name": target_player.name,
                        "message": f"{target_player.name} has been removed from the room."
                    }
                }))

                await broadcast_to_room(room, "player_left", {
                    "session_id": target_session_id,
                    "player_name": target_player.name,
                    "kicked": True,
                    "room_state": state_snap
                })

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
                if p and p.ws is websocket:
                    p.is_connected = False
                    p.ws = None
                    p.disconnect_task = asyncio.create_task(expire_disconnected_player(room, p))
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
        origin = request.headers.get("Origin")
        allowed = {item.strip() for item in os.getenv("ARENA_ALLOWED_ORIGINS", "").split(",") if item.strip()}
        host = request.headers.get("Host", "")
        if origin and origin not in allowed | {f"http://{host}", f"https://{host}"}:
            return json_response(403, "Forbidden", {"error": "Origin is not allowed."})
        return None

    if path.startswith("/api/admin/") and not is_admin(request.headers):
        return json_response(403, "Forbidden", {"error": "Administrator access required."})

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

    if path == "/api/auction-catalog":
        q = query.get("q", [""])[0].casefold()[:100]
        franchise = query.get("anime_id", [""])[0]
        try:
            offset = max(0, int(query.get("offset", ["0"])[0]))
        except ValueError:
            return json_response(400, "Bad Request", {"error": "Invalid offset"})
        matches = [
            character for character in anime_db.get_characters_for_mode()
            if (not franchise or character["anime_id"] == franchise)
            and q in character["name"].casefold()
        ]
        return json_response(200, "OK", {
            "characters": [sanitize_character_for_auction(c) for c in matches[offset:offset + 25]],
            "total": len(matches),
        })

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
            limit=max(1, min(200, limit)),
            offset=max(0, offset)
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

    # Local Anime Avatar Library Manifest (Synced with local folders, zero external APIs)
    if path in ["/assets/avatars/manifest.json", "/local-avatars/manifest"]:
        manifest = local_avatars.sync_and_get_manifest()
        return json_response(200, "OK", manifest)

    # Static file routing
    file_rel = "index.html" if path in ["", "/"] else path.lstrip("/")
    file_path = os.path.realpath(os.path.join(PUBLIC_DIR, unquote(file_rel)))
    if os.path.commonpath((PUBLIC_DIR, file_path)) != PUBLIC_DIR:
        return json_response(404, "Not Found", {"error": "Not Found"})

    if os.path.exists(file_path) and os.path.isfile(file_path):
        mime, _ = mimetypes.guess_type(file_path)
        content_type = mime or "application/octet-stream"
        if "text/" in content_type or "javascript" in content_type or "json" in content_type:
            content_type += "; charset=utf-8"

        file_size = os.path.getsize(file_path)
        range_header = request.headers.get("Range")
        if range_header and range_header.startswith("bytes="):
            try:
                spec = range_header.replace("bytes=", "").split(",")[0].strip()
                start_s, end_s = spec.split("-", 1)
                start = int(start_s) if start_s else 0
                end = int(end_s) if end_s else file_size - 1
                start = max(0, start)
                end = min(file_size - 1, end)
                length = max(0, end - start + 1)
                with open(file_path, "rb") as f:
                    f.seek(start)
                    chunk = f.read(length)
                return Response(
                    206, "Partial Content",
                    Headers([
                        ("Content-Type", content_type),
                        ("Content-Range", f"bytes {start}-{end}/{file_size}"),
                        ("Accept-Ranges", "bytes"),
                        ("Content-Length", str(len(chunk))),
                        ("Access-Control-Allow-Origin", "*"),
                        ("Cache-Control", "no-cache"),
                    ]),
                    chunk
                )
            except Exception:
                pass

        with open(file_path, "rb") as f:
            data = f.read()

        return Response(
            200, "OK",
            Headers([
                ("Content-Type", content_type),
                ("Accept-Ranges", "bytes"),
                ("Content-Length", str(len(data))),
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
        max_size=2**20,
        ping_interval=20,
        ping_timeout=20,
        process_request=process_http_request
    )
    print(f"Server ready on port {PORT}. Press Ctrl+C to stop.")
    await server.wait_closed()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nServer stopped.")
