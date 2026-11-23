import json

with open('data/database_audit_report.json', 'r', encoding='utf-8') as f:
    r = json.load(f)

tot_f = r['total_franchises']
tot_c = r['total_characters']
print(f"Total Franchises: {tot_f}, Total Characters: {tot_c}")
print("=" * 85)
print(f"{'FRANCHISE':<30} | {'UNIQUE':<8} | {'VERIFIED IMG':<14} | {'TARGET':<6} | {'STATUS'}")
print("-" * 85)
for f in r['franchise_audit']:
    fn = f['name']
    uc = f['unique_characters']
    vi = f['verified_images']
    tg = f['target']
    st = f['status']
    print(f"{fn:<30} | {uc:<8} | {vi:<14} | {tg:<6} | {st}")
print("=" * 85)
