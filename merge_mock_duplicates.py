import json

with open('data/anime_database.json', 'r', encoding='utf-8') as f:
    db = json.load(f)

# Old mock prefix IDs
mock_ids = [c['id'] for c in db['characters'] if c['id'].startswith(('db_', 'naruto_', 'op_', 'bleach_', 'jjk_', 'ds_', 'opm_', 'sl_', 'mha_', 'jojo_', 'hq_', 'bl_')) and (not c.get('image') or c.get('image', '').startswith('/api/avatar'))]

print(f"Found {len(mock_ids)} mock prefix characters to merge/repair")

# Create a mapping of key names to anilist characters
anilist_chars = [c for c in db['characters'] if c['id'].startswith('anilist_')]

def clean_toks(s):
    import re
    return set(re.findall(r'[a-z0-9]+', s.lower())) - {'the', 'of', 'd', 'no', 'and', 'a', 'son', 'lord'}

merged_count = 0
chars_to_remove = set()

for mid in mock_ids:
    mock_c = next(c for c in db['characters'] if c['id'] == mid)
    m_toks = clean_toks(mock_c['name'])
    m_fid = mock_c.get('anime_id')
    
    # Find matching anilist character in same franchise
    best_match = None
    best_overlap = 0
    for ac in anilist_chars:
        if ac.get('anime_id') != m_fid:
            continue
        a_toks = clean_toks(ac['name'])
        overlap = len(m_toks & a_toks)
        if overlap > best_overlap:
            best_overlap = overlap
            best_match = ac
            
    if best_match and best_overlap >= 1:
        # Merge mock_c into best_match or update mock_c with best_match data
        # Prompt requires: "Treat them as a single character. Do not create two entries... Merge the records."
        # Update best_match with better English name if needed, keep anilist image, merge abilities/forms
        print(f"Merging {mid} ('{mock_c['name']}') into {best_match['id']} ('{best_match['name']}')")
        if not best_match.get('forms') and mock_c.get('forms'):
            best_match['forms'] = mock_c['forms']
        if not best_match.get('techniques') and mock_c.get('techniques'):
            best_match['techniques'] = mock_c['techniques']
        # Add alt name
        if 'alt_names' not in best_match or not best_match['alt_names']:
            best_match['alt_names'] = []
        if mock_c['name'] not in best_match['alt_names'] and mock_c['name'] != best_match['name']:
            best_match['alt_names'].append(mock_c['name'])
        
        # Prefer canonical western order name if cleaner
        if " " in mock_c['name'] and not best_match['name'].endswith(mock_c['name'].split()[-1]):
            pass # keep best_match or refine
        
        chars_to_remove.add(mid)
        merged_count += 1
    else:
        print(f"No AniList match found for {mid} ('{mock_c['name']}') in {m_fid}")

print(f"Total merged and removed: {merged_count}")
db['characters'] = [c for c in db['characters'] if c['id'] not in chars_to_remove]
print(f"Remaining characters: {len(db['characters'])}")

with open('data/anime_database.json', 'w', encoding='utf-8') as f:
    json.dump(db, f, indent=2, ensure_ascii=False)
