"""
Persistent Player Profiles & Battle Records (Phase 5)
=====================================================
Stores permanent player statistics in data/player_profiles.db keyed by
stable player_id/session_id (separate from temporary room state).
"""

import json
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PROFILE_DB = os.path.join(BASE_DIR, "data", "player_profiles.db")


class PlayerProfileStore:
    """SQLite-backed persistent store for player battle & championship records."""

    def __init__(self, db_path: str = DEFAULT_PROFILE_DB):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS player_profiles (
                    player_id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    total_matches INTEGER DEFAULT 0,
                    wins INTEGER DEFAULT 0,
                    losses INTEGER DEFAULT 0,
                    draws INTEGER DEFAULT 0,
                    championships INTEGER DEFAULT 0,
                    recent_history_json TEXT DEFAULT '[]',
                    updated_at REAL
                )
            """)
            conn.commit()
        finally:
            conn.close()

    def record_tournament_results(self, battle_results: dict):
        """Updates persistent player stats from a completed tournament."""
        if not battle_results or not battle_results.get("standings"):
            return
        champion_id = (battle_results.get("champion") or {}).get("session_id")
        match_id = battle_results.get("match_id", "")
        fmt = battle_results.get("format", "round_robin")
        now = time.time()

        conn = sqlite3.connect(self.db_path)
        try:
            for s in battle_results["standings"]:
                pid = str(s["session_id"])
                name = s.get("name", pid)
                w = int(s.get("wins", 0))
                l = int(s.get("losses", 0))
                d = int(s.get("draws", 0))
                played = w + l + d
                is_champ = 1 if (pid == champion_id and played > 0) else 0

                row = conn.execute(
                    "SELECT total_matches, wins, losses, draws, championships, recent_history_json FROM player_profiles WHERE player_id = ?",
                    (pid,),
                ).fetchone()

                if row:
                    tot, ow, ol, od, ochamp, hist_json = row
                    history = json.loads(hist_json or "[]")
                else:
                    tot, ow, ol, od, ochamp = 0, 0, 0, 0, 0
                    history = []

                history.insert(0, {
                    "match_id": match_id,
                    "format": fmt,
                    "rank": s.get("rank"),
                    "wins": w,
                    "losses": l,
                    "draws": d,
                    "champion": bool(is_champ),
                    "timestamp": now,
                })
                history = history[:20]

                conn.execute("""
                    INSERT INTO player_profiles (
                        player_id, display_name, total_matches, wins, losses, draws,
                        championships, recent_history_json, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(player_id) DO UPDATE SET
                        display_name=excluded.display_name,
                        total_matches=excluded.total_matches,
                        wins=excluded.wins,
                        losses=excluded.losses,
                        draws=excluded.draws,
                        championships=excluded.championships,
                        recent_history_json=excluded.recent_history_json,
                        updated_at=excluded.updated_at
                """, (
                    pid, name, tot + played, ow + w, ol + l, od + d,
                    ochamp + is_champ, json.dumps(history), now,
                ))
            conn.commit()
        finally:
            conn.close()

    def get_profile(self, player_id: str) -> Optional[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT player_id, display_name, total_matches, wins, losses, draws, championships, recent_history_json, updated_at FROM player_profiles WHERE player_id = ?",
                (str(player_id),),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        pid, name, tot, w, l, d, champ, hist_json, updated_at = row
        win_pct = round((w / tot) * 100.0, 1) if tot > 0 else 0.0
        return {
            "player_id": pid,
            "display_name": name,
            "total_matches": tot,
            "wins": w,
            "losses": l,
            "draws": d,
            "championships": champ,
            "win_percentage": win_pct,
            "recent_history": json.loads(hist_json or "[]"),
            "updated_at": updated_at,
        }
