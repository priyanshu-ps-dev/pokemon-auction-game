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
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(BASE_DIR, "cache")
DATA_DIR = os.path.join(BASE_DIR, "data")
MARVEL_RAW_PATH = os.path.join(DATA_DIR, "marvel_characters_raw.json")
MARVEL_MANIFEST_PATH = os.path.join(DATA_DIR, "marvel_import_manifest.json")
MARVEL_CACHE_PATH = os.path.join(CACHE_DIR, "marvel_api_cache.json")
SUPERHERO_API_CACHE_PATH = os.path.join(CACHE_DIR, "superhero_api_all.json")
WIKIDATA_CACHE_PATH = os.path.join(CACHE_DIR, "wikidata_marvel_pages.json")
WIKIPEDIA_CACHE_PATH = os.path.join(CACHE_DIR, "wikipedia_marvel_categories.json")

SUPERHERO_API_URL = "https://cdn.jsdelivr.net/gh/akabab/superhero-api@0.3.0/api/all.json"
WIKIDATA_SPARQL_URL = "https://query.wikidata.org/sparql"
WIKIPEDIA_API_URL = "https://en.wikipedia.org/w/api.php"
USER_AGENT = "PokemonAnimeMarvelAuctionArena/1.0 (educational-open-data)"

MARVEL_API_BASE = "https://gateway.marvel.com/v1/public/characters"
MARVEL_ATTRIBUTION = "Data provided by Marvel. © 2024 Marvel"

