"""
Multi-Anime Character & Pokémon Auction Game: Room & Match Engine
=================================================================
Server-authoritative state machine for rooms, live cross-anime auctions,
timer synchronization, flexible bidding, room-isolated purse management,
and hidden-stat auctioning with dramatic final reveal.
"""

import asyncio
import json
import random
import time
from typing import Dict, List, Optional, Set, Any

# Constants
MIN_PLAYERS_TO_START = 2
MAX_PLAYERS_PER_ROOM = 8
DEFAULT_STARTING_PURSE = 500  # Default ₹500 per player
TEAM_CAPACITY = 6
AUCTION_COUNTDOWN_SECONDS = 15
OPENING_MIN_BID = 10  # Opening bid ₹10
MIN_BID_INCREMENT = 1  # Flexible bidding: any positive increment >= 1

def get_max_auction_characters(player_count: int) -> int:
    """
    Calculates fixed dynamic auction pool size:
    Auction Pool = (Number of Active Players * 6) + 4
    Examples:
    2 players: 12 + 4 = 16
    3 players: 18 + 4 = 22
    4 players: 24 + 4 = 28
    5 players: 30 + 4 = 34
    6 players: 36 + 4 = 40
    7 players: 42 + 4 = 46
    8 players: 48 + 4 = 52
    """
    return (player_count * 6) + 4

get_max_auction_pokemon = get_max_auction_characters
AUCTION_POOL_TABLE = {p: get_max_auction_characters(p) for p in range(1, 9)}


def sanitize_character_for_auction(char: dict) -> dict:
    """
    CRITICAL STAT PRIVACY:
    Strips all competitive stats, battle IQ, power ratings, tiers, and numbers.
    During active bidding, clients receive ONLY:
    - Character artwork/image
    - Character name
    - Anime franchise name & ID
    - Current form name (e.g. Super Saiyan, Gear 5)
    - Identity metadata (gender, species, energy_system)
    - Legacy Pokemon metadata (types, generation)
    """
    if not char:
        return {}
    return {
        "id": char["id"],
        "name": char["name"],
        "universe": char.get("universe", "pokemon" if char.get("anime_id") == "pokemon" else ("marvel" if char.get("anime_id") == "marvel" else "anime")),
        "incarnation": char.get("incarnation", ""),
        "anime_id": char.get("anime_id", "pokemon"),
        "anime_name": char.get("anime_name", "Pokémon"),
        "current_form": char.get("current_form", "Base"),
        "image": char.get("image", ""),
        "official_pokedex_image": char.get("official_pokedex_image", char.get("image", "")),
        "gender": char.get("gender", ""),
        "species": char.get("species", ""),
        "race": char.get("race", ""),
        "energy_system": char.get("energy_system", ""),
        # Legacy Pokémon compatibility fields
        "national_id": char.get("national_id", 0),
        "types": char.get("types", []),
        "generation": char.get("generation", 1)
    }

sanitize_pokemon_for_auction = sanitize_character_for_auction


class Player:
    def __init__(self, session_id: str, name: str, avatar: str, is_host: bool = False, starting_purse: int = DEFAULT_STARTING_PURSE):
        self.session_id = session_id
        self.name = name
        self.avatar = avatar
        self.is_host = is_host
        self.is_ready = False
        # Room-specific purse that carries over between auctions in this match
        self.purse = starting_purse
        # Full character records stored on server
        self.team: List[dict] = []
        self.is_connected = True
        self.ws = None
        # Match lifecycle flags
        self.is_withdrawn: bool = False
        self.has_skipped: bool = False
        self.rematch_vote: Optional[bool] = None

    @property
    def team_count(self) -> int:
        return len(self.team)

    @property
    def is_team_full(self) -> bool:
        return len(self.team) >= TEAM_CAPACITY

    @property
    def total_team_power(self) -> float:
        return round(sum(p.get("power_rating", 0) for p in self.team), 1)

    @property
    def total_bst(self) -> int:
        total = 0
        for p in self.team:
            stats = p.get("stats", {})
            if "total" in stats:
                total += stats["total"]
            else:
                total += sum(v for v in stats.values() if isinstance(v, (int, float)))
        return int(total)

    @property
    def total_hp(self) -> int:
        total = 0
        for p in self.team:
            stats = p.get("stats", {})
            total += stats.get("hp", stats.get("durability", 0))
        return int(total)

    def to_dict(self, reveal_stats: bool = False) -> dict:
        """
        Serializes player state.
        If reveal_stats is False (during LOBBY and AUCTION), all stat information
        is stripped so clients cannot see team power or individual character stats.
        """
        if reveal_stats:
            sanitized_team = self.team
            power = self.total_team_power
            bst = self.total_bst
            hp = self.total_hp
        else:
            sanitized_team = [sanitize_character_for_auction(p) for p in self.team]
            power = None
            bst = None
            hp = None

        return {
            "session_id": self.session_id,
            "name": self.name,
            "avatar": self.avatar,
            "is_host": self.is_host,
            "is_ready": self.is_ready,
            "is_withdrawn": self.is_withdrawn,
            "has_skipped": self.has_skipped,
            "rematch_vote": self.rematch_vote,
            "purse": self.purse,
            "team_count": self.team_count,
            "is_team_full": self.is_team_full,
            "total_team_power": power,
            "total_bst": bst,
            "total_hp": hp,
            "team": sanitized_team,
            "is_connected": self.is_connected
        }


