"""
Marvel Character Data Importer (Phase 6)
========================================
Discovers and imports Marvel Comics & MCU characters into data/marvel_characters_raw.json.
- Uses Official Marvel Developer API v1 when MARVEL_PUBLIC_KEY and MARVEL_PRIVATE_KEY
  environment variables are set (with pagination, MD5 auth, retries, rate-limit backoff, and caching).
- Never exposes MARVEL_PRIVATE_KEY to frontend, logs, or committed files.
- Falls back cleanly to a documented offline Marvel seed catalog when API keys are unavailable.
- Distinguishes Earth-616 Comics incarnations from MCU (Earth-199999) incarnations.
- Separates character discovery from combat eligibility.
"""

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(BASE_DIR, "cache")
DATA_DIR = os.path.join(BASE_DIR, "data")
MARVEL_RAW_PATH = os.path.join(DATA_DIR, "marvel_characters_raw.json")
MARVEL_CACHE_PATH = os.path.join(CACHE_DIR, "marvel_api_cache.json")

MARVEL_API_BASE = "https://gateway.marvel.com/v1/public/characters"
MARVEL_ATTRIBUTION = "Data provided by Marvel. © 2024 Marvel"


def _seed_offline_marvel_catalog() -> List[Dict[str, Any]]:
    """
    Documented offline Marvel seed catalog used when MARVEL_PUBLIC_KEY /
    MARVEL_PRIVATE_KEY are not configured. Clearly separates Comics (Earth-616)
    from MCU (Earth-199999) and separates non-combatant discovery entries.
    """
    def _m(
        mid: str,
        marvel_id: int,
        name: str,
        incarnation: str,
        desc: str,
        aliases: List[str],
        comics: List[str],
        series: List[str],
        events: List[str],
        source: str,
        combat_capable: bool = True,
    ) -> Dict[str, Any]:
        return {
            "id": mid,
            "marvel_id": marvel_id,
            "name": name,
            "incarnation": incarnation,
            "universe": "marvel",
            "anime_id": "marvel",
            "anime_name": "Marvel Comics",
            "description": desc,
            "image": f"/api/avatar/{mid}",
            "aliases": aliases,
            "comics": comics,
            "series": series,
            "events": events,
            "source": source,
            "attribution": MARVEL_ATTRIBUTION,
            "is_combat_capable": combat_capable,
        }

    return [
        # --- HEROES (Earth-616 Comics) ---
        _m("marvel_616_spider_man", 1009610, "Spider-Man (Earth-616)", "Earth-616 (Comics)", "Peter Parker, bitten by a radioactive spider, gaining spider-sense and wall-crawling.", ["Peter Parker", "Web-Head"], ["Amazing Fantasy #15", "Amazing Spider-Man"], ["The Amazing Spider-Man"], ["Spider-Verse", "Civil War"], "Official Handbook of the Marvel Universe (Earth-616)"),
        _m("marvel_616_iron_man", 1009368, "Iron Man (Earth-616)", "Earth-616 (Comics)", "Tony Stark, genius billionaire engineer piloting powered repulsor armor.", ["Tony Stark", "Shellhead"], ["Tales of Suspense #39", "Invincible Iron Man"], ["Iron Man"], ["Armor Wars", "Civil War"], "Official Handbook of the Marvel Universe (Earth-616)"),
        _m("marvel_616_captain_america", 1009220, "Captain America (Earth-616)", "Earth-616 (Comics)", "Steve Rogers, enhanced by the Super-Soldier Serum and wielding a Vibranium shield.", ["Steve Rogers", "Sentinel of Liberty"], ["Captain America Comics #1"], ["Captain America"], ["Secret Empire", "Civil War"], "Official Handbook of the Marvel Universe (Earth-616)"),
        _m("marvel_616_thor", 1009664, "Thor Odinson (Earth-616)", "Earth-616 (Comics)", "Asgardian God of Thunder wielding the enchanted hammer Mjolnir.", ["Odinson", "God of Thunder"], ["Journey into Mystery #83"], ["Thor"], ["War of the Realms", "Fear Itself"], "Official Handbook of the Marvel Universe (Earth-616)"),
        _m("marvel_616_hulk", 1009351, "Hulk (Earth-616)", "Earth-616 (Comics)", "Bruce Banner, transformed by gamma radiation into a powerhouse whose strength scales with rage.", ["Bruce Banner", "Green Scar"], ["Incredible Hulk #1"], ["The Incredible Hulk"], ["World War Hulk", "Planet Hulk"], "Official Handbook of the Marvel Universe (Earth-616)"),
        _m("marvel_616_doctor_strange", 1009282, "Doctor Strange (Earth-616)", "Earth-616 (Comics)", "Stephen Strange, Sorcerer Supreme of Earth wielding mystic arts and the Eye of Agamotto.", ["Stephen Strange", "Sorcerer Supreme"], ["Strange Tales #110"], ["Doctor Strange"], ["Secret Wars", "Damnation"], "Official Handbook of the Marvel Universe (Earth-616)"),
        _m("marvel_616_scarlet_witch", 1009562, "Scarlet Witch (Earth-616)", "Earth-616 (Comics)", "Wanda Maximoff, Nexus Being wielding Chaos Magic and probability manipulation.", ["Wanda Maximoff"], ["X-Men #4"], ["Scarlet Witch", "Avengers"], ["House of M", "Avengers Disassembled"], "Official Handbook of the Marvel Universe (Earth-616)"),
        _m("marvel_616_wolverine", 1009718, "Wolverine (Earth-616)", "Earth-616 (Comics)", "Logan, mutant with an Adamantium-laced skeleton, retractable claws, and healing factor.", ["Logan", "James Howlett", "Weapon X"], ["Incredible Hulk #181"], ["Wolverine", "Uncanny X-Men"], ["Old Man Logan", "House of X"], "Official Handbook of the Marvel Universe (Earth-616)"),
        _m("marvel_616_deadpool", 1009268, "Deadpool (Earth-616)", "Earth-616 (Comics)", "Wade Wilson, mercenary with an accelerated healing factor and unpredictable martial skill.", ["Wade Wilson", "Merc with a Mouth"], ["New Mutants #98"], ["Deadpool"], ["Deadpool Kills the Marvel Universe"], "Official Handbook of the Marvel Universe (Earth-616)"),
        _m("marvel_616_captain_marvel", 1010338, "Captain Marvel (Earth-616)", "Earth-616 (Comics)", "Carol Danvers, cosmic powerhouse capable of photon energy projection and Binary form.", ["Carol Danvers", "Binary"], ["Marvel Super-Heroes #13"], ["Captain Marvel"], ["Civil War II", "Empyre"], "Official Handbook of the Marvel Universe (Earth-616)"),
        _m("marvel_616_black_panther", 1009187, "Black Panther (Earth-616)", "Earth-616 (Comics)", "T'Challa, King of Wakanda enhanced by the Heart-Shaped Herb and Vibranium habit.", ["T'Challa", "King of the Dead"], ["Fantastic Four #52"], ["Black Panther"], ["Secret Wars", "Avengers vs. X-Men"], "Official Handbook of the Marvel Universe (Earth-616)"),
        _m("marvel_616_ant_man", 1010802, "Ant-Man (Scott Lang, Earth-616)", "Earth-616 (Comics)", "Scott Lang, using Pym Particles to shrink or grow to Giant-Man scale.", ["Scott Lang"], ["Avengers #181"], ["Ant-Man"], ["Secret Empire"], "Official Handbook of the Marvel Universe (Earth-616)"),
        _m("marvel_616_daredevil", 1009262, "Daredevil (Earth-616)", "Earth-616 (Comics)", "Matt Murdock, blind martial artist with hyper-acute radar sense.", ["Matt Murdock", "Man Without Fear"], ["Daredevil #1"], ["Daredevil"], ["Shadowland", "Devil's Reign"], "Official Handbook of the Marvel Universe (Earth-616)"),
        _m("marvel_616_vision", 1009697, "Vision (Earth-616)", "Earth-616 (Comics)", "Synthezoid capable of density manipulation, intangibility, and solar-beam projection.", ["Victor Shade"], ["Avengers #57"], ["The Vision", "Avengers"], ["Avengers: Age of Ultron (Comics)"], "Official Handbook of the Marvel Universe (Earth-616)"),
        # --- VILLAINS (Earth-616 Comics) ---
        _m("marvel_616_thanos", 1009652, "Thanos (Earth-616)", "Earth-616 (Comics)", "Mad Titan of Titan possessing immense cosmic strength, intellect, and energy manipulation.", ["Mad Titan"], ["Iron Man #55"], ["Infinity Gauntlet", "Thanos"], ["The Infinity Gauntlet", "Infinity"], "Official Handbook of the Marvel Universe (Earth-616)"),
        _m("marvel_616_loki", 1009407, "Loki Laufeyson (Earth-616)", "Earth-616 (Comics)", "Asgardian God of Mischief, master sorcerer and illusionist.", ["God of Mischief"], ["Journey into Mystery #85"], ["Loki: Agent of Asgard"], ["Siege", "War of the Realms"], "Official Handbook of the Marvel Universe (Earth-616)"),
        _m("marvel_616_ultron", 1009685, "Ultron (Earth-616)", "Earth-616 (Comics)", "Self-evolving Adamantium AI constructed by Hank Pym.", ["Ultron-1", "Crimson Cowl"], ["Avengers #54"], ["Avengers"], ["Age of Ultron", "Annihilation: Conquest"], "Official Handbook of the Marvel Universe (Earth-616)"),
        _m("marvel_616_doctor_doom", 1009281, "Doctor Doom (Earth-616)", "Earth-616 (Comics)", "Victor Von Doom, ruler of Latveria combining supreme scientific armor and dark sorcery.", ["Victor Von Doom"], ["Fantastic Four #5"], ["Fantastic Four", "Infamous Iron Man"], ["Secret Wars (2015)"], "Official Handbook of the Marvel Universe (Earth-616)"),
        _m("marvel_616_magneto", 1009417, "Magneto (Earth-616)", "Earth-616 (Comics)", "Max Eisenhardt, Omega-level mutant master of electromagnetism.", ["Erik Lehnsherr", "Master of Magnetism"], ["X-Men #1"], ["Uncanny X-Men", "X-Men Red"], ["Fatal Attractions", "House of M"], "Official Handbook of the Marvel Universe (Earth-616)"),
        _m("marvel_616_green_goblin", 1014985, "Green Goblin (Earth-616)", "Earth-616 (Comics)", "Norman Osborn, enhanced by the Goblin Formula with glider and pumpkin bombs.", ["Norman Osborn"], ["Amazing Spider-Man #14"], ["Amazing Spider-Man", "Dark Avengers"], ["Dark Reign"], "Official Handbook of the Marvel Universe (Earth-616)"),
        _m("marvel_616_venom", 1009663, "Venom (Eddie Brock, Earth-616)", "Earth-616 (Comics)", "Eddie Brock bonded with the Klyntar Symbiote.", ["Eddie Brock", "Lethal Protector"], ["Amazing Spider-Man #300"], ["Venom"], ["King in Black", "Absolute Carnage"], "Official Handbook of the Marvel Universe (Earth-616)"),
        _m("marvel_616_red_skull", 1009535, "Red Skull (Earth-616)", "Earth-616 (Comics)", "Johann Schmidt, HYDRA mastermind wielding the Dust of Death.", ["Johann Schmidt"], ["Captain America Comics #7"], ["Captain America"], ["Axis"], "Official Handbook of the Marvel Universe (Earth-616)"),
        _m("marvel_616_kang", 1009384, "Kang the Conqueror (Earth-616)", "Earth-616 (Comics)", "Nathaniel Richards, 31st-century time-traveling conqueror in advanced battle armor.", ["Nathaniel Richards", "Immortus"], ["Avengers #8"], ["Avengers", "Kang the Conqueror"], ["Kang Dynasty"], "Official Handbook of the Marvel Universe (Earth-616)"),
        _m("marvel_616_galactus", 1009312, "Galactus (Earth-616)", "Earth-616 (Comics)", "Galan of Taa, Cosmic Entity wielding the Power Cosmic.", ["Devourer of Worlds", "Galan"], ["Fantastic Four #48"], ["Fantastic Four", "Silver Surfer"], ["Annihilation"], "Official Handbook of the Marvel Universe (Earth-616)"),
        # --- DISTINCT MCU INCARNATIONS (Earth-199999) ---
        _m("marvel_mcu_iron_man", 2009368, "Iron Man (MCU)", "Earth-199999 (MCU)", "MCU Tony Stark piloting Mark LXXXV nanotech armor.", ["Tony Stark (MCU)"], [], ["Iron Man (2008)", "Avengers: Endgame"], ["Infinity Saga (MCU)"], "Marvel Cinematic Universe Official Canon"),
        _m("marvel_mcu_thanos", 2009652, "Thanos (MCU)", "Earth-199999 (MCU)", "MCU Warlord of Titan wielding double-edged Uru sword and Infinity Gauntlet.", ["Thanos (MCU)"], [], ["Avengers: Infinity War", "Avengers: Endgame"], ["Infinity Saga (MCU)"], "Marvel Cinematic Universe Official Canon"),
        # --- NON-COMBAT / INCOMPLETE DISCOVERY RECORDS (Separated from Combat Eligibility) ---
        _m("marvel_616_aunt_may", 1009490, "Aunt May (Earth-616)", "Earth-616 (Comics)", "May Parker, Peter Parker's supportive aunt; civilian non-combatant.", ["May Parker"], ["Amazing Fantasy #15"], ["The Amazing Spider-Man"], [], "Official Handbook of the Marvel Universe (Earth-616)", combat_capable=False),
        _m("marvel_616_jjj", 1009372, "J. Jonah Jameson (Earth-616)", "Earth-616 (Comics)", "Editor-in-chief of the Daily Bugle; civilian non-combatant.", ["J.J.J."], ["Amazing Spider-Man #1"], ["The Amazing Spider-Man"], [], "Official Handbook of the Marvel Universe (Earth-616)", combat_capable=False),
    ]


