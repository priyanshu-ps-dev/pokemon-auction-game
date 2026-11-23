import json

with open("data/anime_database.json", "r", encoding="utf-8") as f:
    db = json.load(f)

missing = [c for c in db["characters"] if not c.get("image") or c.get("image", "").startswith("/api/avatar")]
print(f"Missing count: {len(missing)}")

for mc in missing:
    mid = mc["id"]
    fid = mc.get("anime_id")
    # Search in same franchise for any character sharing core name
    candidates = [c for c in db["characters"] if c["id"] != mid and c.get("anime_id") == fid and c.get("image", "").startswith("http")]
    
    words = [w for w in mc["name"].lower().replace("(", "").replace(")", "").split() if w not in ["lord", "the", "son", "of", "and"]]
    matched = None
    for c in candidates:
        c_words = [w for w in c["name"].lower().replace("(", "").replace(")", "").split() if w not in ["lord", "the", "son", "of", "and"]]
        if set(words) & set(c_words):
            matched = c
            break
            
    if matched:
        print(f"MATCH: {mid} ('{mc['name']}') -> {matched['id']} ('{matched['name']}'): {matched['image'][:50]}")
        # Merge by transferring real image to mc, or merge mc into matched
        mc["image"] = matched["image"]
        mc["image_verified"] = 1
        if matched["id"].startswith(f"{fid}_"):
            # If matched is also a mock duplicate, we can consolidate
            pass
    else:
        print(f"NO MATCH: {mid} ('{mc['name']}') in {fid}")

# Save updated db
with open("data/anime_database.json", "w", encoding="utf-8") as f:
    json.dump(db, f, indent=2, ensure_ascii=False)
