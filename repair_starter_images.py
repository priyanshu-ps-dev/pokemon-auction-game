import json
from src.anime_database import AnimeDatabaseManager

db = AnimeDatabaseManager('data/anime_database.json', 'data/anime_platform.db')
missing = [c for c in db.characters.values() if not c.get('image') or c.get('image', '').startswith('/api/avatar') or 'ui-avatars' in c.get('image', '')]
print(f"Total missing before: {len(missing)}")

# For characters with anilist_id or matching anilist character:
# Let's see if we can get real image from Anilist characters in the database or fetch via Anilist
with open('data/anime_database.json', 'r', encoding='utf-8') as f:
    raw_data = json.load(f)

char_map = {c['id']: c for c in raw_data['characters']}

# Build name index of characters with verified CDN images
cdn_chars = {}
for c in raw_data['characters']:
    img = c.get('image', '')
    if img and img.startswith('http') and not 'ui-avatars' in img:
        name_key = (c.get('anime_id', ''), c['name'].strip().lower())
        cdn_chars[name_key] = img

repaired = 0
for cid, c in char_map.items():
    img = c.get('image', '')
    if not img or img.startswith('/api/avatar') or 'ui-avatars' in img:
        name_key = (c.get('anime_id', ''), c['name'].strip().lower())
        if name_key in cdn_chars:
            c['image'] = cdn_chars[name_key]
            c['image_verified'] = 1
            repaired += 1
        else:
            # Check partial match in same franchise
            for (fid, n), cdn_img in cdn_chars.items():
                if fid == c.get('anime_id') and (n in c['name'].lower() or c['name'].lower() in n):
                    c['image'] = cdn_img
                    c['image_verified'] = 1
                    repaired += 1
                    break

print(f"Repaired via matching: {repaired}")
still_missing = [c for c in raw_data['characters'] if not c.get('image') or c.get('image', '').startswith('/api/avatar') or 'ui-avatars' in c.get('image', '')]
print(f"Still missing: {len(still_missing)}")
for c in still_missing:
    print(c['id'], c['name'], c['anime_id'])
