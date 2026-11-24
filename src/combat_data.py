"""
Unified Combat Data Access Interface (Phase 1)
==============================================
Provides a shared, read-only interface for retrieving structured combat data
for both Pokémon and non-Pokémon anime characters without forcing identical
combat mechanics across universes.
"""

import json
import os
from typing import Any, Dict, List, Optional, Union

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DATA_DIR = os.path.join(BASE_DIR, "data")


def _load_json(path: str) -> Any:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


class CombatDataProvider:
    """
    Shared data-access layer for Pokémon and Anime combat datasets.
    Preserves universe-specific mechanics (Pokémon moves/types/abilities vs.
    anime techniques/energy systems/transformations).
    """

    def __init__(self, data_dir: str = DEFAULT_DATA_DIR):
        self.data_dir = data_dir

        # Pokémon datasets
        raw_pokemon = _load_json(os.path.join(data_dir, "pokemon_database.json"))
        self.pokemon_by_id: Dict[int, dict] = (
            {p["id"]: p for p in raw_pokemon} if isinstance(raw_pokemon, list) else {}
        )
        self.moves_by_id: Dict[int, dict] = {
            int(k): v
            for k, v in _load_json(os.path.join(data_dir, "moves_database.json")).get("moves", {}).items()
        }
        self.pokemon_learnsets: Dict[int, dict] = {
            int(k): v
            for k, v in _load_json(os.path.join(data_dir, "pokemon_learnsets.json")).get("learnsets", {}).items()
        }
        raw_pkmn_abilities = _load_json(os.path.join(data_dir, "pokemon_abilities.json")).get("abilities", {})
        self.pokemon_abilities_by_id: Dict[int, dict] = {int(k): v for k, v in raw_pkmn_abilities.items()}
        self.pokemon_abilities_by_name: Dict[str, dict] = {
            v["name"].lower(): v for v in raw_pkmn_abilities.values() if v.get("name")
        }

        # Anime datasets
        raw_anime = _load_json(os.path.join(data_dir, "anime_database.json"))
        self.anime_chars_by_id: Dict[str, dict] = {
            str(c["id"]): c for c in raw_anime.get("characters", []) if isinstance(c, dict) and "id" in c
        }
        self.anime_combat_by_id: Dict[str, dict] = _load_json(
            os.path.join(data_dir, "anime_combat_database.json")
        ).get("characters", {})
        self.anime_attacks_by_id: Dict[str, dict] = _load_json(
            os.path.join(data_dir, "anime_character_attacks.json")
        ).get("attacks", {})
        self.anime_abilities_by_id: Dict[str, dict] = _load_json(
            os.path.join(data_dir, "anime_character_abilities.json")
        ).get("abilities", {})
        self.anime_transformations_by_id: Dict[str, dict] = _load_json(
            os.path.join(data_dir, "anime_transformations.json")
        ).get("transformations", {})

    def _resolve_pokemon_id(self, identifier: Union[int, str, dict]) -> Optional[int]:
        if isinstance(identifier, int):
            return identifier if identifier in self.pokemon_by_id else None
        if isinstance(identifier, str):
            if identifier.startswith("pkmn_"):
                try:
                    pid = int(identifier.split("_", 1)[1])
                    return pid if pid in self.pokemon_by_id else None
                except ValueError:
                    return None
            if identifier.isdigit():
                pid = int(identifier)
                return pid if pid in self.pokemon_by_id else None
            return None
        if isinstance(identifier, dict):
            if "pokemon_id" in identifier and isinstance(identifier["pokemon_id"], int):
                return identifier["pokemon_id"]
            if identifier.get("anime_id") == "pokemon" or "national_id" in identifier:
                raw_id = identifier.get("id")
                if isinstance(raw_id, int):
                    return raw_id if raw_id in self.pokemon_by_id else None
                if isinstance(raw_id, str):
                    return self._resolve_pokemon_id(raw_id)
        return None

    def get_pokemon_move(self, move_id: int) -> Optional[dict]:
        return self.moves_by_id.get(move_id)

    def get_pokemon_ability(self, name_or_id: Union[int, str]) -> Optional[dict]:
        if isinstance(name_or_id, int):
            return self.pokemon_abilities_by_id.get(name_or_id)
        return self.pokemon_abilities_by_name.get(str(name_or_id).strip().lower())

    def get_pokemon_learnset(self, pokemon_id: int) -> Optional[dict]:
        return self.pokemon_learnsets.get(pokemon_id)

    def get_anime_attacks(self, character_id: str) -> List[dict]:
        profile = self.anime_combat_by_id.get(str(character_id))
        if not profile:
            return []
        return [
            self.anime_attacks_by_id[aid]
            for aid in profile.get("attack_ids", [])
            if aid in self.anime_attacks_by_id
        ]

    def get_anime_abilities(self, character_id: str) -> List[dict]:
        profile = self.anime_combat_by_id.get(str(character_id))
        if not profile:
            return []
        return [
            self.anime_abilities_by_id[aid]
            for aid in profile.get("ability_ids", [])
            if aid in self.anime_abilities_by_id
        ]

    def get_anime_transformations(self, character_id: str) -> List[dict]:
        profile = self.anime_combat_by_id.get(str(character_id))
        if not profile:
            return []
        return [
            self.anime_transformations_by_id[tid]
            for tid in profile.get("transformation_ids", [])
            if tid in self.anime_transformations_by_id
        ]

    def get_combat_profile(self, character_or_id: Union[int, str, dict]) -> Optional[dict]:
        """
        Retrieves a normalized combat profile for either a Pokémon or an anime character.
        Preserves universe-specific mechanics without cross-universe distortion.
        """
        pid = self._resolve_pokemon_id(character_or_id)
        if pid is not None:
            poke = self.pokemon_by_id[pid]
            learnset = self.pokemon_learnsets.get(pid, {})
            default_move_ids = learnset.get("default_moveset", [])
            resolved_moves = [self.moves_by_id[mid] for mid in default_move_ids if mid in self.moves_by_id]
            resolved_abilities = []
            mapped_abilities = learnset.get("abilities", [])
            if mapped_abilities:
                for ab_map in mapped_abilities:
                    ab_meta = self.get_pokemon_ability(ab_map["ability_id"]) or {}
                    resolved_abilities.append({
                        **ab_meta,
                        "ability_id": ab_map["ability_id"],
                        "name": ab_map["name"],
                        "slot": ab_map.get("slot", 1),
                        "is_hidden": ab_map.get("is_hidden", False),
                    })
            else:
                for idx, ab_name in enumerate(poke.get("abilities", []), start=1):
                    ab_meta = self.get_pokemon_ability(ab_name)
                    resolved_abilities.append(
                        {**ab_meta, "slot": idx, "is_hidden": False}
                        if ab_meta
                        else {"name": ab_name, "short_effect": None, "slot": idx, "is_hidden": False}
                    )

            return {
                "system": "pokemon",
                "character_id": f"pkmn_{pid}",
                "pokemon_id": pid,
                "national_id": poke.get("national_id"),
                "name": poke.get("name"),
                "anime_id": "pokemon",
                "anime_name": "Pokémon",
                "is_default": poke.get("is_default", True),
                "is_legendary": poke.get("is_legendary", False),
                "is_mythical": poke.get("is_mythical", False),
                "types": poke.get("types", []),
                "stats": poke.get("stats", {}),
                "abilities": resolved_abilities,
                "default_moveset": resolved_moves,
                "learnable_move_ids": learnset.get("learnable_move_ids", []),
                "learnset_source": learnset.get("learnset_source", "none_available"),
            }

        # Non-Pokémon anime character lookup
        cid = str(character_or_id.get("id") or character_or_id.get("character_id")) if isinstance(character_or_id, dict) else str(character_or_id)
        profile = self.anime_combat_by_id.get(cid)
        if not profile:
            return None

        base_char = self.anime_chars_by_id.get(cid, {})
        return {
            "system": "anime",
            "character_id": cid,
            "name": profile.get("name") or base_char.get("name"),
            "anime_id": profile.get("anime_id"),
            "anime_name": profile.get("anime_name"),
            "energy_system": profile.get("energy_system"),
            "stats": base_char.get("stats", {}),
            "attacks": self.get_anime_attacks(cid),
            "abilities": self.get_anime_abilities(cid),
            "transformations": self.get_anime_transformations(cid),
            "weapons": profile.get("weapons", []),
            "weaknesses": profile.get("weaknesses"),
            "resistances": profile.get("resistances"),
            "immunities": profile.get("immunities"),
            "status_effects_inflicted": profile.get("status_effects_inflicted"),
            "status_effects_resisted": profile.get("status_effects_resisted"),
            "canon_status": profile.get("canon_status"),
            "verification_status": profile.get("verification_status"),
            "source": profile.get("source"),
        }