class Room:
    def __init__(
        self,
        room_code: str,
        host_player: Player,
        starting_purse: int = DEFAULT_STARTING_PURSE,
        countdown_seconds: int = AUCTION_COUNTDOWN_SECONDS,
        min_bid: int = OPENING_MIN_BID,
        anime_mode: str = "all",
        selected_anime: Optional[List[str]] = None,
        forms_mode: str = "SINGLE_BASE",
        battle_control_mode: str = "ai_vs_ai",
        tournament_format: str = "round_robin"
    ):
        self.room_code = room_code
        self.starting_purse = starting_purse
        self.countdown_seconds = countdown_seconds
        self.min_bid = min_bid
        self.bid_increment = MIN_BID_INCREMENT
        self.battle_control_mode = battle_control_mode
        self.tournament_format = tournament_format
        self.active_live_battle: Optional[Any] = None
        
        # Anime game mode configurations
        self.anime_mode = anime_mode  # 'all', 'single', 'multiple', 'pokemon', 'custom'
        self.selected_anime = selected_anime or []
        self.forms_mode = forms_mode  # 'SINGLE_BASE' or 'SEPARATE_ENTRIES'
        self.character_pool: List[dict] = []

        # Ensure host receives room-specific purse
        host_player.purse = starting_purse
        self.players: Dict[str, Player] = {host_player.session_id: host_player}
        self.spectators: Dict[str, Player] = {}
        
        # State: LOBBY, AUCTION, SHOWCASE, GAME_OVER
        self.status = "LOBBY"
        
        # Server-authoritative full current Character/Pokemon
        self.current_character_full: Optional[dict] = None
        self.current_bid: int = 0
        self.highest_bidder_id: Optional[str] = None
        self.timer_end_timestamp: float = 0
        self.timer_seconds_left: int = countdown_seconds
        self.timer_task: Optional[asyncio.Task] = None
        
        # Match tracking
        self.match_number: int = 1
        self.match_id: str = f"{room_code}_m1"
        self.match_history: List[dict] = []
        self.battle_results: Optional[dict] = None
        self.used_character_ids: Set[Any] = set()
        self.consecutive_unsold_count: int = 0
        self.auction_history: List[dict] = []
        self.chat_history: List[dict] = []
        self.skipped_player_ids: Set[str] = set()
        self.rematch_votes: Dict[str, bool] = {}
        self.skip_event: Optional[asyncio.Event] = None

        # Fixed Dynamic Auction Pool (calculated when game starts)
        self.max_auction_characters: int = 16
        self.auction_character_count: int = 0

    # Backward compatibility properties
    @property
    def current_pokemon_full(self) -> Optional[dict]:
        return self.current_character_full

    @current_pokemon_full.setter
    def current_pokemon_full(self, val: Optional[dict]):
        self.current_character_full = val

    @property
    def used_pokemon_ids(self) -> Set[Any]:
        return self.used_character_ids

    @property
    def max_auction_pokemon(self) -> int:
        return self.max_auction_characters

    @max_auction_pokemon.setter
    def max_auction_pokemon(self, val: int):
        self.max_auction_characters = val

    @property
    def auction_pokemon_count(self) -> int:
        return self.auction_character_count

    @auction_pokemon_count.setter
    def auction_pokemon_count(self, val: int):
        self.auction_character_count = val

    @property
    def current_character_sanitized(self) -> Optional[dict]:
        if not self.current_character_full:
            return None
        return sanitize_character_for_auction(self.current_character_full)

    @property
    def current_pokemon_sanitized(self) -> Optional[dict]:
        return self.current_character_sanitized

    @property
    def active_players(self) -> List[Player]:
        return [p for p in self.players.values() if not p.is_withdrawn]

    @property
    def connected_players_count(self) -> int:
        return sum(1 for p in self.players.values() if p.is_connected and not p.is_withdrawn)

    @property
    def all_teams_full(self) -> bool:
        active = [p for p in self.players.values() if not p.is_withdrawn]
        if len(active) == 0:
            return False
        return all(p.is_team_full for p in active)

    @property
    def eligible_bidders(self) -> List[Player]:
        """Players who are not withdrawn, have empty team slots, and enough funds for min bid."""
        return [
            p for p in self.players.values()
            if not p.is_withdrawn and not p.is_team_full and p.purse >= self.min_bid and p.is_connected
        ]

    def all_eligible_players_skipped(self) -> bool:
        eligible = self.eligible_bidders
        if not eligible:
            return True
        return all(p.session_id in self.skipped_player_ids for p in eligible)

    def record_skip(self, session_id: str) -> tuple[bool, str, bool]:
        """
        Records a player's skip on the current character.
        Returns: (success, message, all_eligible_skipped)
        """
        player = self.players.get(session_id)
        if not player or player.is_withdrawn:
            return False, "Player not eligible or already withdrawn.", False
        if self.status != "AUCTION":
            return False, "No active auction to skip.", False

        player.has_skipped = True
        self.skipped_player_ids.add(session_id)

        all_skipped = self.all_eligible_players_skipped()
        return True, "Skipped character successfully.", all_skipped

    def withdraw_player(self, session_id: str) -> tuple[bool, str, Optional[str], bool]:
        """
        Withdraws a player from the match.
        Returns: (success, message, new_host_id, should_end_match)
        """
        player = self.players.get(session_id)
        if not player:
            return False, "Player not found in room.", None, False
        if player.is_withdrawn:
            return False, "Player is already withdrawn.", None, False

        player.is_withdrawn = True
        player.has_skipped = True
        self.skipped_player_ids.add(session_id)

        new_host_id = None
        if player.is_host:
            # Deterministic transfer to next active non-withdrawn player
            active_others = [p for p in self.players.values() if not p.is_withdrawn and p.session_id != session_id]
            if active_others:
                player.is_host = False
                active_others[0].is_host = True
                new_host_id = active_others[0].session_id

        remaining_active = [p for p in self.players.values() if not p.is_withdrawn]
        should_end_match = (len(remaining_active) < 2) and (self.status in ("AUCTION", "SHOWCASE"))

        return True, f"{player.name} withdrew from the match.", new_host_id, should_end_match

    def request_rematch(self, session_id: str) -> tuple[bool, str]:
        """Host requests a rematch after match completion."""
        player = self.players.get(session_id)
        if not player or not player.is_host:
            return False, "Only the room host can initiate a rematch."
        if self.status not in ("GAME_OVER", "REMATCH_PENDING"):
            return False, "Match must be completed before requesting a rematch."

        self.status = "REMATCH_PENDING"
        self.rematch_votes = {session_id: True}
        for p in self.players.values():
            p.rematch_vote = True if p.session_id == session_id else None

        return True, "Rematch requested. Waiting for players to accept."

    def vote_rematch(self, session_id: str, accept: bool) -> tuple[bool, str, bool, bool]:
        """
        Records a player's rematch vote.
        Returns: (success, message, all_accepted, any_declined)
        """
        player = self.players.get(session_id)
        if not player:
            return False, "Player not found in room.", False, False
        if self.status != "REMATCH_PENDING":
            return False, "No rematch vote is currently pending.", False, False

        player.rematch_vote = accept
        self.rematch_votes[session_id] = accept

        if not accept:
            self.status = "GAME_OVER"
            return True, f"{player.name} declined the rematch.", False, True

        connected_players = [p for p in self.players.values() if p.is_connected]
        all_accepted = all(self.rematch_votes.get(p.session_id) is True for p in connected_players)
        return True, "Vote recorded.", all_accepted, False

    def reset_for_rematch(self, room_manager: Any) -> dict:
        """
        Resets match state for a fresh rematch while preserving room ID, settings, and connected players.
        Archives previous match into match_history.
        """
        leaderboard = room_manager.calculate_final_leaderboard(self)
        self.match_history.append({
            "match_id": self.match_id,
            "match_number": self.match_number,
            "leaderboard": leaderboard,
            "auction_rounds": self.auction_character_count,
            "completed_at": time.time()
        })

        self.match_number += 1
        self.match_id = f"{self.room_code}_m{self.match_number}"

        for p in self.players.values():
            p.purse = self.starting_purse
            p.team = []
            p.is_withdrawn = False
            p.has_skipped = False
            p.rematch_vote = None

        self.status = "AUCTION"
        if self.active_live_battle and hasattr(self.active_live_battle, "invalidate"):
            self.active_live_battle.invalidate()
        self.active_live_battle = None
        self.battle_results = None
        self.current_character_full = None
        self.last_bid_record = None
        self.current_bid = 0
        self.highest_bidder_id = None
        self.skipped_player_ids.clear()
        self.rematch_votes.clear()
        self.consecutive_unsold_count = 0
        self.auction_history.clear()
        self.used_character_ids.clear()

        room_manager.initialize_room_pool(self)

        active_count = len([p for p in self.players.values() if p.is_connected])
        calc_pool = get_max_auction_characters(active_count)
        if len(self.character_pool) < calc_pool:
            self.max_auction_characters = len(self.character_pool)
        else:
            self.max_auction_characters = calc_pool
        self.auction_character_count = 0

        return {
            "match_id": self.match_id,
            "match_number": self.match_number,
            "max_auction_characters": self.max_auction_characters
        }

    def get_player(self, session_id: str) -> Optional[Player]:
        return self.players.get(session_id) or self.spectators.get(session_id)

    def calculate_max_bid_for_player(self, player: Player) -> int:
        """
        Calculates maximum allowed bid for a player.
        Withdrawn players or players who skipped current character cannot bid.
        """
        if player.is_team_full or player.is_withdrawn or player.has_skipped:
            return 0
        return max(0, player.purse)

    def to_state_dict(self) -> dict:
        """
        Complete room state broadcasted to clients.
        Reveals stats ONLY when status is GAME_OVER.
        During AUCTION and LOBBY, all competitive stats are hidden.
        """
        reveal_stats = (self.status in ("BATTLE", "GAME_OVER"))

        highest_bidder_name = None
        highest_bidder_avatar = None
        if self.highest_bidder_id and self.highest_bidder_id in self.players:
            p = self.players[self.highest_bidder_id]
            highest_bidder_name = p.name
            highest_bidder_avatar = p.avatar

        current_char = self.current_character_full if reveal_stats else self.current_character_sanitized

        return {
            "room_code": self.room_code,
            "status": self.status,
            "starting_purse": self.starting_purse,
            "min_bid": self.min_bid,
            "bid_increment": self.bid_increment,
            "anime_mode": self.anime_mode,
            "selected_anime": self.selected_anime,
            "forms_mode": self.forms_mode,
            "battle_control_mode": self.battle_control_mode,
            "tournament_format": self.tournament_format,
            "max_auction_pokemon": self.max_auction_characters,
            "max_auction_characters": self.max_auction_characters,
            "auction_pokemon_count": self.auction_character_count,
            "auction_character_count": self.auction_character_count,
            "pool_exhausted": self.auction_character_count >= self.max_auction_characters,
            "players": [p.to_dict(reveal_stats=reveal_stats) for p in self.players.values()],
            "match_id": self.match_id,
            "match_number": self.match_number,
            "skipped_player_ids": list(self.skipped_player_ids),
            "rematch_votes": self.rematch_votes,
            "rematch_pending": (self.status == "REMATCH_PENDING"),
            "active_players_count": len([p for p in self.players.values() if not p.is_withdrawn]),
            "current_pokemon": current_char,
            "current_character": current_char,
            "current_bid": self.current_bid,
            "highest_bidder_id": self.highest_bidder_id,
            "highest_bidder_name": highest_bidder_name,
            "highest_bidder_avatar": highest_bidder_avatar,
            "timer_seconds_left": max(0, int(self.timer_seconds_left)),
            "all_teams_full": self.all_teams_full,
            "consecutive_unsold": self.consecutive_unsold_count
        }


