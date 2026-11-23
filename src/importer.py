"""
Complete Pokemon Data Import & Database Generator
=================================================
Imports official Pokemon data covering all 1025 National Pokedex species
and all 326 alternate battle/regional/mega forms (1,351 total entries).

Outputs:
- data/pokemon_database.json
- data/pokemon.db (SQLite with full indexes)
"""

import os
import sys
import csv
import json
import sqlite3
import urllib.request
import time

from type_chart import calculate_defensive_effectiveness
from ranking import calculate_power_rating, determine_tier, determine_rarity_tier, calculate_auction_value

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(BASE_DIR, "cache")
DATA_DIR = os.path.join(BASE_DIR, "data")

STARTER_SPECIES_IDS = {
    # Gen 1
    1, 2, 3, 4, 5, 6, 7, 8, 9, 25, 26, 133, 172,
    # Gen 2
    152, 153, 154, 155, 156, 157, 158, 159, 160,
    # Gen 3
    252, 253, 254, 255, 256, 257, 258, 259, 260,
    # Gen 4
    387, 388, 389, 390, 391, 392, 393, 394, 395,
    # Gen 5
    495, 496, 497, 498, 499, 500, 501, 502, 503,
    # Gen 6
    650, 651, 652, 653, 654, 655, 656, 657, 658,
    # Gen 7
    722, 723, 724, 725, 726, 727, 728, 729, 730,
    # Gen 8
    810, 811, 812, 813, 814, 815, 816, 817, 818,
    # Gen 9
    906, 907, 908, 909, 910, 911, 912, 913, 914
}

CSV_URLS = {
    "pokemon": "https://raw.githubusercontent.com/PokeAPI/pokeapi/master/data/v2/csv/pokemon.csv",
    "species": "https://raw.githubusercontent.com/PokeAPI/pokeapi/master/data/v2/csv/pokemon_species.csv",
    "stats": "https://raw.githubusercontent.com/PokeAPI/pokeapi/master/data/v2/csv/pokemon_stats.csv",
    "types": "https://raw.githubusercontent.com/PokeAPI/pokeapi/master/data/v2/csv/pokemon_types.csv",
    "type_names": "https://raw.githubusercontent.com/PokeAPI/pokeapi/master/data/v2/csv/types.csv",
    "abilities": "https://raw.githubusercontent.com/PokeAPI/pokeapi/master/data/v2/csv/pokemon_abilities.csv",
    "ability_names": "https://raw.githubusercontent.com/PokeAPI/pokeapi/master/data/v2/csv/ability_names.csv",
    "species_names": "https://raw.githubusercontent.com/PokeAPI/pokeapi/master/data/v2/csv/pokemon_species_names.csv",
    "forms": "https://raw.githubusercontent.com/PokeAPI/pokeapi/master/data/v2/csv/pokemon_forms.csv"
}


