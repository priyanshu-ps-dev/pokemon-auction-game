import json
import time
import urllib.request

QUERY = """
query ($search: String) {
  Character(search: $search) {
    id
    name {
      full
    }
    image {
      large
    }
  }
}
"""

def fetch_img(query_str):
    req = urllib.request.Request(
        "https://graphql.anilist.co",
        data=json.dumps({"query": QUERY, "variables": {"search": query_str}}).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            c = data.get("data", {}).get("Character")
            if c and c.get("image"):
                return c["image"].get("large")
    except Exception as e:
        print(f"Error {query_str}: {e}")
    return None

specific_names = {
    "db_beerus": "Beerus",
    "db_gogeta": "Gogeta",
    "db_vegito": "Vegetto",
    "naruto_obito": "Obito Uchiha",
    "naruto_neji": "Neji Hyuuga",
    "op_shanks": "Shanks",
    "op_sanji": "Sanji",
    "bleach_aizen": "Sousuke Aizen",
    "bleach_yamamoto": "Genryuusai Shigekuni Yamamoto",
    "jjk_sukuna": "Sukuna",
    "jjk_yuta": "Yuuta Okkotsu",
    "jjk_toji": "Touji Fushiguro",
    "ds_yoriichi": "Yoriichi Tsugikuni",
    "opm_boros": "Boros",
    "sl_jinwoo": "Jinwoo Sung",
    "sl_igris": "Igris",
    "aot_levi": "Levi",
    "mha_allmight": "Toshinori Yagi",
    "jojo_jotaro": "Joutarou Kuujou",
    "jojo_dio": "Dio Brando",
    "hq_hinata": "Shouyou Hinata",
    "bl_nagi": "Seishirou Nagi"
}

with open("data/anime_database.json", "r", encoding="utf-8") as f:
    db = json.load(f)

char_map = {c["id"]: c for c in db["characters"]}

for cid, query_name in specific_names.items():
    if cid in char_map:
        c = char_map[cid]
        if not c.get("image") or c.get("image", "").startswith("/api/avatar") or "ui-avatars" in c.get("image", ""):
            print(f"Fetching {cid} -> {query_name}...")
            img = fetch_img(query_name)
            if img:
                c["image"] = img
                c["image_verified"] = 1
                print(f"  Got: {img[:60]}")
            else:
                print(f"  Failed: {query_name}")
            time.sleep(1.2)

with open("data/anime_database.json", "w", encoding="utf-8") as f:
    json.dump(db, f, indent=2, ensure_ascii=False)

from src.anime_database import AnimeDatabaseManager
mgr = AnimeDatabaseManager("data/anime_database.json", "data/anime_platform.db")
mgr.generate_audit_report("data/database_audit_report.json")
missing_after = [c for c in mgr.characters.values() if not c.get("image") or c.get("image", "").startswith("/api/avatar")]
print(f"Missing images after: {len(missing_after)}")