class RoomManager:
    def __init__(self, database_or_manager: Any):
        # Support both AnimeDatabaseManager and legacy list of dicts
        self.anime_db = database_or_manager
        if isinstance(database_or_manager, list):
            self.character_database = database_or_manager
        else:
            self.character_database = list(database_or_manager.characters.values()) if hasattr(database_or_manager, "characters") else []
        self.rooms: Dict[str, Room] = {}

    @property
    def pokemon_database(self) -> List[dict]:
        return self.character_database

    @pokemon_database.setter
    def pokemon_database(self, val: List[dict]):
        self.character_database = val

    def generate_room_code(self) -> str:
        """Generates a unique 6-character room code (e.g. ANME-842)."""
        chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        while True:
            suffix = "".join(random.choices(chars, k=4))
            code = f"ANME-{suffix}"
            if code not in self.rooms:
                return code

    def create_room(
        self,
        host_name: str,
        host_avatar: str,
        session_id: str,
        starting_purse: int = DEFAULT_STARTING_PURSE,
        countdown_seconds: int = AUCTION_COUNTDOWN_SECONDS,
        min_bid: int = OPENING_MIN_BID,
        anime_mode: str = "all",
        selected_anime: Optional[List[str]] = None,
        forms_mode: str = "SINGLE_BASE",
        battle_control_mode: str = "ai_vs_ai",
        tournament_format: str = "round_robin"
    ) -> Room:
        code = self.generate_room_code()
        host = Player(session_id=session_id, name=host_name, avatar=host_avatar, is_host=True, starting_purse=starting_purse)
        room = Room(
            room_code=code,
            host_player=host,
            starting_purse=starting_purse,
            countdown_seconds=countdown_seconds,
            min_bid=min_bid,
            anime_mode=anime_mode,
            selected_anime=selected_anime,
            forms_mode=forms_mode,
            battle_control_mode=battle_control_mode,
            tournament_format=tournament_format
        )

        # Build initial character pool based on anime_mode
        self.initialize_room_pool(room)
        self.rooms[code] = room
        return room

    def initialize_room_pool(self, room: Room):
        """Initializes the character pool for a room based on its mode and forms setting."""
        if hasattr(self.anime_db, "get_characters_for_mode"):
            room.character_pool = self.anime_db.get_characters_for_mode(
                mode=room.anime_mode,
                selected_anime=room.selected_anime,
                forms_mode=room.forms_mode
            )
        else:
            # Fallback to in-memory list
            if room.anime_mode == "pokemon":
                room.character_pool = [c for c in self.character_database if c.get("anime_id") == "pokemon" or "national_id" in c]
            else:
                room.character_pool = list(self.character_database)

        # Shuffle pool for variety
        random.shuffle(room.character_pool)

    def join_room(self, room_code: str, player_name: str, player_avatar: str, session_id: str) -> tuple[Optional[Room], str]:
        code = room_code.strip().upper()
        room = self.rooms.get(code)
        if not room:
            return None, "Room not found. Check the room code."

        # Check existing reconnection in this room
        if session_id in room.players:
            existing = room.players[session_id]
            existing.name = player_name
            existing.avatar = player_avatar
            existing.is_connected = True
            return room, "Reconnected to existing room session."

        if room.status == "GAME_OVER":
            return None, "This auction room has already ended."

        if room.status != "LOBBY":
            # Allow joining as spectator
            spectator = Player(session_id=session_id, name=player_name, avatar=player_avatar, is_host=False, starting_purse=room.starting_purse)
            room.spectators[session_id] = spectator
            return room, "Joined active match as spectator."

        if len(room.players) >= MAX_PLAYERS_PER_ROOM:
            return None, f"Room is full (max {MAX_PLAYERS_PER_ROOM} players)."

        player = Player(session_id=session_id, name=player_name, avatar=player_avatar, is_host=False, starting_purse=room.starting_purse)
        room.players[session_id] = player
        return room, "Joined room successfully."

    def select_random_character(self, room: Room) -> Optional[dict]:
        """Server-authoritative random selection from unused pool."""
        if not room.character_pool:
            self.initialize_room_pool(room)

        available = [c for c in room.character_pool if c["id"] not in room.used_character_ids]
        if not available:
            # If exhausted, allow reset of pool
            room.used_character_ids.clear()
            available = room.character_pool

        if not available:
            return None

        selected = random.choice(available)
        room.used_character_ids.add(selected["id"])
        return selected

    select_random_pokemon = select_random_character

    def calculate_final_leaderboard(self, room: Room) -> List[dict]:
        """
        Calculates final team power and ranks players.
        Reveals FULL competitive stats for the Results screen!
        Ranking & Tie-breaking rules:
        1. Higher Team Power (sum of power ratings)
        2. Higher combined stats / BST
        3. Higher highest individual Power Rating
        4. Higher remaining purse
        5. Tie

        CRITICAL: Team size is NEVER used in ranking or tie-breaking!
        """
        results = []
        for p in room.players.values():
            team = p.team
            team_power = p.total_team_power
            total_bst = p.total_bst
            total_hp = p.total_hp
            avg_power = round(team_power / len(team), 1) if team else 0.0

            sorted_team = sorted(team, key=lambda x: x.get("power_rating", 0), reverse=True)
            strongest = sorted_team[0] if sorted_team else None
            weakest = sorted_team[-1] if sorted_team else None
            highest_individual_pr = strongest.get("power_rating", 0) if strongest else 0

            franchises_represented = sorted(list(set(c.get("anime_name", "Pokémon") for c in team)))

            results.append({
                "session_id": p.session_id,
                "name": p.name,
                "avatar": p.avatar,
                "is_withdrawn": p.is_withdrawn,
                "team_power": team_power,
                "total_bst": total_bst,
                "total_hp": total_hp,
                "pokemon_count": len(team),
                "character_count": len(team),
                "team_size_display": f"{len(team)}/{TEAM_CAPACITY}",
                "avg_power": avg_power,
                "remaining_purse": p.purse,
                "highest_individual_pr": highest_individual_pr,
                "strongest": strongest,
                "weakest": weakest,
                "franchises_represented": franchises_represented,
                "team": team  # FULL stats revealed!
            })

        # Rank with tie-breakers (CRITICAL: Team size is NEVER used in ranking or tie-breaking)
        results.sort(key=lambda r: (
            not r.get("is_withdrawn", False),
            r["team_power"],
            r["total_bst"],
            r["highest_individual_pr"],
            r["remaining_purse"]
        ), reverse=True)

        current_rank = 1
        for i, res in enumerate(results):
            if i > 0:
                prev = results[i - 1]
                is_tied = (
                    res["team_power"] == prev["team_power"] and
                    res["total_bst"] == prev["total_bst"] and
                    res["highest_individual_pr"] == prev["highest_individual_pr"] and
                    res["remaining_purse"] == prev["remaining_purse"]
                )
                if not is_tied:
                    current_rank = i + 1
            res["rank"] = current_rank

        return results

    def calculate_battle_leaderboard(self, room: Room, battle_results: Optional[dict]) -> List[dict]:
        """
        Ranks players strictly by simulated battle results (wins/points/remaining HP),
        keeping team_power as informational metadata only. Falls back to
        calculate_final_leaderboard if no battle results are available.
        """
        if not battle_results or not battle_results.get("standings"):
            return self.calculate_final_leaderboard(room)

        standings_by_sid = {s["session_id"]: s for s in battle_results["standings"]}
        base_entries = {e["session_id"]: e for e in self.calculate_final_leaderboard(room)}

        final_list: List[dict] = []
        for s in battle_results["standings"]:
            sid = s["session_id"]
            entry = dict(base_entries.get(sid, {"session_id": sid, "name": s["name"], "team": []}))
            entry.update({
                "rank": s["rank"],
                "battle_wins": s["wins"],
                "battle_losses": s["losses"],
                "battle_draws": s["draws"],
                "battle_points": s["points"],
                "battle_remaining_hp": s["remaining_hp_total"],
                "matches_played": s["matches_played"],
            })
            final_list.append(entry)

        # Include any player missing from standings at the end
        for sid, entry in base_entries.items():
            if sid not in standings_by_sid:
                entry["rank"] = len(final_list) + 1
                final_list.append(entry)

        return final_list
