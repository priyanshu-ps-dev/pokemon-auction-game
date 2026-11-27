"""Report the active draft pool without changing source records."""

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.anime_database import AnimeDatabaseManager


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    data = ROOT / "data"
    db = AnimeDatabaseManager(str(data / "anime_database.json"), str(data / "anime_platform.db"))
    roster = db.get_characters_for_mode()
    catalog = json.loads((data / "anime_database.json").read_text())["characters"]
    raw_marvel = json.loads((data / "marvel_combat_database.json").read_text())["characters"]
    active_ids = {character["id"] for character in roster}
    counts = Counter(character["anime_id"] for character in roster)
    report = {
        "source_character_records": len(catalog) + len(raw_marvel),
        "active_draft_characters": len(roster),
        "inactive_anime_records": sum(
            character["anime_id"] != "pokemon" and character["id"] not in active_ids
            for character in catalog
        ),
        "pokemon_alternate_records_excluded": sum(
            character["anime_id"] == "pokemon" and character["id"] not in active_ids
            for character in catalog
        ),
        "archived_marvel_records_excluded": len(raw_marvel.keys() - active_ids),
        "mcu_retained_ids": sorted(cid for cid in active_ids if cid.startswith("marvel_mcu_")),
        "draft_counts_by_franchise": dict(sorted(counts.items())),
    }
    result = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.write_text(result)
    else:
        print(result, end="")


if __name__ == "__main__":
    main()
