import urllib.request
import json
import time

QUERY = """
query ($q: String) {
  Page(page: 1, perPage: 1) {
    characters(search: $q) {
      id
      name {
        full
      }
      image {
        large
      }
    }
  }
}
"""

targets = [
    ("db_beerus", "Beerus"),
    ("db_gogeta", "Gogeta"),
    ("db_vegito", "Vegetto"),
    ("naruto_obito", "Obito Uchiha"),
    ("ds_yoriichi", "Yoriichi Tsugikuni"),
    ("opm_boros", "Boros"),
    ("sl_jinwoo", "Jinwoo Sung"),
    ("mha_allmight", "All Might"),
    ("jojo_jotaro", "Joutarou Kuujou"),
    ("jjk_toji", "Touji Fushiguro"),
    ("naruto_sasuke", "Sasuke Uchiha")
]

results = {}
for cid, name in targets:
    req = urllib.request.Request(
        "https://graphql.anilist.co",
        data=json.dumps({"query": QUERY, "variables": {"q": name}}).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            chars = data.get("data", {}).get("Page", {}).get("characters", [])
            if chars:
                c = chars[0]
                img = c["image"]["large"]
                results[cid] = img
                print(f"OK {cid} ({c['name']['full']}): {img}")
    except Exception as e:
        print(f"ERR {name}: {e}")
    time.sleep(1.0)

with open("data/anime_database.json", "r", encoding="utf-8") as f:
    db = json.load(f)

for c in db["characters"]:
    if c["id"] in results:
        c["image"] = results[c["id"]]
        c["image_verified"] = 1

with open("data/anime_database.json", "w", encoding="utf-8") as f:
    json.dump(db, f, indent=2, ensure_ascii=False)

from src.anime_database import AnimeDatabaseManager
mgr = AnimeDatabaseManager("data/anime_database.json", "data/anime_platform.db")
mgr.generate_audit_report("data/database_audit_report.json")
missing = [c for c in mgr.characters.values() if not c.get("image") or c.get("image", "").startswith("/api/avatar") or "ui-avatars" in c.get("image", "")]
print(f"FINAL MISSING: {len(missing)}")
