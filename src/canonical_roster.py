"""Curated auction identities and screen-continuity combat records."""

from pathlib import Path
import unicodedata


def normalized_name(value):
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(character for character in decomposed if character.isalnum())


def pokemon_species(character):
    return character.get("national_id") or character.get("pokemon_id") or character["id"]


def load_mcu_roster(data_dir):
    path = Path(data_dir) / "mcu_roster.tsv"
    if not path.is_file():
        return {}
    roster = {}
    identities = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        key, name, aliases, source, strength, speed, durability, energy, attacks = line.split("|")
        character_id = f"marvel_mcu_{key}"
        identity = normalized_name(name)
        if character_id in roster or identity in identities:
            raise ValueError(f"Duplicate MCU character: {name}")
        identities.add(identity)
        roster[character_id] = {
            "id": character_id,
            "canonical_id": character_id,
            "character_id": character_id,
            "name": name,
            "universe": "marvel",
            "anime_id": "marvel",
            "anime_name": "Marvel Cinematic Universe",
            "incarnation": "MCU screen continuity",
            "profile_version": 1,
            "aliases": aliases.split(";") if aliases else [],
            "source": source,
            "image": f"/api/avatar/{character_id}",
            "stats": {
                "strength": int(strength),
                "speed": int(speed),
                "durability": int(durability),
                "energy_projection": int(energy),
                "combat_skill": 60,
            },
            "attacks": [
                {
                    "id": normalized_name(move),
                    "name": move,
                    "category": category,
                    "element_or_energy_type": category,
                    "range": "contact" if move == "Contact Sleep" else "",
                    "source": source,
                }
                for move, category in (attack.split(":") for attack in attacks.split(";"))
            ],
            "combat_eligible": True,
            "verification_status": "verified_curated",
        }
    return roster
