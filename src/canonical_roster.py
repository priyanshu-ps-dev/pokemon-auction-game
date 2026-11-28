"""Curated auction identities and screen-continuity combat records."""

import json
from pathlib import Path
import unicodedata


def normalized_name(value):
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(character for character in decomposed if character.isalnum())


def pokemon_species(character):
    return character.get("national_id") or character.get("pokemon_id") or character["id"]


def _power_tier(power_rating):
    for threshold, tier in ((93, "S+"), (85, "S"), (70, "A"), (55, "B"), (40, "C")):
        if power_rating >= threshold:
            return tier
    return "D"


def load_mcu_roster(data_dir):
    path = Path(data_dir) / "mcu_roster.tsv"
    if not path.is_file():
        return {}
    profiles_path = Path(data_dir) / "mcu_profiles.json"
    profiles = json.loads(profiles_path.read_text(encoding="utf-8")) if profiles_path.is_file() else {}
    roster = {}
    identities = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        key, name, aliases, source, strength, speed, durability, energy, attacks = line.split("|")
        character_id = f"marvel_mcu_{key}"
        profile = profiles.get(key, {})
        attack_records = [
            {
                "id": normalized_name(move),
                "name": move,
                "category": category,
                "element_or_energy_type": category,
                "range": "contact" if move == "Contact Sleep" else "",
                "source": source,
            }
            for move, category in (attack.split(":") for attack in attacks.split(";"))
        ]
        combat_skill = 60
        numeric_stats = {
            "strength": int(strength),
            "attack_power": max(int(strength), int(energy)),
            "speed": int(speed),
            "durability": int(durability),
            "stamina": round((int(strength) + int(durability)) / 2),
            "defense": round((int(speed) + int(durability)) / 2),
            "intelligence": combat_skill,
            "battle_iq": combat_skill,
            "special_abilities": int(energy),
            "energy_projection": int(energy),
            "combat_skill": combat_skill,
        }
        power_rating = round(
            int(strength) * 0.25
            + int(speed) * 0.20
            + int(durability) * 0.25
            + int(energy) * 0.20
            + combat_skill * 0.10,
            1,
        )
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
            "alt_names": aliases.split(";") if aliases else [],
            "source": source,
            "image": f"/assets/avatars/marvel/{key}.jpg",
            "image_verification_status": "verified_local_portrait",
            "artwork_kind": "local_mcu_character_portrait",
            "role": profile.get("role", "MCU fighter"),
            "category": profile.get("role", "MCU fighter"),
            "species": profile.get("species", "Unknown"),
            "description": profile.get("description", f"{name} as represented in {source}."),
            "portrait_emblem": profile.get("emblem", name[:2].upper()),
            "portrait_colors": profile.get("colors", ["#b91c1c", "#f59e0b"]),
            "stats": numeric_stats,
            "power_rating": power_rating,
            "power_tier": _power_tier(power_rating),
            "canonical_bst": sum((int(strength), int(speed), int(durability), int(energy), combat_skill)),
            "rarity": "MCU Curated",
            "energy_system": "MCU abilities and equipment",
            "abilities": [
                {
                    "id": f"{record['id']}_ability",
                    "name": record["name"],
                    "ability_type": record["category"],
                    "description": f"Signature {record['category']} capability from {source}.",
                }
                for record in attack_records
            ],
            "techniques": [record["name"] for record in attack_records],
            "attacks": attack_records,
            "combat_eligible": True,
            "verification_status": "verified_curated",
        }
    return roster
