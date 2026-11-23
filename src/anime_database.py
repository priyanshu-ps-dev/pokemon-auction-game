"""
Unified Multi-Anime Database Manager
====================================
Authoritative service for loading, querying, transforming, and persisting
characters and franchises across all auction game modes.
Supports:
- Modes: 'all', 'single', 'multiple', 'pokemon', 'custom'
- Transformations: 'SINGLE_BASE' vs 'SEPARATE_ENTRIES'
- Admin runtime mutations: toggle characters/franchises, edit stats
"""

import json
import os
import sqlite3
import copy
from typing import Dict, List, Optional, Any

from src.anime_models import (
    AnimeFranchise, AnimeCharacter, CharacterForm,
    calculate_overall_power, get_power_tier, sanitize_for_auction
)
from src.auto_anime_importer import AnimeImportManager

class AnimeDatabaseManager:
    def __init__(self, json_path: str, db_path: str):
        self.json_path = json_path
        self.db_path = db_path
        self.franchises: Dict[str, dict] = {}
        self.characters: Dict[str, dict] = {}
        self.load_data()
        self.import_manager = AnimeImportManager(self)

    def load_data(self):
        """Loads data from JSON file into memory."""
        if not os.path.exists(self.json_path):
            raise FileNotFoundError(f"Anime database JSON not found at {self.json_path}")

        with open(self.json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        raw_franchises = data.get("franchises", {})
        if isinstance(raw_franchises, dict):
            self.franchises = raw_franchises
        else:
            self.franchises = {f["id"]: f for f in raw_franchises}

        raw_characters = data.get("characters", [])
        if isinstance(raw_characters, dict):
            self.characters = raw_characters
        else:
            self.characters = {c["id"]: c for c in raw_characters}

        print(f"[AnimeDB] Loaded {len(self.franchises)} franchises and {len(self.characters)} characters.")

    def save_data(self):
        """Persists current state back to JSON and SQLite database with full metadata."""
        # 1. Save JSON
        data = {
            "metadata": {
                "version": "2.1.0",
                "franchises_count": len(self.franchises),
                "characters_count": len(self.characters),
                "last_saved": os.path.getmtime(self.json_path) if os.path.exists(self.json_path) else None
            },
            "franchises": self.franchises,
            "characters": list(self.characters.values())
        }
        with open(self.json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        # 2. Update SQLite
        if os.path.exists(self.db_path):
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()

                # Ensure extended columns exist
                for col_name, col_type in [
                    ("anilist_id", "INTEGER"),
                    ("mal_id", "INTEGER"),
                    ("kitsu_id", "TEXT"),
                    ("alt_names_json", "TEXT"),
                    ("native_name", "TEXT"),
                    ("age", "TEXT"),
                    ("birthday", "TEXT"),
                    ("role", "TEXT"),
                    ("source_url", "TEXT"),
                    ("import_timestamp", "TEXT"),
                    ("last_updated", "TEXT"),
                    ("image_verified", "INTEGER DEFAULT 1"),
                    ("data_completeness", "TEXT"),
                    ("rating_status", "TEXT"),
                    ("favourites", "INTEGER DEFAULT 0"),
                    ("associated_anime_json", "TEXT")
                ]:
                    try:
                        cursor.execute(f"ALTER TABLE characters ADD COLUMN {col_name} {col_type}")
                    except Exception:
                        pass

                # Upsert characters
                for c in self.characters.values():
                    cursor.execute("""
                        INSERT INTO characters (
                            id, name, anime_id, anime_name, image, gender, species, race, description,
                            energy_system, power_rating, power_tier, rarity, data_confidence, source,
                            is_enabled, anilist_id, mal_id, kitsu_id, alt_names_json, native_name,
                            age, birthday, role, source_url, last_updated, image_verified,
                            data_completeness, rating_status, favourites, associated_anime_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(id) DO UPDATE SET
                            name=excluded.name,
                            anime_id=excluded.anime_id,
                            anime_name=excluded.anime_name,
                            image=excluded.image,
                            gender=excluded.gender,
                            description=excluded.description,
                            power_rating=excluded.power_rating,
                            power_tier=excluded.power_tier,
                            rarity=excluded.rarity,
                            is_enabled=excluded.is_enabled,
                            anilist_id=excluded.anilist_id,
                            mal_id=excluded.mal_id,
                            kitsu_id=excluded.kitsu_id,
                            alt_names_json=excluded.alt_names_json,
                            native_name=excluded.native_name,
                            age=excluded.age,
                            birthday=excluded.birthday,
                            source_url=excluded.source_url,
                            last_updated=excluded.last_updated,
                            image_verified=excluded.image_verified,
                            data_completeness=excluded.data_completeness,
                            rating_status=excluded.rating_status,
                            favourites=excluded.favourites,
                            associated_anime_json=excluded.associated_anime_json
                    """, (
                        c["id"], c.get("name", ""), c.get("anime_id", "anime_universe"), c.get("anime_name", "Anime"),
                        c.get("image", ""), c.get("gender", ""), c.get("species", "Human"), c.get("race", "Human"),
                        c.get("description", ""), c.get("energy_system", "Standard"), c.get("power_rating", 50.0),
                        c.get("power_tier", "B"), c.get("rarity", "Common"), c.get("data_confidence", ""),
                        c.get("source", ""), 1 if c.get("is_enabled", True) else 0,
                        c.get("anilist_id"), c.get("mal_id"), c.get("kitsu_id"),
                        json.dumps(c.get("alt_names", [])), c.get("native_name", ""),
                        c.get("age", ""), c.get("birthday", ""), c.get("role", "Main"), c.get("source_url", ""),
                        c.get("last_updated", ""), 1 if c.get("image_verified", True) else 0,
                        c.get("data_completeness", "Complete"), c.get("rating_status", "estimated_game_rating"),
                        c.get("favourites", 0), json.dumps(c.get("associated_anime", []))
                    ))

                # Upsert franchises
                for f in self.franchises.values():
                    cursor.execute("""
                        INSERT INTO franchises (id, name, japanese_name, energy_system, logo_color, description, is_enabled, character_count)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(id) DO UPDATE SET
                            name=excluded.name,
                            character_count=excluded.character_count,
                            is_enabled=excluded.is_enabled
                    """, (
                        f["id"], f["name"], f.get("japanese_name", ""), f.get("energy_system", "Standard"),
                        f.get("logo_color", "#38bdf8"), f.get("description", ""),
                        1 if f.get("is_enabled", True) else 0, f.get("character_count", 0)
                    ))
                conn.commit()
                conn.close()
            except Exception as e:
                print(f"[AnimeDB] Warning: SQLite sync failed: {e}")

    def get_all_franchises(self) -> List[dict]:
        """Returns all franchises with character counts."""
        result = []
        for fid, f in self.franchises.items():
            f_copy = copy.deepcopy(f)
            char_count = sum(1 for c in self.characters.values() if c.get("anime_id") == fid)
            active_count = sum(1 for c in self.characters.values() if c.get("anime_id") == fid and c.get("is_active", True))
            f_copy["character_count"] = char_count
            f_copy["active_character_count"] = active_count
            result.append(f_copy)
        return sorted(result, key=lambda x: x["name"])

    def get_character_by_id(self, character_id: str) -> Optional[dict]:
        return self.characters.get(character_id)

    def get_characters_for_mode(
        self,
        mode: str = "all",
        selected_anime: Optional[List[str]] = None,
        forms_mode: str = "SINGLE_BASE",
        custom_ids: Optional[List[str]] = None
    ) -> List[dict]:
        """
        Retrieves characters eligible for the chosen auction mode and forms configuration.

        Modes:
        - 'all': All characters from all active franchises
        - 'single': Only characters from the specified single franchise
        - 'multiple': Only characters from the specified list of franchises
        - 'pokemon': Only Pokemon franchise characters
        - 'custom': Explicit character IDs provided in custom_ids

        forms_mode:
        - 'SINGLE_BASE': Base characters only (forms are not separate entries)
        - 'SEPARATE_ENTRIES': Alternate forms become separate auctionable entities
        """
        eligible: List[dict] = []

        # 1. Filter base characters
        for char in self.characters.values():
            if not char.get("is_active", True):
                continue

            anime_id = char.get("anime_id")
            franchise = self.franchises.get(anime_id, {})
            if not franchise.get("is_active", True) and mode != "custom":
                continue

            match mode:
                case "pokemon":
                    if anime_id == "pokemon":
                        eligible.append(char)
                case "single":
                    if selected_anime and anime_id in selected_anime:
                        eligible.append(char)
                case "multiple":
                    if selected_anime and anime_id in selected_anime:
                        eligible.append(char)
                case "custom":
                    if custom_ids and char["id"] in custom_ids:
                        eligible.append(char)
                case "all" | _:
                    eligible.append(char)

        # 2. Expand forms if forms_mode == 'SEPARATE_ENTRIES'
        if forms_mode == "SEPARATE_ENTRIES":
            expanded: List[dict] = []
            for char in eligible:
                # Add base entry
                expanded.append(char)
                # Add alternate form entries
                for form in (char.get("forms") or []):
                    if not isinstance(form, dict):
                        continue
                    form_name = form.get("form_name") or form.get("name") or "Alternate Form"
                    form_id = form.get("form_id") or f"{char['id']}_{form_name.lower().replace(' ', '_').replace('-', '_')}"
                    form_stats = form.get("stats") or char.get("stats", {})
                    form_rating = form.get("power_rating") or calculate_overall_power(form_stats)
                    form_tier = form.get("power_tier") or get_power_tier(form_rating)
                    
                    form_entry = copy.deepcopy(char)
                    form_entry["id"] = form_id
                    form_entry["base_character_id"] = char["id"]
                    form_entry["name"] = form_name if "(" in form_name else f"{char['name']} ({form_name})"
                    form_entry["current_form"] = form_name
                    form_entry["image"] = form.get("image") or char.get("image")
                    form_entry["stats"] = form_stats
                    form_entry["power_rating"] = form_rating
                    form_entry["power_tier"] = form_tier
                    form_entry["abilities"] = form.get("abilities", char.get("abilities", []))
                    form_entry["techniques"] = form.get("techniques", char.get("techniques", []))
                    form_entry["weapons"] = form.get("weapons", char.get("weapons", []))
                    expanded.append(form_entry)
            return expanded

        return eligible

    def search_characters(
        self,
        query: str = "",
        anime_id: Optional[str] = None,
        power_tier: Optional[str] = None,
        rarity: Optional[str] = None,
        species: Optional[str] = None,
        sort: str = "power_desc",
        limit: int = 50,
        offset: int = 0
    ) -> dict:
        """Search, filter, sort, and paginate characters for catalog and admin interface."""
        items = list(self.characters.values())

        if anime_id:
            items = [c for c in items if c.get("anime_id") == anime_id]

        if power_tier:
            items = [c for c in items if c.get("power_tier") == power_tier]

        if rarity:
            items = [c for c in items if c.get("rarity") == rarity]

        if species:
            sp = species.lower()
            items = [c for c in items if sp in c.get("species", "").lower() or sp in c.get("race", "").lower()]

        if query:
            q = query.strip().lower()
            def matches(c):
                name = (c.get("name") or "").lower()
                if q in name:
                    return True
                anime_name = (c.get("anime_name") or "").lower()
                if q in anime_name:
                    return True
                native_name = (c.get("native_name") or "").lower()
                if q in native_name:
                    return True
                for alt in (c.get("alt_names") or []):
                    if q in str(alt).lower():
                        return True
                for a in (c.get("associated_anime") or []):
                    if isinstance(a, dict) and q in (a.get("title") or "").lower():
                        return True
                    elif isinstance(a, str) and q in a.lower():
                        return True
                cid = (c.get("id") or "").lower()
                if q in cid:
                    return True
                desc = (c.get("description") or "").lower()
                if q in desc:
                    return True
                energy = (c.get("energy_system") or "").lower()
                if q in energy:
                    return True
                for t in (c.get("techniques") or []):
                    if q in str(t).lower():
                        return True
                for a in (c.get("abilities") or []):
                    if q in str(a).lower():
                        return True
                return False
            items = [c for c in items if matches(c)]

        # Sorting
        if sort == "power_desc":
            items.sort(key=lambda x: x.get("power_rating", 0), reverse=True)
        elif sort == "power_asc":
            items.sort(key=lambda x: x.get("power_rating", 0))
        elif sort == "name_asc":
            items.sort(key=lambda x: x.get("name", "").lower())
        elif sort == "name_desc":
            items.sort(key=lambda x: x.get("name", "").lower(), reverse=True)
        elif sort == "franchise_asc":
            items.sort(key=lambda x: (x.get("anime_name", "").lower(), -x.get("power_rating", 0)))

        total = len(items)
        paged = items[offset:offset + limit]

        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "characters": paged
        }

    def get_database_stats(self) -> dict:
        """Returns accurate database metrics directly from indexed records."""
        total_franchises = len(self.franchises)
        total_characters = len(self.characters)
        pokemon_count = sum(1 for c in self.characters.values() if c.get("anime_id") == "pokemon")
        anime_count = total_characters - pokemon_count
        total_forms = sum(len(c.get("forms", [])) for c in self.characters.values())
        with_images = sum(1 for c in self.characters.values() if bool(c.get("image")))
        with_power = sum(1 for c in self.characters.values() if bool(c.get("power_rating")))

        tier_counts = {"S+": 0, "S": 0, "A": 0, "B": 0, "C": 0, "D": 0}
        for c in self.characters.values():
            tier = c.get("power_tier", "B")
            if tier in tier_counts:
                tier_counts[tier] += 1

        return {
            "total_franchises": total_franchises,
            "total_characters": total_characters,
            "pokemon_count": pokemon_count,
            "anime_count": anime_count,
            "total_character_forms": total_forms,
            "characters_with_images": with_images,
            "characters_with_power_data": with_power,
            "tier_counts": tier_counts
        }

    def reload(self):
        """Reload database from disk."""
        self.load_data()

    def scan_duplicates(self) -> dict:
        """Scans for potential duplicate characters across franchises."""
        from collections import defaultdict
        seen_names = defaultdict(list)
        duplicates = []
        for cid, char in self.characters.items():
            fid = char.get("anime_id", "")
            norm_name = char.get("name", "").strip().lower()
            key = f"{fid}::{norm_name}"
            seen_names[key].append(cid)

        for key, ids in seen_names.items():
            if len(ids) > 1:
                fid, name = key.split("::", 1)
                duplicates.append({
                    "anime_id": fid,
                    "name": name,
                    "ids": ids,
                    "count": len(ids)
                })
        return {
            "total_duplicates": len(duplicates),
            "duplicates": duplicates,
            "message": "Zero duplicates found" if not duplicates else f"Found {len(duplicates)} duplicate entries"
        }

    def repair_images(self) -> dict:
        """Verifies and fixes character images."""
        verified = 0
        missing = 0
        for cid, char in self.characters.items():
            img = (char.get("image") or "").strip()
            if not img or img.startswith("/api/avatar") or "ui-avatars" in img:
                missing += 1
            else:
                char["image_verified"] = 1
                verified += 1
        return {
            "total_checked": len(self.characters),
            "verified_images": verified,
            "missing_images": missing,
            "message": f"Audit complete: {verified} verified images, {missing} missing/fallback"
        }

    def generate_audit_report(self, output_path: Optional[str] = None) -> dict:
        """Generates franchise audit report comparing character counts against target."""
        import datetime
        report = []
        for fid, f in self.franchises.items():
            chars = [c for c in self.characters.values() if c.get("anime_id") == fid]
            names = set(c["name"].strip().lower() for c in chars)
            verified_imgs = sum(1 for c in chars if c.get("image") and not c.get("image", "").startswith("/api/avatar"))
            target = 50 if fid != "pokemon" else 1351
            status = "REACHED TARGET" if len(names) >= target else f"BELOW TARGET ({len(names)}/{target})"
            report.append({
                "franchise_id": fid,
                "name": f.get("name", fid),
                "total_records": len(chars),
                "unique_characters": len(names),
                "verified_images": verified_imgs,
                "missing_images": len(chars) - verified_imgs,
                "target": target,
                "status": status
            })
        report.sort(key=lambda x: x["unique_characters"], reverse=True)
        res = {
            "timestamp": datetime.datetime.now().isoformat(),
            "total_franchises": len(self.franchises),
            "total_characters": len(self.characters),
            "franchise_audit": report
        }
        if output_path:
            with open(output_path, "w", encoding="utf-8") as fp:
                json.dump(res, fp, indent=2, ensure_ascii=False)
        return res

    def toggle_character(self, character_id: str, is_active: Optional[bool] = None) -> bool:
        """Toggles active status of a character."""
        char = self.characters.get(character_id)
        if not char:
            return False
        if is_active is None:
            char["is_active"] = not char.get("is_active", True)
        else:
            char["is_active"] = bool(is_active)
        self.save_data()
        return True

    def toggle_franchise(self, anime_id: str, is_active: Optional[bool] = None) -> bool:
        """Toggles active status of an entire franchise."""
        franchise = self.franchises.get(anime_id)
        if not franchise:
            return False
        if is_active is None:
            franchise["is_active"] = not franchise.get("is_active", True)
        else:
            franchise["is_active"] = bool(is_active)
        self.save_data()
        return True

    def update_character_stats(self, character_id: str, updates: dict) -> Optional[dict]:
        """Admin updates for character stats or properties."""
        char = self.characters.get(character_id)
        if not char:
            return None

        # Allow updating stats
        if "stats" in updates and isinstance(updates["stats"], dict):
            for k, v in updates["stats"].items():
                if k in char["stats"]:
                    try:
                        char["stats"][k] = max(1, min(100, int(v)))
                    except (ValueError, TypeError):
                        pass
            # Recalculate power rating & tier
            char["power_rating"] = calculate_overall_power(char["stats"])
            char["power_tier"] = get_power_tier(char["power_rating"])

        if "name" in updates and updates["name"]:
            char["name"] = str(updates["name"]).strip()
        if "image" in updates and updates["image"]:
            char["image"] = str(updates["image"]).strip()
        if "description" in updates:
            char["description"] = str(updates["description"]).strip()
        if "is_active" in updates:
            char["is_active"] = bool(updates["is_active"])

        self.save_data()
        return char