def download_datasets():
    """Ensure all required datasets are cached locally."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    
    print("[1/5] Checking and downloading source data files...")
    for key, url in CSV_URLS.items():
        dest = os.path.join(CACHE_DIR, f"{key}.csv")
        if not os.path.exists(dest) or os.path.getsize(dest) == 0:
            print(f"  Downloading {key}.csv from {url} ...")
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 PokemonAuctionImporter/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp, open(dest, "wb") as f:
                f.write(resp.read())
            print(f"  Saved {key}.csv ({os.path.getsize(dest)} bytes)")
        else:
            print(f"  Cached {key}.csv found ({os.path.getsize(dest)} bytes)")


def clean_form_name(base_name, identifier, is_default):
    """Generates clean human-readable names for Pokemon forms."""
    if is_default:
        return base_name

    parts = identifier.lower().split("-")
    if "mega" in parts:
        suffix = " " + parts[-1].upper() if parts[-1] in ["x", "y"] else ""
        return f"Mega {base_name}{suffix}"
    if "primal" in parts:
        return f"Primal {base_name}"
    if "alola" in parts:
        return f"Alolan {base_name}"
    if "galar" in parts:
        return f"Galarian {base_name}"
    if "hisui" in parts:
        return f"Hisuian {base_name}"
    if "paldea" in parts:
        breed = ""
        if "combat" in parts:
            breed = " (Combat Breed)"
        elif "blaze" in parts:
            breed = " (Blaze Breed)"
        elif "aqua" in parts:
            breed = " (Aqua Breed)"
        return f"Paldean {base_name}{breed}"
    if "gmax" in parts:
        return f"Gigantamax {base_name}"
    if "origin" in parts:
        return f"{base_name} (Origin Forme)"
    if "attack" in parts:
        return f"{base_name} (Attack Forme)"
    if "defense" in parts:
        return f"{base_name} (Defense Forme)"
    if "speed" in parts:
        return f"{base_name} (Speed Forme)"
    if "crowned" in parts:
        item = "Crowned Sword" if "sword" in parts or "zacian" in identifier else "Crowned Shield"
        return f"{base_name} ({item})"
    if "shadow" in parts:
        return f"{base_name} (Shadow Rider)"
    if "ice" in parts and "calyrex" in identifier:
        return f"{base_name} (Ice Rider)"
    if "rapid-strike" in identifier:
        return f"{base_name} (Rapid Strike Style)"
    if "single-strike" in identifier:
        return f"{base_name} (Single Strike Style)"
    if "therian" in parts:
        return f"{base_name} (Therian Forme)"
    if "incarnate" in parts:
        return f"{base_name} (Incarnate Forme)"

    # Generic form extraction
    base_slug = base_name.lower().replace(" ", "-").replace(".", "").replace("'", "")
    clean_parts = [p.capitalize() for p in parts if p not in base_slug and p != "standard"]
    if clean_parts:
        return f"{base_name} ({' '.join(clean_parts)})"
    return f"{base_name} ({identifier})"


def build_pokemon_database():
    download_datasets()
    print("[2/5] Parsing CSV raw relations...")

    # 1. Type names mapping
    type_names = {}
    with open(os.path.join(CACHE_DIR, "type_names.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            type_names[r["id"]] = r["identifier"].capitalize()

    # 2. Ability names mapping (English = language_id 9)
    ability_names = {}
    with open(os.path.join(CACHE_DIR, "ability_names.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["local_language_id"] == "9":
                ability_names[r["ability_id"]] = r["name"]

    # 3. Species info (name & genus category in English)
    species_info = {}
    with open(os.path.join(CACHE_DIR, "species_names.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["local_language_id"] == "9":
                species_info[r["pokemon_species_id"]] = {
                    "name": r["name"],
                    "category": r["genus"].replace("Pokmon", "Pokémon")
                }

    # 4. Species details (generation, legendary, mythical, evolution chain)
    species_details = {}
    with open(os.path.join(CACHE_DIR, "species.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            sid = r["id"]
            species_details[sid] = {
                "id": int(sid),
                "identifier": r["identifier"],
                "generation": int(r["generation_id"]),
                "evolves_from_species_id": int(r["evolves_from_species_id"]) if r["evolves_from_species_id"] else None,
                "evolution_chain_id": int(r["evolution_chain_id"]) if r["evolution_chain_id"] else None,
                "is_baby": r["is_baby"] == "1",
                "is_legendary": r["is_legendary"] == "1",
                "is_mythical": r["is_mythical"] == "1"
            }

    # Compute evolution stages
    evolution_stages = {}
    for sid, sdata in species_details.items():
        parent_id = sdata["evolves_from_species_id"]
        if not parent_id:
            evolution_stages[sid] = 1
        else:
            grandparent = species_details.get(str(parent_id), {}).get("evolves_from_species_id")
            if grandparent:
                evolution_stages[sid] = 3
            else:
                evolution_stages[sid] = 2

    # 5. Pokemon stats mapping: pokemon_id -> {hp, attack, defense, special_attack, special_defense, speed, total}
    # stat_ids: 1=hp, 2=attack, 3=defense, 4=special-attack, 5=special-defense, 6=speed
    stat_key_map = {
        "1": "hp",
        "2": "attack",
        "3": "defense",
        "4": "special_attack",
        "5": "special_defense",
        "6": "speed"
    }
    pokemon_stats = {}
    with open(os.path.join(CACHE_DIR, "stats.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            pid = r["pokemon_id"]
            sid = r["stat_id"]
            if sid in stat_key_map:
                if pid not in pokemon_stats:
                    pokemon_stats[pid] = {}
                pokemon_stats[pid][stat_key_map[sid]] = int(r["base_stat"])

    for pid, s in pokemon_stats.items():
        s["total"] = s.get("hp", 0) + s.get("attack", 0) + s.get("defense", 0) + \
                     s.get("special_attack", 0) + s.get("special_defense", 0) + s.get("speed", 0)

    # 6. Pokemon types mapping: pokemon_id -> [types sorted by slot]
    pokemon_types = {}
    with open(os.path.join(CACHE_DIR, "types.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            pid = r["pokemon_id"]
            tname = type_names.get(r["type_id"], "Normal")
            slot = int(r["slot"])
            if pid not in pokemon_types:
                pokemon_types[pid] = []
            pokemon_types[pid].append((slot, tname))

    for pid in pokemon_types:
        pokemon_types[pid].sort(key=lambda x: x[0])
        pokemon_types[pid] = [t[1] for t in pokemon_types[pid]]

    # 7. Pokemon abilities mapping: pokemon_id -> [abilities]
    pokemon_abilities = {}
    with open(os.path.join(CACHE_DIR, "abilities.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            pid = r["pokemon_id"]
            aname = ability_names.get(r["ability_id"])
            if aname:
                if pid not in pokemon_abilities:
                    pokemon_abilities[pid] = []
                if aname not in pokemon_abilities[pid]:
                    pokemon_abilities[pid].append(aname)

    print("[3/5] Compiling and calculating rankings for all Pokemon...")
    # 8. Main pokemon table compilation
    all_pokemon = []
    failed_records = []

    with open(os.path.join(CACHE_DIR, "pokemon.csv"), encoding="utf-8") as f:
        raw_pokemon = list(csv.DictReader(f))

    total_records = len(raw_pokemon)
    base_count = 0
    form_count = 0

    for r in raw_pokemon:
        try:
            pid = int(r["id"])
            species_id = int(r["species_id"])
            is_default = r["is_default"] == "1"
            identifier = r["identifier"]

            if is_default:
                base_count += 1
            else:
                form_count += 1

            s_info = species_info.get(str(species_id), {})
            base_name = s_info.get("name", identifier.capitalize())
            category = s_info.get("category", "Pokémon")

            display_name = clean_form_name(base_name, identifier, is_default)

            s_details = species_details.get(str(species_id), {})
            generation = s_details.get("generation", 1)
            is_legendary = s_details.get("is_legendary", False)
            is_mythical = s_details.get("is_mythical", False)
            is_starter = species_id in STARTER_SPECIES_IDS
            evolves_from_id = s_details.get("evolves_from_species_id")
            evolution_chain_id = s_details.get("evolution_chain_id")
            stage = evolution_stages.get(str(species_id), 1)

            evolves_from_name = species_info.get(str(evolves_from_id), {}).get("name") if evolves_from_id else None

            types = pokemon_types.get(str(pid), ["Normal"])
            abilities = pokemon_abilities.get(str(pid), [])
            stats = pokemon_stats.get(str(pid), {
                "hp": 50, "attack": 50, "defense": 50,
                "special_attack": 50, "special_defense": 50, "speed": 50, "total": 300
            })

            # Height in meters, weight in kg
            height_m = round(float(r["height"]) / 10.0, 2)
            weight_kg = round(float(r["weight"]) / 10.0, 2)

            # Defensive type calculation
            type_def_info = calculate_defensive_effectiveness(types)
            type_mod = type_def_info["net_defensive_score"]

            # Calculate Power Rating (1 to 100)
            power_rating = calculate_power_rating(
                stats=stats,
                type_modifier=type_mod,
                evolution_stage=stage,
                is_legendary=is_legendary,
                is_mythical=is_mythical
            )

            # Assign Tier
            tier = determine_tier(power_rating)

            # Assign Rarity Tier
            rarity_tier = determine_rarity_tier(
                is_mythical=is_mythical,
                is_legendary=is_legendary,
                is_starter=is_starter,
                bst=stats["total"],
                stage=stage,
                identifier=identifier
            )

            # Calculate Auction Value Score
            auction_value_score = calculate_auction_value(
                power_rating=power_rating,
                rarity_tier=rarity_tier,
                bst=stats["total"],
                tier=tier
            )

            # Artwork and Official Pokédex Links
            official_artwork = f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/{pid}.png"
            pokedex_img = f"https://assets.pokemon.com/assets/cms2/img/pokedex/full/{species_id:03d}.png"
            pokedex_url = f"https://www.pokemon.com/us/pokedex/{s_details.get('identifier', identifier)}"

            entry = {
                "id": pid,
                "national_id": species_id,
                "name": display_name,
                "identifier": identifier,
                "is_default": is_default,
                "types": types,
                "generation": generation,
                "category": category,
                "height": height_m,
                "weight": weight_kg,
                "abilities": abilities,
                "stats": stats,
                "type_effectiveness": {
                    "weaknesses": type_def_info["weaknesses"],
                    "resistances": type_def_info["resistances"],
                    "immunities": type_def_info["immunities"],
                    "defensive_score": type_mod
                },
                "power_rating": power_rating,
                "tier": tier,
                "rarity": rarity_tier,
                "auction_value_score": auction_value_score,
                "is_legendary": is_legendary,
                "is_mythical": is_mythical,
                "is_starter": is_starter,
                "evolution": {
                    "stage": stage,
                    "chain_id": evolution_chain_id,
                    "evolves_from_id": evolves_from_id,
                    "evolves_from_name": evolves_from_name
                },
                "image": official_artwork,
                "official_pokedex_image": pokedex_img,
                "official_pokedex_url": pokedex_url
            }

            all_pokemon.append(entry)

        except Exception as e:
            failed_records.append({"record": r, "error": str(e)})

    print(f"[3/5] Processed {len(all_pokemon)}/{total_records} records ({len(failed_records)} failed).")

    # Sort dataset by ID
    all_pokemon.sort(key=lambda x: x["id"])

    # 9. Save JSON database
    json_path = os.path.join(DATA_DIR, "pokemon_database.json")
    print(f"[4/5] Saving JSON database to {json_path} ...")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(all_pokemon, f, indent=2, ensure_ascii=False)
    print(f"  Saved {len(all_pokemon)} entries to JSON ({os.path.getsize(json_path)} bytes)")

    # 10. Save SQLite database
    db_path = os.path.join(DATA_DIR, "pokemon.db")
    print(f"[5/5] Creating SQLite database and indexes at {db_path} ...")
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE pokemon (
        id INTEGER PRIMARY KEY,
        national_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        identifier TEXT NOT NULL,
        is_default INTEGER NOT NULL,
        generation INTEGER NOT NULL,
        category TEXT,
        height_m REAL,
        weight_kg REAL,
        primary_type TEXT NOT NULL,
        secondary_type TEXT,
        all_types TEXT NOT NULL,
        abilities TEXT NOT NULL,
        hp INTEGER NOT NULL,
        attack INTEGER NOT NULL,
        defense INTEGER NOT NULL,
        special_attack INTEGER NOT NULL,
        special_defense INTEGER NOT NULL,
        speed INTEGER NOT NULL,
        base_stat_total INTEGER NOT NULL,
        power_rating REAL NOT NULL,
        tier TEXT NOT NULL,
        rarity TEXT NOT NULL,
        auction_value_score INTEGER NOT NULL,
        is_legendary INTEGER NOT NULL,
        is_mythical INTEGER NOT NULL,
        is_starter INTEGER NOT NULL,
        evolution_stage INTEGER NOT NULL,
        evolution_chain_id INTEGER,
        evolves_from_name TEXT,
        image TEXT NOT NULL,
        official_pokedex_image TEXT NOT NULL,
        official_pokedex_url TEXT NOT NULL,
        raw_json TEXT NOT NULL
    );
    """)

    cur.execute("CREATE INDEX idx_national_id ON pokemon(national_id);")
    cur.execute("CREATE INDEX idx_name ON pokemon(name);")
    cur.execute("CREATE INDEX idx_generation ON pokemon(generation);")
    cur.execute("CREATE INDEX idx_primary_type ON pokemon(primary_type);")
    cur.execute("CREATE INDEX idx_tier ON pokemon(tier);")
    cur.execute("CREATE INDEX idx_rarity ON pokemon(rarity);")
    cur.execute("CREATE INDEX idx_power_rating ON pokemon(power_rating DESC);")
    cur.execute("CREATE INDEX idx_auction_value ON pokemon(auction_value_score DESC);")
    cur.execute("CREATE INDEX idx_bst ON pokemon(base_stat_total DESC);")
    cur.execute("CREATE INDEX idx_speed ON pokemon(speed DESC);")
    cur.execute("CREATE INDEX idx_attack ON pokemon(attack DESC);")
    cur.execute("CREATE INDEX idx_defense ON pokemon(defense DESC);")
    cur.execute("CREATE INDEX idx_legendary ON pokemon(is_legendary);")
    cur.execute("CREATE INDEX idx_mythical ON pokemon(is_mythical);")

    # Table for normalized types
    cur.execute("""
    CREATE TABLE pokemon_types (
        pokemon_id INTEGER,
        type_name TEXT NOT NULL,
        slot INTEGER NOT NULL,
        PRIMARY KEY (pokemon_id, slot),
        FOREIGN KEY (pokemon_id) REFERENCES pokemon(id)
    );
    """)
    cur.execute("CREATE INDEX idx_type_slot ON pokemon_types(type_name);")

    # Table for normalized abilities
    cur.execute("""
    CREATE TABLE pokemon_abilities (
        pokemon_id INTEGER,
        ability_name TEXT NOT NULL,
        PRIMARY KEY (pokemon_id, ability_name),
        FOREIGN KEY (pokemon_id) REFERENCES pokemon(id)
    );
    """)
    cur.execute("CREATE INDEX idx_ability ON pokemon_abilities(ability_name);")

    # Insert data
    pokemon_rows = []
    types_rows = []
    abilities_rows = []

    for p in all_pokemon:
        p_types = p["types"]
        primary = p_types[0] if len(p_types) > 0 else "Normal"
        secondary = p_types[1] if len(p_types) > 1 else None

        pokemon_rows.append((
            p["id"],
            p["national_id"],
            p["name"],
            p["identifier"],
            1 if p["is_default"] else 0,
            p["generation"],
            p["category"],
            p["height"],
            p["weight"],
            primary,
            secondary,
            ", ".join(p_types),
            ", ".join(p["abilities"]),
            p["stats"]["hp"],
            p["stats"]["attack"],
            p["stats"]["defense"],
            p["stats"]["special_attack"],
            p["stats"]["special_defense"],
            p["stats"]["speed"],
            p["stats"]["total"],
            p["power_rating"],
            p["tier"],
            p["rarity"],
            p["auction_value_score"],
            1 if p["is_legendary"] else 0,
            1 if p["is_mythical"] else 0,
            1 if p["is_starter"] else 0,
            p["evolution"]["stage"],
            p["evolution"]["chain_id"],
            p["evolution"]["evolves_from_name"],
            p["image"],
            p["official_pokedex_image"],
            p["official_pokedex_url"],
            json.dumps(p, ensure_ascii=False)
        ))

        for slot_idx, tname in enumerate(p_types, start=1):
            types_rows.append((p["id"], tname, slot_idx))

        for aname in p["abilities"]:
            abilities_rows.append((p["id"], aname))

    cur.executemany("""
    INSERT INTO pokemon VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?);
    """, pokemon_rows)

    cur.executemany("""
    INSERT INTO pokemon_types VALUES (?,?,?);
    """, types_rows)

    cur.executemany("""
    INSERT INTO pokemon_abilities VALUES (?,?);
    """, abilities_rows)

    conn.commit()
    conn.close()

    print(f"  SQLite database created with {len(pokemon_rows)} Pokemon, {len(types_rows)} types, {len(abilities_rows)} abilities.")
    print("="*60)
    print(f"IMPORT COMPLETE SUMMARY:")
    print(f"  Total Pokemon imported: {len(all_pokemon)}")
    print(f"  Base National Dex Species: {base_count} (#0001 to #1025)")
    print(f"  Alternate / Battle Forms: {form_count}")
    print(f"  Generations: Gen 1 through Gen 9")
    print(f"  Failed records: {len(failed_records)}")
    print("="*60)

    return all_pokemon


if __name__ == "__main__":
    t0 = time.time()
    build_pokemon_database()
    print(f"Time taken: {time.time()-t0:.2f} seconds.")