class MarvelCharacterImporter:
    """Fetches Marvel characters from the official API (if keys exist) or offline catalog."""

    def __init__(self, public_key: Optional[str] = None, private_key: Optional[str] = None):
        self.public_key = public_key if public_key is not None else os.environ.get("MARVEL_PUBLIC_KEY", "")
        self.private_key = private_key if private_key is not None else os.environ.get("MARVEL_PRIVATE_KEY", "")
        self.errors: List[str] = []

    @property
    def has_api_credentials(self) -> bool:
        return bool(self.public_key and self.private_key)

    def _build_auth_params(self) -> Dict[str, str]:
        ts = str(int(time.time()))
        digest = hashlib.md5(f"{ts}{self.private_key}{self.public_key}".encode("utf-8")).hexdigest()
        return {"ts": ts, "apikey": self.public_key, "hash": digest}

    def fetch_api_page(self, offset: int = 0, limit: int = 100, retries: int = 3) -> Optional[dict]:
        """Fetches a single paginated batch from Marvel Developer API with retries & rate-limit backoff."""
        if not self.has_api_credentials:
            return None
        params = self._build_auth_params()
        params["limit"] = str(limit)
        params["offset"] = str(offset)
        url = f"{MARVEL_API_BASE}?{urllib.parse.urlencode(params)}"

        for attempt in range(retries):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "PokemonAnimeAuctionArena/1.0"})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    time.sleep(2 ** attempt)
                    continue
                self.errors.append(f"Marvel API HTTP {e.code} at offset={offset}")
                return None
            except Exception as e:
                if attempt == retries - 1:
                    self.errors.append(f"Marvel API error at offset={offset}: {type(e).__name__}")
                    return None
                time.sleep(1.0)
        return None

    def _normalize_api_character(self, raw: dict) -> dict:
        mid = f"marvel_api_{raw['id']}"
        thumb = raw.get("thumbnail") or {}
        img = ""
        if thumb.get("path") and thumb.get("extension") and "image_not_available" not in thumb["path"]:
            img = f"{thumb['path']}.{thumb['extension']}".replace("http://", "https://")
        else:
            img = f"/api/avatar/{mid}"

        return {
            "id": mid,
            "marvel_id": raw["id"],
            "name": raw.get("name", f"Marvel #{raw['id']}"),
            "incarnation": "Earth-616 (Marvel API)",
            "universe": "marvel",
            "anime_id": "marvel",
            "anime_name": "Marvel Comics",
            "description": (raw.get("description") or "").strip(),
            "image": img,
            "aliases": [],
            "comics": [c["name"] for c in (raw.get("comics", {}).get("items") or [])[:10]],
            "series": [s["name"] for s in (raw.get("series", {}).get("items") or [])[:10]],
            "events": [e["name"] for e in (raw.get("events", {}).get("items") or [])[:10]],
            "source": "Marvel Developer API v1",
            "attribution": MARVEL_ATTRIBUTION,
            "is_combat_capable": False,  # Requires verified combat enrichment before battle
        }

    def import_characters(self, max_pages: int = 2, use_cache: bool = True) -> Dict[str, Any]:
        os.makedirs(CACHE_DIR, exist_ok=True)
        os.makedirs(DATA_DIR, exist_ok=True)

        characters_by_key: Dict[Tuple[str, str], dict] = {}
        seen_marvel_ids: set = set()
        duplicates_skipped = 0
        import_mode = "offline_documented_seed"

        # 1. Always include documented offline seed catalog first
        for entry in _seed_offline_marvel_catalog():
            key = (entry["name"].strip().lower(), entry["incarnation"].strip().lower())
            mid = entry.get("marvel_id")
            if key in characters_by_key or (mid is not None and mid in seen_marvel_ids):
                duplicates_skipped += 1
                continue
            characters_by_key[key] = entry
            if mid is not None:
                seen_marvel_ids.add(mid)

        # 2. Optionally fetch from Official Marvel Developer API if credentials are configured
        api_fetched = 0
        if self.has_api_credentials:
            import_mode = "marvel_developer_api_v1"
            if use_cache and os.path.exists(MARVEL_CACHE_PATH):
                with open(MARVEL_CACHE_PATH, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                for raw in cached:
                    norm = self._normalize_api_character(raw)
                    key = (norm["name"].strip().lower(), norm["incarnation"].strip().lower())
                    mid = norm.get("marvel_id")
                    if key not in characters_by_key and (mid is None or mid not in seen_marvel_ids):
                        characters_by_key[key] = norm
                        if mid is not None:
                            seen_marvel_ids.add(mid)
                        api_fetched += 1
                    else:
                        duplicates_skipped += 1
            else:
                raw_api_list: List[dict] = []
                for page in range(max_pages):
                    payload = self.fetch_api_page(offset=page * 100, limit=100)
                    if not payload:
                        break
                    results = (payload.get("data") or {}).get("results") or []
                    if not results:
                        break
                    raw_api_list.extend(results)
                    for raw in results:
                        norm = self._normalize_api_character(raw)
                        key = (norm["name"].strip().lower(), norm["incarnation"].strip().lower())
                        mid = norm.get("marvel_id")
                        if key not in characters_by_key and (mid is None or mid not in seen_marvel_ids):
                            characters_by_key[key] = norm
                            if mid is not None:
                                seen_marvel_ids.add(mid)
                            api_fetched += 1
                        else:
                            duplicates_skipped += 1
                if raw_api_list:
                    with open(MARVEL_CACHE_PATH, "w", encoding="utf-8") as f:
                        json.dump(raw_api_list, f, indent=2, ensure_ascii=False)

        records = list(characters_by_key.values())
        out_payload = {
            "metadata": {
                "version": "1.0.0",
                "universe": "marvel",
                "import_mode": import_mode,
                "attribution": MARVEL_ATTRIBUTION,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "total_characters": len(records),
                "api_fetched": api_fetched,
                "duplicates_skipped": duplicates_skipped,
                "errors": self.errors,
            },
            "characters": records,
        }
        with open(MARVEL_RAW_PATH, "w", encoding="utf-8") as f:
            json.dump(out_payload, f, indent=2, ensure_ascii=False)

        return out_payload["metadata"]


if __name__ == "__main__":
    importer = MarvelCharacterImporter()
    print(json.dumps(importer.import_characters(), indent=2))
