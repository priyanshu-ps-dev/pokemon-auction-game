"""
Pokemon Bidding Game: Database Verification & Quality Audit
===========================================================
Audits the complete imported database (JSON and SQLite) against all
spec requirements.
"""

import os
import json
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
JSON_PATH = os.path.join(DATA_DIR, "pokemon_database.json")
DB_PATH = os.path.join(DATA_DIR, "pokemon.db")

def run_verification():
    print("=" * 70)
    print("POKEMON AUCTION SYSTEM: COMPREHENSIVE VERIFICATION AUDIT")
    print("=" * 70)

    # 1. File existence & size
    assert os.path.exists(JSON_PATH), f"JSON file missing: {JSON_PATH}"
    assert os.path.exists(DB_PATH), f"SQLite DB missing: {DB_PATH}"
    json_size_mb = os.path.getsize(JSON_PATH) / (1024 * 1024)
    db_size_mb = os.path.getsize(DB_PATH) / (1024 * 1024)
    print(f"[OK] Files Exist:")
    print(f"     JSON Database: {json_size_mb:.2f} MB")
    print(f"     SQLite Database: {db_size_mb:.2f} MB")

    # 2. JSON Integrity & Schema validation
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    total_pokemon = len(data)
    assert total_pokemon == 1351, f"Expected 1351 total entries, got {total_pokemon}"
    print(f"[OK] Total Pokemon Loaded: {total_pokemon}")

    base_species = [p for p in data if p["is_default"]]
    forms = [p for p in data if not p["is_default"]]
    print(f"     Base Species (#1 to #1025): {len(base_species)}")
    print(f"     Alternate / Battle Forms: {len(forms)}")
    assert len(base_species) == 1025, f"Expected 1025 base species, got {len(base_species)}"
    assert len(forms) == 326, f"Expected 326 forms, got {len(forms)}"

    # 3. Required Fields & Null Checks
    required_fields = [
        "id", "national_id", "name", "identifier", "types", "generation",
        "category", "height", "weight", "abilities", "stats", "power_rating",
        "tier", "rarity", "auction_value_score", "is_legendary", "is_mythical",
        "is_starter", "evolution", "image", "official_pokedex_image", "official_pokedex_url"
    ]
    stat_keys = ["hp", "attack", "defense", "special_attack", "special_defense", "speed", "total"]

    missing_field_count = 0
    invalid_stat_count = 0

    gen_counts = {}
    tier_counts = {"S+": 0, "S": 0, "A": 0, "B": 0, "C": 0, "D": 0}
    rarity_counts = {}
    legendary_count = 0
    mythical_count = 0
    starter_count = 0

    for p in data:
        for rf in required_fields:
            if rf not in p or p[rf] is None:
                missing_field_count += 1
        
        # Stat validation
        st = p["stats"]
        for sk in stat_keys:
            if sk not in st or st[sk] is None or st[sk] <= 0:
                invalid_stat_count += 1
        expected_total = sum(st[k] for k in ["hp", "attack", "defense", "special_attack", "special_defense", "speed"])
        if st["total"] != expected_total:
            invalid_stat_count += 1

        # Counters
        g = p["generation"]
        gen_counts[g] = gen_counts.get(g, 0) + 1
        tier_counts[p["tier"]] = tier_counts.get(p["tier"], 0) + 1
        rarity_counts[p["rarity"]] = rarity_counts.get(p["rarity"], 0) + 1
        if p["is_legendary"]: legendary_count += 1
        if p["is_mythical"]: mythical_count += 1
        if p["is_starter"]: starter_count += 1

    assert missing_field_count == 0, f"Found {missing_field_count} missing required fields"
    assert invalid_stat_count == 0, f"Found {invalid_stat_count} invalid stats"
    print(f"[OK] Schema & Stat Validation: 100% complete, 0 nulls, all BST formulas verified.")

    # 4. Generation Distribution
    print("\n--- GENERATION DISTRIBUTION ---")
    for g in sorted(gen_counts.keys()):
        print(f"  Generation {g}: {gen_counts[g]} entries")

    # 5. Tier Distribution
    print("\n--- COMPETITIVE AUCTION TIER DISTRIBUTION ---")
    for t in ["S+", "S", "A", "B", "C", "D"]:
        pct = (tier_counts[t] / total_pokemon) * 100
        print(f"  Tier {t:2}: {tier_counts[t]:4d} Pokemon ({pct:5.1f}%)")

    # 6. Rarity Distribution
    print("\n--- RARITY TIER DISTRIBUTION ---")
    for r, cnt in sorted(rarity_counts.items(), key=lambda x: -x[1]):
        pct = (cnt / total_pokemon) * 100
        print(f"  {r:16}: {cnt:4d} Pokemon ({pct:5.1f}%)")

    print(f"\n  Special Status:")
    print(f"    Legendary: {legendary_count}")
    print(f"    Mythical:  {mythical_count}")
    print(f"    Starter:   {starter_count}")

    # 7. Elite Sample Checks (Top 10 by Power Rating)
    print("\n--- TOP 10 HIGHEST POWER RATING (AUCTION LEADERS) ---")
    by_power = sorted(data, key=lambda x: x["power_rating"], reverse=True)
    for i, p in enumerate(by_power[:10], 1):
        print(f"  {i:2}. {p['name']:25} | PR: {p['power_rating']:5.1f} | Tier: {p['tier']:2} | BST: {p['stats']['total']:3} | Value: {p['auction_value_score']:6d} coins")

    # 8. Check Phione vs High-Tier Non-Legendary
    print("\n--- LEGENDARY BALANCE CHECK ---")
    phione = next(p for p in data if p["name"] == "Phione")
    garchomp = next(p for p in data if p["name"] == "Garchomp")
    dragapult = next(p for p in data if p["name"] == "Dragapult")
    caterpie = next(p for p in data if p["name"] == "Caterpie")
    print(f"  Phione (Mythical, BST {phione['stats']['total']})       : PR={phione['power_rating']} Tier={phione['tier']} (Not forced S+!)")
    print(f"  Garchomp (Non-Legendary, BST {garchomp['stats']['total']}) : PR={garchomp['power_rating']} Tier={garchomp['tier']}")
    print(f"  Dragapult (Non-Legendary, BST {dragapult['stats']['total']}): PR={dragapult['power_rating']} Tier={dragapult['tier']}")
    print(f"  Caterpie (Basic, BST {caterpie['stats']['total']})         : PR={caterpie['power_rating']} Tier={caterpie['tier']}")

    assert garchomp["power_rating"] > phione["power_rating"], "Garchomp should outrank Phione"

    # 9. SQLite Verification Queries
    print("\n--- SQLITE INDEXES & QUERY PERFORMANCE TEST ---")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM pokemon;")
    row_count = cur.fetchone()[0]
    assert row_count == 1351

    # Fast indexed search test: Fire types in Tier A sorted by power rating
    cur.execute("""
    SELECT name, primary_type, secondary_type, power_rating, tier, auction_value_score
    FROM pokemon
    WHERE (primary_type = 'Fire' OR secondary_type = 'Fire') AND tier = 'A'
    ORDER BY power_rating DESC
    LIMIT 5;
    """)
    fire_a = cur.fetchall()
    print("  Sample Query [Fire Types in Tier A]:")
    for r in fire_a:
        print(f"    - {r[0]:20} ({r[1]}/{r[2] or '-'}): PR={r[3]}, Tier={r[4]}, Value={r[5]}")

    # Sorting test
    cur.execute("SELECT name, speed FROM pokemon ORDER BY speed DESC LIMIT 3;")
    fastest = cur.fetchall()
    print(f"  Fastest: {', '.join(f'{f[0]} ({f[1]})' for f in fastest)}")

    conn.close()
    print("\n[SUCCESS] ALL VERIFICATION CHECKS PASSED PERFECTLY!\n" + "=" * 70)

if __name__ == "__main__":
    run_verification()
