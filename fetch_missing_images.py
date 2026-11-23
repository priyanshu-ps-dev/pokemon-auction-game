import json
import time
import urllib.request
import urllib.error

GRAPHQL_URL = "https://graphql.anilist.co"
QUERY = """
query ($search: String) {
  Character(search: $search) {
    id
    name {
      full
      native
      alternative
    }
    image {
      large
      medium
    }
  }
}
"""

def fetch_anilist_image(search_name: str) -> str:
    payload = {
        "query": QUERY,
        "variables": {"search": search_name}
    }
    req = urllib.request.Request(
        GRAPHQL_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AnimeAuction/3.0"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            char = data.get("data", {}).get("Character")
            if char and char.get("image"):
                return char["image"].get("large") or char["image"].get("medium") or ""
    except Exception as e:
        print(f"Error fetching {search_name}: {e}")
    return ""

def main():
    with open("data/anime_database.json", "r", encoding="utf-8") as f:
        db = json.load(f)

    missing = [c for c in db["characters"] if not c.get("image") or c.get("image", "").startswith("/api/avatar") or "ui-avatars" in c.get("image", "")]
    print(f"Found {len(missing)} characters needing CDN images")

    clean_search_map = {
        "op_kaido": "Kaido",
        "op_whitebeard": "Edward Newgate",
        "op_blackbeard": "Marshall D. Teach",
        "op_law": "Trafalgar Law",
        "db_whis": "Whis",
        "db_hit": "Hit",
        "db_buu": "Majin Buu",
        "db_gogeta": "Gogeta",
        "db_vegito": "Vegito",
        "db_goku_black": "Goku Black",
        "db_roshi": "Kame-sennin",
        "sl_igris": "Igris",
        "naruto_guy": "Might Guy",
        "naruto_killerbee": "Killer B",
        "bleach_yamamoto": "Genryuusai Shigekuni Yamamoto"
    }

    repaired = 0
    for c in missing:
        cid = c["id"]
        search_query = clean_search_map.get(cid, c["name"].split("(")[0].strip())
        print(f"Fetching artwork for {cid} ({search_query})...", flush=True)
        img = fetch_anilist_image(search_query)
        if img:
            c["image"] = img
            c["image_verified"] = 1
            repaired += 1
            print(f"  -> SUCCESS: {img[:60]}...", flush=True)
        else:
            print(f"  -> NOT FOUND for {search_query}", flush=True)
        time.sleep(0.7)  # Respect AniList rate limit (90 req/min)

    print(f"Repaired {repaired}/{len(missing)} character images.")

    with open("data/anime_database.json", "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)

    from src.anime_database import AnimeDatabaseManager
    mgr = AnimeDatabaseManager("data/anime_database.json", "data/anime_platform.db")
    mgr.generate_audit_report("data/database_audit_report.json")
    print("Database and audit report updated.")

if __name__ == "__main__":
    main()
