"""
Multi-Anime Character Entity Models & Configurable Power Ranking Engine
=======================================================================
Implements:
- Unified Anime Character Schema
- Multi-tier Form / Transformation representation
- Normalized 1-100 Power Scoring Engine with configurable weights
- Source attribution and data confidence tracking
"""

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any
import math

# Configurable Power Ranking Weights (Section 3 of Specification)
SCORING_WEIGHTS = {
    "strength": 0.10,          # Physical strength: 10%
    "attack_power": 0.20,      # Attack power: 20%
    "speed": 0.15,             # Speed: 15%
    "durability": 0.15,        # Durability: 15%
    "stamina": 0.10,           # Stamina: 10%
    "defense": 0.10,           # Defense: 10%
    "intelligence": 0.05,      # Intelligence: 5%
    "battle_iq": 0.05,         # Battle IQ: 5%
    "special_abilities": 0.10   # Special abilities: 10%
}

TIER_THRESHOLDS = [
    (93.0, "S+"),
    (85.0, "S"),
    (70.0, "A"),
    (55.0, "B"),
    (40.0, "C"),
    (0.0, "D"),
]


def calculate_overall_power(stats: Dict[str, float], weights: Optional[Dict[str, float]] = None) -> float:
    """
    Calculates normalized overall power score from 1 to 100 based on weighted stats.
    """
    w = weights or SCORING_WEIGHTS
    score = (
        stats.get("strength", 50) * w["strength"] +
        stats.get("attack_power", 50) * w["attack_power"] +
        stats.get("speed", 50) * w["speed"] +
        stats.get("durability", 50) * w["durability"] +
        stats.get("stamina", 50) * w["stamina"] +
        stats.get("defense", 50) * w["defense"] +
        stats.get("intelligence", 50) * w["intelligence"] +
        stats.get("battle_iq", 50) * w["battle_iq"] +
        stats.get("special_abilities", 50) * w["special_abilities"]
    )
    return round(max(1.0, min(100.0, score)), 1)


def get_power_tier(power_rating: float) -> str:
    """Assigns ranking tier from power score."""
    for threshold, tier in TIER_THRESHOLDS:
        if power_rating >= threshold:
            return tier
    return "D"


@dataclass
class CharacterForm:
    form_id: str
    parent_character_id: str
    form_name: str
    image: str
    abilities: List[str] = field(default_factory=list)
    techniques: List[str] = field(default_factory=list)
    stats: Dict[str, float] = field(default_factory=dict)
    power_rating: float = 0.0
    power_tier: str = "B"
    source_reference: str = "Official Canon / Databooks"

    def __post_init__(self):
        if not self.power_rating and self.stats:
            self.power_rating = calculate_overall_power(self.stats)
        if not self.power_tier and self.power_rating:
            self.power_tier = get_power_tier(self.power_rating)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AnimeFranchise:
    id: str
    name: str
    japanese_name: str
    genre: List[str]
    energy_system: str
    logo_color: str
    description: str
    is_enabled: bool = True
    character_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AnimeCharacter:
    id: str
    name: str
    anime_id: str
    anime_name: str
    image: str
    gender: str = "Unknown"
    species: str = "Human"
    race: str = "Human"
    description: str = ""
    energy_system: str = "Standard"
    forms: List[Dict[str, Any]] = field(default_factory=list)
    abilities: List[str] = field(default_factory=list)
    techniques: List[str] = field(default_factory=list)
    weapons: List[str] = field(default_factory=list)
    stats: Dict[str, float] = field(default_factory=dict)
    power_rating: float = 50.0
    power_tier: str = "B"
    rarity: str = "Common"
    data_confidence: str = "High (Canon / Databook)"
    source: str = "Official Franchise Canon"
    is_enabled: bool = True
    # For transformation auction entry distinction
    current_form: Optional[str] = None
    parent_id: Optional[str] = None

    def __post_init__(self):
        if not self.power_rating and self.stats:
            self.power_rating = calculate_overall_power(self.stats)
        if not self.power_tier and self.power_rating:
            self.power_tier = get_power_tier(self.power_rating)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def sanitize_for_auction(self) -> Dict[str, Any]:
        """
        CRITICAL AUCTION PRIVACY:
        Reveals ONLY Character image, name, anime franchise name, and form (if applicable).
        Strictly hides all stats, strength, defense, speed, battle IQ, power rating, and tier!
        """
        data = {
            "id": self.id,
            "name": self.name,
            "anime_id": self.anime_id,
            "anime_name": self.anime_name,
            "image": self.image,
            "gender": self.gender,
            "species": self.species
        }
        if self.current_form:
            data["current_form"] = self.current_form
        return data


def sanitize_for_auction(char: Any) -> Dict[str, Any]:
    """Helper function to sanitize either an AnimeCharacter object or a dict."""
    if hasattr(char, "sanitize_for_auction"):
        return char.sanitize_for_auction()
    if not isinstance(char, dict):
        return {}
    res = {
        "id": char.get("id"),
        "name": char.get("name"),
        "anime_id": char.get("anime_id", "pokemon"),
        "anime_name": char.get("anime_name", "Pokémon"),
        "image": char.get("image", ""),
        "gender": char.get("gender", ""),
        "species": char.get("species", ""),
        "energy_system": char.get("energy_system", "")
    }
    if char.get("current_form"):
        res["current_form"] = char.get("current_form")
    if "official_pokedex_image" in char:
        res["official_pokedex_image"] = char["official_pokedex_image"]
    if "types" in char:
        res["types"] = char["types"]
    if "generation" in char:
        res["generation"] = char["generation"]
    return res