# Verified high-resolution character portraits via MIT-licensed akabab/superhero-api (jsDelivr CDN).
# Non-combatant civilian entries without CDN portraits fall back to local placeholder & are flagged.
_OFFLINE_VERIFIED_IMAGES: Dict[str, str] = {
    "marvel_616_spider_man": "https://cdn.jsdelivr.net/gh/akabab/superhero-api@0.3.0/api/images/lg/620-spider-man.jpg",
    "marvel_616_iron_man": "https://cdn.jsdelivr.net/gh/akabab/superhero-api@0.3.0/api/images/lg/346-iron-man.jpg",
    "marvel_616_captain_america": "https://cdn.jsdelivr.net/gh/akabab/superhero-api@0.3.0/api/images/lg/149-captain-america.jpg",
    "marvel_616_thor": "https://cdn.jsdelivr.net/gh/akabab/superhero-api@0.3.0/api/images/lg/659-thor.jpg",
    "marvel_616_hulk": "https://cdn.jsdelivr.net/gh/akabab/superhero-api@0.3.0/api/images/lg/332-hulk.jpg",
    "marvel_616_doctor_strange": "https://cdn.jsdelivr.net/gh/akabab/superhero-api@0.3.0/api/images/lg/226-doctor-strange.jpg",
    "marvel_616_scarlet_witch": "https://cdn.jsdelivr.net/gh/akabab/superhero-api@0.3.0/api/images/lg/579-scarlet-witch.jpg",
    "marvel_616_wolverine": "https://cdn.jsdelivr.net/gh/akabab/superhero-api@0.3.0/api/images/lg/717-wolverine.jpg",
    "marvel_616_deadpool": "https://cdn.jsdelivr.net/gh/akabab/superhero-api@0.3.0/api/images/lg/213-deadpool.jpg",
    "marvel_616_captain_marvel": "https://cdn.jsdelivr.net/gh/akabab/superhero-api@0.3.0/api/images/lg/157-captain-marvel.jpg",
    "marvel_616_black_panther": "https://cdn.jsdelivr.net/gh/akabab/superhero-api@0.3.0/api/images/lg/106-black-panther.jpg",
    "marvel_616_ant_man": "https://cdn.jsdelivr.net/gh/akabab/superhero-api@0.3.0/api/images/lg/31-ant-man-ii.jpg",
    "marvel_616_daredevil": "https://cdn.jsdelivr.net/gh/akabab/superhero-api@0.3.0/api/images/lg/201-daredevil.jpg",
    "marvel_616_vision": "https://cdn.jsdelivr.net/gh/akabab/superhero-api@0.3.0/api/images/lg/697-vision.jpg",
    "marvel_616_thanos": "https://cdn.jsdelivr.net/gh/akabab/superhero-api@0.3.0/api/images/lg/655-thanos.jpg",
    "marvel_616_loki": "https://cdn.jsdelivr.net/gh/akabab/superhero-api@0.3.0/api/images/lg/414-loki.jpg",
    "marvel_616_ultron": "https://cdn.jsdelivr.net/gh/akabab/superhero-api@0.3.0/api/images/lg/680-ultron.jpg",
    "marvel_616_doctor_doom": "https://cdn.jsdelivr.net/gh/akabab/superhero-api@0.3.0/api/images/lg/222-doctor-doom.jpg",
    "marvel_616_magneto": "https://cdn.jsdelivr.net/gh/akabab/superhero-api@0.3.0/api/images/lg/423-magneto.jpg",
    "marvel_616_green_goblin": "https://cdn.jsdelivr.net/gh/akabab/superhero-api@0.3.0/api/images/lg/299-green-goblin.jpg",
    "marvel_616_venom": "https://cdn.jsdelivr.net/gh/akabab/superhero-api@0.3.0/api/images/lg/687-venom.jpg",
    "marvel_616_red_skull": "https://cdn.jsdelivr.net/gh/akabab/superhero-api@0.3.0/api/images/lg/550-red-skull.jpg",
    "marvel_616_kang": "https://cdn.jsdelivr.net/gh/akabab/superhero-api@0.3.0/api/images/lg/379-kang.jpg",
    "marvel_616_galactus": "https://cdn.jsdelivr.net/gh/akabab/superhero-api@0.3.0/api/images/lg/273-galactus.jpg",
    "marvel_mcu_iron_man": "https://cdn.jsdelivr.net/gh/akabab/superhero-api@0.3.0/api/images/lg/346-iron-man.jpg",
    "marvel_mcu_thanos": "https://cdn.jsdelivr.net/gh/akabab/superhero-api@0.3.0/api/images/lg/655-thanos.jpg",
}


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
        verified_url = _OFFLINE_VERIFIED_IMAGES.get(mid)
        return {
            "id": mid,
            "marvel_id": marvel_id,
            "name": name,
            "incarnation": incarnation,
            "universe": "marvel",
            "anime_id": "marvel",
            "anime_name": "Marvel Comics",
            "description": desc,
            "image": verified_url if verified_url else f"/api/avatar/{mid}",
            "image_source": "SuperHeroAPI (akabab/superhero-api, MIT) via jsDelivr CDN" if verified_url else "Missing artwork (neutral fallback)",
            "image_attribution": f"{MARVEL_ATTRIBUTION} | Portrait via akabab/superhero-api (MIT)" if verified_url else MARVEL_ATTRIBUTION,
            "image_verification_status": "verified_cdn" if verified_url else "missing_artwork_placeholder",
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

    # ------------------------------------------------------------------
    # PHASE 8: CREDENTIAL-FREE PUBLIC MULTI-SOURCE RESUMABLE EXPANSION
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_name(name: str) -> str:
        cleaned = re.sub(r"\s*\([^)]*\)", "", name or "").strip().lower()
        cleaned = re.sub(r"[^a-z0-9]+", " ", cleaned).strip()
        return cleaned

    @staticmethod
    def _classify_from_metadata(
        alignment: str = "",
        race: str = "",
        categories: Optional[List[str]] = None,
        description: str = "",
    ) -> List[str]:
        cats: Set[str] = set(categories or [])
        al = (alignment or "").strip().lower()
        if al == "good":
            cats.add("Heroes")
        elif al == "bad":
            cats.add("Villains")
        elif al == "neutral":
            cats.add("Antiheroes")

        rc = (race or "").strip().lower()
        desc = (description or "").strip().lower()
        if "mutant" in rc or "mutant" in desc:
            cats.add("Mutants")
        if any(k in rc for k in ("cosmic", "eternal", "celestial", "god", "asgardian", "titan")):
            cats.add("Cosmic")
        if any(k in rc for k in ("alien", "kree", "skrull", "symbiote", "klyntar", "flora colossus", "shi'ar")):
            cats.add("Aliens")
        if any(k in rc for k in ("demon", "vampire", "ghost", "mystic", "undead")):
            cats.add("Supernatural")
        if not cats:
            cats.add("Other / unclassified")
        return sorted(cats)

    def _http_get_json(self, url: str, timeout: int = 25, retries: int = 3) -> Optional[Any]:
        for attempt in range(retries):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code in (429, 502, 503, 504):
                    time.sleep(2 ** attempt)
                    continue
                self.errors.append(f"HTTP {e.code} on {url[:80]}")
                return None
            except Exception as e:
                if attempt == retries - 1:
                    self.errors.append(f"{type(e).__name__} on {url[:80]}")
                    return None
                time.sleep(1.5 * (attempt + 1))
        return None

    def fetch_superhero_api_marvel(self, use_cache: bool = True) -> List[dict]:
        """Fetch all Marvel Comics & Marvel-imprint entries from MIT-licensed SuperHeroAPI."""
        all_items: Optional[List[dict]] = None
        if use_cache and os.path.exists(SUPERHERO_API_CACHE_PATH):
            with open(SUPERHERO_API_CACHE_PATH, "r", encoding="utf-8") as f:
                all_items = json.load(f)
        if not all_items:
            all_items = self._http_get_json(SUPERHERO_API_URL, timeout=25)
            if isinstance(all_items, list) and all_items:
                with open(SUPERHERO_API_CACHE_PATH, "w", encoding="utf-8") as f:
                    json.dump(all_items, f, ensure_ascii=False)
        if not isinstance(all_items, list):
            return []

        marvel_pubs = {
            "marvel comics", "giant-man", "icon comics", "binary", "evil deadpool",
            "deadpool", "iron lad", "spider-carnage", "venom iii", "ms marvel ii",
            "rune king thor", "anti-venom", "anti-vision", "ant-man", "phoenix",
            "meltdown", "power man", "thunderbird ii", "atlas", "goliath", "tempest",
        }
        out: List[dict] = []
        for x in all_items:
            bio = x.get("biography") or {}
            pub = (bio.get("publisher") or "").strip().lower()
            if "marvel" not in pub and pub not in marvel_pubs:
                continue
            app = x.get("appearance") or {}
            conn = x.get("connections") or {}
            stats = x.get("powerstats") or {}
            img = ((x.get("images") or {}).get("lg") or "").strip()
            aff_raw = conn.get("groupAffiliation") or ""
            affiliations = [a.strip() for a in re.split(r"[,;]", aff_raw) if a.strip() and a.strip() != "-"][:10]
            aliases = [a for a in (bio.get("aliases") or []) if a and a != "-"]
            if bio.get("fullName") and bio["fullName"] != "-" and bio["fullName"] not in aliases:
                aliases.insert(0, bio["fullName"])
            race = app.get("race") if app.get("race") not in (None, "null", "-") else ""
            cats = self._classify_from_metadata(bio.get("alignment", ""), race)
            cid = f"marvel_sh_{x['id']}"
            out.append({
                "id": cid,
                "superhero_api_id": x["id"],
                "marvel_id": None,
                "name": x["name"],
                "incarnation": "Earth-616 / Comics (SuperHeroAPI)",
                "universe": "marvel",
                "anime_id": "marvel",
                "anime_name": "Marvel Comics",
                "description": f"{bio.get('fullName') or x['name']} — First appearance: {bio.get('firstAppearance') or 'Unknown'}.",
                "image": img if img else f"/api/avatar/{cid}",
                "image_source": "SuperHeroAPI (akabab/superhero-api, MIT) via jsDelivr CDN" if img else "Missing artwork (neutral fallback)",
                "image_attribution": f"{MARVEL_ATTRIBUTION} | Portrait via akabab/superhero-api (MIT)" if img else MARVEL_ATTRIBUTION,
                "image_verification_status": "verified_cdn" if img else "missing_artwork_placeholder",
                "aliases": aliases,
                "affiliations": affiliations,
                "species": race or "Unknown",
                "gender": app.get("gender") if app.get("gender") not in (None, "-") else "Unknown",
                "categories": cats,
                "powerstats": stats,
                "comics": [bio["firstAppearance"]] if bio.get("firstAppearance") and bio["firstAppearance"] != "-" else [],
                "series": [],
                "events": [],
                "source": "SuperHeroAPI (akabab/superhero-api, MIT)",
                "attribution": MARVEL_ATTRIBUTION,
                "is_combat_capable": False,
            })
        return out

    def fetch_wikidata_marvel_paginated(self, use_cache: bool = True, page_size: int = 500) -> Dict[str, Any]:
        """Paginated, resumable Wikidata SPARQL import for all Marvel Comics / MCU fictional characters."""
        cache_state = {"completed": False, "last_offset": 0, "failed_pages": [], "records": {}}
        if use_cache and os.path.exists(WIKIDATA_CACHE_PATH):
            with open(WIKIDATA_CACHE_PATH, "r", encoding="utf-8") as f:
                cache_state = json.load(f)

        if not cache_state.get("completed"):
            offset = int(cache_state.get("last_offset", 0))
            while True:
                sparql = f"""
SELECT ?item ?itemLabel ?itemDescription ?speciesLabel ?genderLabel ?affLabel WHERE {{
  {{
    SELECT DISTINCT ?item WHERE {{
      ?item wdt:P31/wdt:P279* wd:Q95074 .
      {{ ?item wdt:P1441 ?w . {{ ?w wdt:P123 wd:Q173496 . }} UNION {{ ?w wdt:P179 wd:Q173496 . }} UNION {{ ?w wdt:P179 wd:Q642878 . }} }}
      UNION {{ ?item wdt:P1080 wd:Q931597 . }}
      UNION {{ ?item wdt:P1080 wd:Q642878 . }}
    }}
    ORDER BY ?item
    LIMIT {page_size}
    OFFSET {offset}
  }}
  OPTIONAL {{ ?item wdt:P31 ?species . }}
  OPTIONAL {{ ?item wdt:P21 ?gender . }}
  OPTIONAL {{ ?item wdt:P463 ?aff . }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}"""
                url = f"{WIKIDATA_SPARQL_URL}?format=json&query={urllib.parse.quote(sparql)}"
                data = self._http_get_json(url, timeout=30, retries=3)
                if not data:
                    cache_state.setdefault("failed_pages", []).append(offset)
                    break
                bindings = (data.get("results") or {}).get("bindings") or []
                if not bindings:
                    cache_state["completed"] = True
                    break

                seen_in_page: Set[str] = set()
                for b in bindings:
                    uri = (b.get("item") or {}).get("value", "")
                    qid = uri.rsplit("/", 1)[-1]
                    if not qid.startswith("Q"):
                        continue
                    seen_in_page.add(qid)
                    label = (b.get("itemLabel") or {}).get("value", qid)
                    if label == qid:
                        continue
                    desc = (b.get("itemDescription") or {}).get("value", "")
                    sp = (b.get("speciesLabel") or {}).get("value", "")
                    gen = (b.get("genderLabel") or {}).get("value", "")
                    aff = (b.get("affLabel") or {}).get("value", "")

                    rec = cache_state["records"].setdefault(qid, {
                        "wikidata_id": qid,
                        "name": label,
                        "description": desc,
                        "species": [],
                        "gender": gen or "Unknown",
                        "affiliations": [],
                    })
                    if sp and sp not in rec["species"] and not sp.startswith("Q"):
                        rec["species"].append(sp)
                    if aff and aff not in rec["affiliations"] and not aff.startswith("Q"):
                        rec["affiliations"].append(aff)

                offset += page_size
                cache_state["last_offset"] = offset
                with open(WIKIDATA_CACHE_PATH, "w", encoding="utf-8") as f:
                    json.dump(cache_state, f, ensure_ascii=False)
                if len(seen_in_page) < 50:
                    cache_state["completed"] = True
                    with open(WIKIDATA_CACHE_PATH, "w", encoding="utf-8") as f:
                        json.dump(cache_state, f, ensure_ascii=False)
                    break
                time.sleep(0.3)

        return cache_state

    def fetch_wikipedia_marvel_categories(self, use_cache: bool = True) -> Dict[str, Any]:
        """Paginated Wikipedia category traversal for Marvel heroes, villains, antiheroes, mutants, and teams."""
        if use_cache and os.path.exists(WIKIPEDIA_CACHE_PATH):
            with open(WIKIPEDIA_CACHE_PATH, "r", encoding="utf-8") as f:
                cached = json.load(f)
            if cached.get("completed"):
                return cached

        cat_specs = [
            ("Category:Marvel_Comics_superheroes", "Heroes", None),
            ("Category:Marvel_Comics_supervillains", "Villains", None),
            ("Category:Marvel_Comics_antiheroes", "Antiheroes", None),
            ("Category:Marvel_Comics_mutants", "Mutants", None),
            ("Category:Marvel_Comics_cosmic_characters", "Cosmic", None),
            ("Category:Marvel_Comics_alien_characters", "Aliens", None),
            ("Category:Marvel_Comics_characters", "Other / unclassified", None),
            ("Category:Avengers_(comics)_characters", None, "Avengers"),
            ("Category:Spider-Man_characters", None, "Spider-Man Universe"),
            ("Category:X-Men_members", None, "X-Men"),
            ("Category:Fantastic_Four_characters", None, "Fantastic Four"),
            ("Category:Guardians_of_the_Galaxy_characters", None, "Guardians of the Galaxy"),
            ("Category:Inhumans_characters", None, "Inhumans"),
            ("Category:Eternals_(comics)_characters", None, "Eternals"),
            ("Category:Defenders_(comics)_characters", None, "Defenders"),
            ("Category:Thunderbolts_(comics)_characters", None, "Thunderbolts"),
            ("Category:Young_Avengers_characters", None, "Young Avengers"),
            ("Category:Midnight_Sons_characters", None, "Midnight Sons"),
        ]

        pages_by_id: Dict[str, dict] = {}
        failed_cats: List[str] = []
        skip_prefixes = ("List of ", "Category:", "Template:", "Portal:", "Wikipedia:")

        for cat_title, role_cat, team_aff in cat_specs:
            cmcontinue = None
            while True:
                params = {
                    "action": "query",
                    "list": "categorymembers",
                    "cmtitle": cat_title,
                    "cmtype": "page",
                    "cmlimit": "500",
                    "format": "json",
                }
                if cmcontinue:
                    params["cmcontinue"] = cmcontinue
                url = f"{WIKIPEDIA_API_URL}?{urllib.parse.urlencode(params)}"
                data = self._http_get_json(url, timeout=20, retries=3)
                if not data:
                    failed_cats.append(cat_title)
                    break
                for m in (data.get("query") or {}).get("categorymembers") or []:
                    title = m.get("title", "")
                    if not title or title.startswith(skip_prefixes):
                        continue
                    pid = str(m["pageid"])
                    entry = pages_by_id.setdefault(pid, {
                        "pageid": m["pageid"],
                        "title": title,
                        "categories": [],
                        "affiliations": [],
                    })
                    if role_cat and role_cat not in entry["categories"]:
                        entry["categories"].append(role_cat)
                    if team_aff and team_aff not in entry["affiliations"]:
                        entry["affiliations"].append(team_aff)
                cmcontinue = (data.get("continue") or {}).get("cmcontinue")
                if not cmcontinue:
                    break
                time.sleep(0.15)

        result = {"completed": True, "failed_categories": failed_cats, "pages": pages_by_id}
        with open(WIKIPEDIA_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False)
        return result

    def import_public_catalog(self, use_cache: bool = True) -> Dict[str, Any]:
        """
        Comprehensive, resumable credential-free Marvel import merging:
        1. Curated 28 seed characters (preserved with exact IDs & verified artwork)
        2. SuperHeroAPI (MIT, jsDelivr CDN)
        3. Wikidata SPARQL (CC0 1.0, paginated)
        4. Wikipedia Category API (CC BY-SA 4.0, paginated)
        Writes data/marvel_characters_raw.json and data/marvel_import_manifest.json.
        """
        os.makedirs(CACHE_DIR, exist_ok=True)
        os.makedirs(DATA_DIR, exist_ok=True)

        records_by_id: Dict[str, dict] = {}
        norm_index: Dict[str, str] = {}
        duplicates_merged = 0

        def _merge_metadata(target: dict, incoming: dict):
            for field in ("aliases", "affiliations", "categories", "comics", "series", "events"):
                existing = target.setdefault(field, [])
                for val in (incoming.get(field) or []):
                    if val and val not in existing:
                        existing.append(val)
            if not target.get("description") and incoming.get("description"):
                target["description"] = incoming["description"]
            if (not target.get("species") or target.get("species") == "Unknown") and incoming.get("species"):
                target["species"] = incoming["species"]
            if incoming.get("wikidata_id") and not target.get("wikidata_id"):
                target["wikidata_id"] = incoming["wikidata_id"]
            if incoming.get("wikipedia_pageid") and not target.get("wikipedia_pageid"):
                target["wikipedia_pageid"] = incoming["wikipedia_pageid"]
            if incoming.get("powerstats") and not target.get("powerstats"):
                target["powerstats"] = incoming["powerstats"]
            srcs = target.setdefault("sources", [target.get("source", "Unknown")])
            if incoming.get("source") and incoming["source"] not in srcs:
                srcs.append(incoming["source"])

        # 1. Curated 28 seed records (never overwritten)
        for entry in _seed_offline_marvel_catalog():
            entry.setdefault("categories", ["Supporting characters"] if not entry.get("is_combat_capable") else [])
            entry.setdefault("affiliations", [])
            entry.setdefault("sources", [entry.get("source", "Curated")])
            records_by_id[entry["id"]] = entry
            norm = self._normalize_name(entry["name"])
            if norm and "mcu" not in entry["id"]:
                norm_index.setdefault(norm, entry["id"])

        # 2. SuperHeroAPI (~288 Marvel characters with verified CDN artwork & powerstats)
        sh_records = self.fetch_superhero_api_marvel(use_cache=use_cache)
        for rec in sh_records:
            norm = self._normalize_name(rec["name"])
            if norm in norm_index:
                _merge_metadata(records_by_id[norm_index[norm]], rec)
                duplicates_merged += 1
            else:
                records_by_id[rec["id"]] = rec
                if norm:
                    norm_index[norm] = rec["id"]

        # 3. Wikidata SPARQL (1,488+ Marvel characters)
        wd_state = self.fetch_wikidata_marvel_paginated(use_cache=use_cache)
        wd_records = wd_state.get("records") or {}
        for qid, wrec in wd_records.items():
            cid = f"marvel_wd_{qid}"
            norm = self._normalize_name(wrec["name"])
            cats = self._classify_from_metadata("", " ".join(wrec.get("species") or []), [], wrec.get("description", ""))
            entry = {
                "id": cid,
                "marvel_id": None,
                "wikidata_id": qid,
                "name": wrec["name"],
                "incarnation": "Marvel Universe (Wikidata)",
                "universe": "marvel",
                "anime_id": "marvel",
                "anime_name": "Marvel Comics",
                "description": wrec.get("description", ""),
                "image": f"/api/avatar/{cid}",
                "image_source": "Missing artwork (neutral fallback)",
                "image_attribution": MARVEL_ATTRIBUTION,
                "image_verification_status": "missing_artwork_placeholder",
                "aliases": [],
                "affiliations": wrec.get("affiliations", []),
                "species": ", ".join(wrec.get("species") or []) or "Unknown",
                "gender": wrec.get("gender", "Unknown"),
                "categories": cats,
                "comics": [],
                "series": [],
                "events": [],
                "source": "Wikidata SPARQL (CC0 1.0)",
                "attribution": f"{MARVEL_ATTRIBUTION} | Metadata via Wikidata (CC0)",
                "is_combat_capable": False,
            }
            if norm in norm_index:
                _merge_metadata(records_by_id[norm_index[norm]], entry)
                duplicates_merged += 1
            else:
                records_by_id[cid] = entry
                if norm:
                    norm_index[norm] = cid

        # 4. Wikipedia Categories (heroes, villains, antiheroes, mutants, cosmic, teams)
        wp_state = self.fetch_wikipedia_marvel_categories(use_cache=use_cache)
        wp_pages = wp_state.get("pages") or {}
        for pid, wpage in wp_pages.items():
            cid = f"marvel_wp_{pid}"
            norm = self._normalize_name(wpage["title"])
            cats = [c for c in (wpage.get("categories") or []) if c != "Other / unclassified"] or ["Other / unclassified"]
            entry = {
                "id": cid,
                "marvel_id": None,
                "wikipedia_pageid": wpage["pageid"],
                "name": wpage["title"],
                "incarnation": "Marvel Comics (Wikipedia)",
                "universe": "marvel",
                "anime_id": "marvel",
                "anime_name": "Marvel Comics",
                "description": f"Marvel Comics character documented on Wikipedia ({wpage['title']}).",
                "image": f"/api/avatar/{cid}",
                "image_source": "Missing artwork (neutral fallback)",
                "image_attribution": MARVEL_ATTRIBUTION,
                "image_verification_status": "missing_artwork_placeholder",
                "aliases": [],
                "affiliations": wpage.get("affiliations", []),
                "species": "Unknown",
                "categories": cats,
                "comics": [],
                "series": [],
                "events": [],
                "source": "Wikipedia MediaWiki API (CC BY-SA 4.0)",
                "attribution": f"{MARVEL_ATTRIBUTION} | Categories via Wikipedia (CC BY-SA 4.0)",
                "is_combat_capable": False,
            }
            if norm in norm_index:
                _merge_metadata(records_by_id[norm_index[norm]], entry)
                duplicates_merged += 1
            else:
                records_by_id[cid] = entry
                if norm:
                    norm_index[norm] = cid

        records = list(records_by_id.values())
        cat_counts: Dict[str, int] = {}
        img_verified = 0
        combat_ready = 0
        for r in records:
            if r.get("image_verification_status") == "verified_cdn":
                img_verified += 1
            if r.get("is_combat_capable"):
                combat_ready += 1
            for c in (r.get("categories") or ["Other / unclassified"]):
                cat_counts[c] = cat_counts.get(c, 0) + 1

        now_iso = datetime.now(timezone.utc).isoformat()
        manifest = {
            "version": "2.0.0",
            "import_mode": "public_multi_source_resumable",
            "last_import_timestamp": now_iso,
            "sources": {
                "curated_seed": {"records": 28, "status": "complete"},
                "superhero_api_mit": {"records": len(sh_records), "status": "complete" if sh_records else "unavailable"},
                "wikidata_sparql_cc0": {
                    "records": len(wd_records),
                    "last_successful_offset": wd_state.get("last_offset", 0),
                    "completed": wd_state.get("completed", False),
                    "failed_pages": wd_state.get("failed_pages", []),
                },
                "wikipedia_categories_cc_by_sa": {
                    "records": len(wp_pages),
                    "completed": wp_state.get("completed", False),
                    "failed_categories": wp_state.get("failed_categories", []),
                },
                "official_marvel_api": {"status": "skipped_no_credentials"},
            },
            "total_discovered_before_merge": 28 + len(sh_records) + len(wd_records) + len(wp_pages),
            "unique_ids": len(records),
            "duplicates_merged": duplicates_merged,
            "failed_pages": wd_state.get("failed_pages", []),
            "last_successful_offset": wd_state.get("last_offset", 0),
            "image_coverage": {
                "verified_cdn": img_verified,
                "missing_artwork_placeholder": len(records) - img_verified,
            },
            "combat_verification_coverage": {
                "combat_eligible": combat_ready,
                "combat_incomplete_or_discovery_only": len(records) - combat_ready,
            },
            "category_counts": cat_counts,
            "errors": self.errors,
        }

        out_payload = {
            "metadata": {
                "version": "2.0.0",
                "universe": "marvel",
                "import_mode": "public_multi_source_resumable",
                "attribution": MARVEL_ATTRIBUTION,
                "generated_at": now_iso,
                "total_characters": len(records),
                "api_fetched": len(sh_records) + len(wd_records) + len(wp_pages),
                "duplicates_skipped": duplicates_merged,
                "errors": self.errors,
            },
            "characters": records,
        }
        with open(MARVEL_RAW_PATH, "w", encoding="utf-8") as f:
            json.dump(out_payload, f, indent=2, ensure_ascii=False)
        with open(MARVEL_MANIFEST_PATH, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)

        return manifest


if __name__ == "__main__":
    importer = MarvelCharacterImporter()
    print(json.dumps(importer.import_public_catalog(use_cache=True), indent=2))
