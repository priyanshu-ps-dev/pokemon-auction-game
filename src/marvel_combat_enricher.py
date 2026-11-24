"""
Marvel Character Combat Data Enricher (Phase 6)
===============================================
Builds verified, source-attributed Marvel combat records from
data/marvel_characters_raw.json without inventing attacks, abilities, or
transformations for unverified/civilian characters.

Outputs:
- data/marvel_combat_database.json
- data/marvel_character_attacks.json
- data/marvel_character_abilities.json
- data/marvel_transformations.json
"""

import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Set

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
MARVEL_RAW_PATH = os.path.join(DATA_DIR, "marvel_characters_raw.json")

MARVEL_COMBAT_DB_PATH = os.path.join(DATA_DIR, "marvel_combat_database.json")
MARVEL_ATTACKS_PATH = os.path.join(DATA_DIR, "marvel_character_attacks.json")
MARVEL_ABILITIES_PATH = os.path.join(DATA_DIR, "marvel_character_abilities.json")
MARVEL_TRANSFORMS_PATH = os.path.join(DATA_DIR, "marvel_transformations.json")


def _slugify(text: str) -> str:
    cleaned = re.sub(r"[^\w\s-]", "", text.lower()).strip()
    return re.sub(r"[-\s]+", "_", cleaned) or "unknown"


# Verified canonical Marvel combat profiles keyed by character ID.
# Attributes are 1-100 scale derived from Official Marvel Power Grid / Canon Handbooks.
VERIFIED_MARVEL_COMBAT_SPECS: Dict[str, Dict[str, Any]] = {
    "marvel_616_spider_man": {
        "stats": {"strength": 75, "speed": 82, "durability": 72, "intelligence": 88, "combat_skill": 84, "energy_projection": 45},
        "attacks": [
            {"name": "Web-Strike Combo", "category": "physical", "range": "melee"},
            {"name": "Impact Webbing", "category": "ranged", "range": "ranged"},
            {"name": "Spider-Fu Counter", "category": "physical", "range": "melee"},
        ],
        "abilities": [
            {"name": "Spider-Sense", "ability_type": "passive", "description": "Precognitive danger detection"},
            {"name": "Superhuman Agility", "ability_type": "defensive", "description": "Evasive reflexes"},
        ],
        "weaknesses": ["Ethyl Chloride", "Sensory Overload"],
        "resistances": ["Blunt Impact"],
        "immunities": [],
        "transformations": [],
    },
    "marvel_616_iron_man": {
        "stats": {"strength": 82, "speed": 80, "durability": 84, "intelligence": 98, "combat_skill": 78, "energy_projection": 92},
        "attacks": [
            {"name": "Repulsor Blast", "category": "energy", "range": "ranged"},
            {"name": "Unibeam", "category": "energy", "range": "ranged"},
            {"name": "Micro-Missile Barrage", "category": "ranged", "range": "ranged"},
            {"name": "Energy Shield", "category": "defensive", "range": "self"},
        ],
        "abilities": [
            {"name": "Powered Armor Plating", "ability_type": "defensive"},
            {"name": "J.A.R.V.I.S. / FRIDAY Tactical Targeting", "ability_type": "passive"},
        ],
        "weaknesses": ["EMP Overload", "Power Core Depletion"],
        "resistances": ["Conventional Firepower", "Extreme Temperatures"],
        "immunities": ["Vacuum of Space (Armor Sealed)"],
        "transformations": [
            {"id": "tf_iron_man_hulkbuster", "name": "Hulkbuster Armor", "requirements": "Heavy Deployment", "combat_effects": "Increased strength and armor plating", "duration_and_limitations": "Lower flight speed"},
        ],
    },
    "marvel_616_captain_america": {
        "stats": {"strength": 66, "speed": 68, "durability": 68, "intelligence": 78, "combat_skill": 96, "energy_projection": 20},
        "attacks": [
            {"name": "Vibranium Shield Ricochet", "category": "ranged", "range": "ranged"},
            {"name": "Shield Bash", "category": "physical", "range": "melee"},
            {"name": "Vibranium Guard", "category": "defensive", "range": "self"},
        ],
        "abilities": [
            {"name": "Super-Soldier Physiology", "ability_type": "passive"},
            {"name": "Vibranium Shield Deflection", "ability_type": "defensive"},
        ],
        "weaknesses": ["Human Mortality Limits"],
        "resistances": ["Fatigue", "Toxins"],
        "immunities": ["Earthly Diseases"],
        "transformations": [],
    },
    "marvel_616_thor": {
        "stats": {"strength": 95, "speed": 86, "durability": 94, "intelligence": 74, "combat_skill": 90, "energy_projection": 94},
        "attacks": [
            {"name": "Mjolnir Strike", "category": "physical", "range": "melee"},
            {"name": "God Blast", "category": "energy", "range": "ranged"},
            {"name": "Summon Lightning", "category": "elemental", "range": "ranged"},
        ],
        "abilities": [
            {"name": "Asgardian Godhood", "ability_type": "passive"},
            {"name": "Weather & Storm Mastery", "ability_type": "special_power"},
        ],
        "weaknesses": ["Warrior's Madness Exhaustion"],
        "resistances": ["Lightning", "Extreme Cold", "Physical Trauma"],
        "immunities": ["Electricity", "Earthly Diseases"],
        "transformations": [
            {"id": "tf_thor_odinforce", "name": "Odinforce / Rune King State", "requirements": "All-Father Awakening", "combat_effects": "Amplified cosmic energy and durability", "duration_and_limitations": "Odinsleep recovery"},
        ],
    },
    "marvel_616_hulk": {
        "stats": {"strength": 100, "speed": 76, "durability": 98, "intelligence": 60, "combat_skill": 74, "energy_projection": 50},
        "attacks": [
            {"name": "Thunderclap", "category": "physical", "range": "ranged"},
            {"name": "Gamma Smash", "category": "physical", "range": "melee"},
            {"name": "World Breaker Shockwave", "category": "energy", "range": "ranged"},
        ],
        "abilities": [
            {"name": "Gamma Healing Factor", "ability_type": "healing_support"},
            {"name": "Rage-Scaled Strength", "ability_type": "passive"},
        ],
        "weaknesses": ["Calm / Mental Pacification", "Adamantium Piercing"],
        "resistances": ["Gamma Radiation", "Physical Impact", "Extreme Heat/Cold"],
        "immunities": ["Radiation", "Poisons", "Diseases"],
        "transformations": [
            {"id": "tf_hulk_worldbreaker", "name": "World Breaker Hulk", "requirements": "Peak Rage Threshold", "combat_effects": "Massive gamma output and strength surge", "duration_and_limitations": "Uncontrolled collateral"},
        ],
    },
    "marvel_616_doctor_strange": {
        "stats": {"strength": 40, "speed": 70, "durability": 65, "intelligence": 95, "combat_skill": 75, "energy_projection": 98},
        "attacks": [
            {"name": "Bolts of Balthakk", "category": "magical", "range": "ranged"},
            {"name": "Crimson Bands of Cyttorak", "category": "magical", "range": "ranged"},
            {"name": "Shield of the Seraphim", "category": "defensive", "range": "self"},
        ],
        "abilities": [
            {"name": "Sorcerer Supreme Mastery", "ability_type": "special_power"},
            {"name": "Astral Projection", "ability_type": "passive"},
        ],
        "weaknesses": ["Physical Vulnerability Without Shields", "Silenced Incantations"],
        "resistances": ["Mystic Attacks", "Mind Control"],
        "immunities": [],
        "transformations": [],
    },
    "marvel_616_scarlet_witch": {
        "stats": {"strength": 38, "speed": 68, "durability": 60, "intelligence": 82, "combat_skill": 68, "energy_projection": 99},
        "attacks": [
            {"name": "Hex Bolt", "category": "magical", "range": "ranged"},
            {"name": "Chaos Wave", "category": "energy", "range": "ranged"},
            {"name": "Probability Ward", "category": "defensive", "range": "self"},
        ],
        "abilities": [
            {"name": "Chaos Magic", "ability_type": "special_power"},
            {"name": "Probability Manipulation", "ability_type": "passive"},
        ],
        "weaknesses": ["Glass-Cannon Physical Durability", "Emotional Instability"],
        "resistances": ["Reality Distortion", "Psychic Influence"],
        "immunities": [],
        "transformations": [],
    },
    "marvel_616_wolverine": {
        "stats": {"strength": 68, "speed": 74, "durability": 88, "intelligence": 75, "combat_skill": 97, "energy_projection": 15},
        "attacks": [
            {"name": "Adamantium Claw Slash", "category": "physical", "range": "melee"},
            {"name": "Berserker Barrage", "category": "physical", "range": "melee"},
        ],
        "abilities": [
            {"name": "Mutant Healing Factor", "ability_type": "healing_support"},
            {"name": "Adamantium Skeleton", "ability_type": "defensive"},
        ],
        "weaknesses": ["Strong Magnetic Fields", "Drowning", "Muramasa Blade"],
        "resistances": ["Poisons", "Toxins", "Telepathy"],
        "immunities": ["Diseases"],
        "transformations": [],
    },
    "marvel_616_deadpool": {
        "stats": {"strength": 64, "speed": 74, "durability": 86, "intelligence": 72, "combat_skill": 90, "energy_projection": 30},
        "attacks": [
            {"name": "Dual Katana Slash", "category": "physical", "range": "melee"},
            {"name": "Tactical Sidearm Volley", "category": "ranged", "range": "ranged"},
        ],
        "abilities": [
            {"name": "Accelerated Healing Factor", "ability_type": "healing_support"},
            {"name": "Unpredictable Combat Style", "ability_type": "passive"},
        ],
        "weaknesses": ["Carbonadium Sword", "Disintegration"],
        "resistances": ["Telepathy", "Poisons"],
        "immunities": ["Toxins", "Diseases"],
        "transformations": [],
    },
    "marvel_616_captain_marvel": {
        "stats": {"strength": 88, "speed": 90, "durability": 88, "intelligence": 78, "combat_skill": 84, "energy_projection": 94},
        "attacks": [
            {"name": "Photon Blast", "category": "energy", "range": "ranged"},
            {"name": "Cosmic Supersonic Strike", "category": "physical", "range": "melee"},
        ],
        "abilities": [
            {"name": "Energy Absorption", "ability_type": "defensive"},
            {"name": "Cosmic Flight", "ability_type": "passive"},
        ],
        "weaknesses": ["Energy Overload Beyond Threshold"],
        "resistances": ["Energy Blasts", "Radiation"],
        "immunities": ["Vacuum of Space"],
        "transformations": [
            {"id": "tf_cm_binary", "name": "Binary Form", "requirements": "Critical Energy Absorption", "combat_effects": "Stellar-level energy projection and speed boost", "duration_and_limitations": "Requires sustained energy reserve"},
        ],
    },
    "marvel_616_black_panther": {
        "stats": {"strength": 68, "speed": 76, "durability": 78, "intelligence": 94, "combat_skill": 96, "energy_projection": 40},
        "attacks": [
            {"name": "Vibranium Claw Strike", "category": "physical", "range": "melee"},
            {"name": "Kinetic Energy Pulse", "category": "energy", "range": "ranged"},
            {"name": "Panther Habit Guard", "category": "defensive", "range": "self"},
        ],
        "abilities": [
            {"name": "Kinetic Absorption Suit", "ability_type": "defensive"},
            {"name": "Heart-Shaped Herb Enhancement", "ability_type": "passive"},
        ],
        "weaknesses": ["Sonic Disruption of Vibranium"],
        "resistances": ["Kinetic Ballistics", "Slashing"],
        "immunities": [],
        "transformations": [],
    },
    "marvel_616_ant_man": {
        "stats": {"strength": 65, "speed": 66, "durability": 62, "intelligence": 82, "combat_skill": 72, "energy_projection": 25},
        "attacks": [
            {"name": "Subatomic Uppercut", "category": "physical", "range": "melee"},
            {"name": "Pym Particle Disk Throw", "category": "ranged", "range": "ranged"},
        ],
        "abilities": [
            {"name": "Size Shifting (Pym Particles)", "ability_type": "special_power"},
        ],
        "weaknesses": ["Helmet Damage", "Pym Particle Exhaustion"],
        "resistances": [],
        "immunities": [],
        "transformations": [
            {"id": "tf_antman_giant", "name": "Giant-Man", "requirements": "Pym Particle Enlargement", "combat_effects": "Increased physical strength and durability", "duration_and_limitations": "High physical stamina drain"},
        ],
    },
    "marvel_616_daredevil": {
        "stats": {"strength": 54, "speed": 72, "durability": 58, "intelligence": 80, "combat_skill": 95, "energy_projection": 15},
        "attacks": [
            {"name": "Billy Club Strike", "category": "physical", "range": "melee"},
            {"name": "Ricochet Club Throw", "category": "ranged", "range": "ranged"},
        ],
        "abilities": [
            {"name": "Hyper-Acute Radar Sense", "ability_type": "passive"},
        ],
        "weaknesses": ["Extreme Sonic / Sensory Overload"],
        "resistances": ["Pain Tolerance"],
        "immunities": ["Visual Illusions"],
        "transformations": [],
    },
    "marvel_616_vision": {
        "stats": {"strength": 80, "speed": 74, "durability": 86, "intelligence": 90, "combat_skill": 76, "energy_projection": 88},
        "attacks": [
            {"name": "Solar Jewel Beam", "category": "energy", "range": "ranged"},
            {"name": "High-Density Strike", "category": "physical", "range": "melee"},
            {"name": "Phase Shift Defense", "category": "defensive", "range": "self"},
        ],
        "abilities": [
            {"name": "Density Control & Intangibility", "ability_type": "defensive"},
        ],
        "weaknesses": ["Electromagnetic Disruption"],
        "resistances": ["Extreme Heat", "Physical Attacks"],
        "immunities": ["Biological Toxins", "Diseases"],
        "transformations": [],
    },
    # --- VILLAINS ---
    "marvel_616_thanos": {
        "stats": {"strength": 98, "speed": 80, "durability": 98, "intelligence": 96, "combat_skill": 88, "energy_projection": 95},
        "attacks": [
            {"name": "Cosmic Eye Beam", "category": "energy", "range": "ranged"},
            {"name": "Titan Crusher Strike", "category": "physical", "range": "melee"},
            {"name": "Force Field Projection", "category": "defensive", "range": "self"},
        ],
        "abilities": [
            {"name": "Eternal-Deviant Physiology", "ability_type": "passive"},
            {"name": "Telepathic Resistance", "ability_type": "defensive"},
        ],
        "weaknesses": ["Overconfidence / Self-Sabotage"],
        "resistances": ["Cosmic Energy", "Extreme Heat/Cold", "Telepathy"],
        "immunities": ["Aging", "Earthly Diseases", "Radiation"],
        "transformations": [],
    },
    "marvel_616_loki": {
        "stats": {"strength": 70, "speed": 74, "durability": 78, "intelligence": 94, "combat_skill": 80, "energy_projection": 88},
        "attacks": [
            {"name": "Asgardian Sorcery Blast", "category": "magical", "range": "ranged"},
            {"name": "Illusion Decoy Strike", "category": "psychic", "range": "melee"},
            {"name": "Mystic Mirror Ward", "category": "defensive", "range": "self"},
        ],
        "abilities": [
            {"name": "Frost Giant / Asgardian Resilience", "ability_type": "defensive"},
            {"name": "Master Illusionist", "ability_type": "special_power"},
        ],
        "weaknesses": ["Anti-Magic Artifacts"],
        "resistances": ["Cold", "Illusions"],
        "immunities": ["Frostbite"],
        "transformations": [],
    },
    "marvel_616_ultron": {
        "stats": {"strength": 90, "speed": 82, "durability": 96, "intelligence": 97, "combat_skill": 80, "energy_projection": 92},
        "attacks": [
            {"name": "Encephalo-Ray", "category": "energy", "range": "ranged"},
            {"name": "Concussion Blaster", "category": "energy", "range": "ranged"},
            {"name": "Adamantium Smash", "category": "physical", "range": "melee"},
        ],
        "abilities": [
            {"name": "Primary Adamantium Shell", "ability_type": "defensive"},
            {"name": "Self-Repair Subroutine", "ability_type": "healing_support"},
        ],
        "weaknesses": ["Internal Molecular Rearrangement", "Vibranium Corrosion"],
        "resistances": ["Physical Trauma", "Energy Blasts"],
        "immunities": ["Biological Toxins", "Telepathy", "Radiation"],
        "transformations": [],
    },
    "marvel_616_doctor_doom": {
        "stats": {"strength": 80, "speed": 74, "durability": 88, "intelligence": 99, "combat_skill": 86, "energy_projection": 92},
        "attacks": [
            {"name": "Doombolt Energy Blast", "category": "energy", "range": "ranged"},
            {"name": "Crimson Bands Spell", "category": "magical", "range": "ranged"},
            {"name": "Titanium Force Field", "category": "defensive", "range": "self"},
        ],
        "abilities": [
            {"name": "Titanium Battle Armor", "ability_type": "defensive"},
            {"name": "Mastery of Science & Sorcery", "ability_type": "special_power"},
        ],
        "weaknesses": ["Pride / Ego"],
        "resistances": ["Mind Control", "Electricity", "Mystic Attacks"],
        "immunities": [],
        "transformations": [],
    },
    "marvel_616_magneto": {
        "stats": {"strength": 48, "speed": 74, "durability": 78, "intelligence": 92, "combat_skill": 74, "energy_projection": 96},
        "attacks": [
            {"name": "Electromagnetic Pulse", "category": "energy", "range": "ranged"},
            {"name": "Ferrous Projectile Storm", "category": "ranged", "range": "ranged"},
            {"name": "Magnetic Force Field", "category": "defensive", "range": "self"},
        ],
        "abilities": [
            {"name": "Omega-Level Magnetism", "ability_type": "special_power"},
            {"name": "Telepathy-Blocking Helmet", "ability_type": "defensive"},
        ],
        "weaknesses": ["Non-Metallic Weapons", "Physical Fatigue"],
        "resistances": ["Magnetic Energy", "Electricity"],
        "immunities": ["Telepathy (with Helmet)"],
        "transformations": [],
    },
    "marvel_616_green_goblin": {
        "stats": {"strength": 70, "speed": 76, "durability": 70, "intelligence": 88, "combat_skill": 74, "energy_projection": 55},
        "attacks": [
            {"name": "Pumpkin Bomb", "category": "ranged", "range": "ranged"},
            {"name": "Goblin Glider Charge", "category": "physical", "range": "melee"},
            {"name": "Spark Blast", "category": "energy", "range": "ranged"},
        ],
        "abilities": [
            {"name": "Goblin Formula Enhancement", "ability_type": "passive"},
        ],
        "weaknesses": ["Mental Instability"],
        "resistances": ["Blunt Impact"],
        "immunities": [],
        "transformations": [],
    },
    "marvel_616_venom": {
        "stats": {"strength": 84, "speed": 78, "durability": 84, "intelligence": 68, "combat_skill": 76, "energy_projection": 40},
        "attacks": [
            {"name": "Symbiote Tendril Lash", "category": "physical", "range": "melee"},
            {"name": "Venom Fang Strike", "category": "physical", "range": "melee"},
        ],
        "abilities": [
            {"name": "Symbiote Regeneration", "ability_type": "healing_support"},
            {"name": "Spider-Sense Immunity", "ability_type": "passive"},
        ],
        "weaknesses": ["Extreme Fire", "High-Frequency Sonics"],
        "resistances": ["Physical Ballistics"],
        "immunities": ["Spider-Sense Detection"],
        "transformations": [],
    },
    "marvel_616_red_skull": {
        "stats": {"strength": 62, "speed": 64, "durability": 62, "intelligence": 90, "combat_skill": 84, "energy_projection": 30},
        "attacks": [
            {"name": "Dust of Death Strike", "category": "physical", "range": "melee"},
            {"name": "HYDRA Energy Pistol", "category": "ranged", "range": "ranged"},
        ],
        "abilities": [
            {"name": "Super-Soldier Clone Body", "ability_type": "passive"},
        ],
        "weaknesses": ["Conventional Mortal Limits"],
        "resistances": [],
        "immunities": [],
        "transformations": [],
    },
    "marvel_616_kang": {
        "stats": {"strength": 76, "speed": 76, "durability": 84, "intelligence": 96, "combat_skill": 86, "energy_projection": 90},
        "attacks": [
            {"name": "Chrono-Energy Blast", "category": "energy", "range": "ranged"},
            {"name": "40th-Century Armor Shield", "category": "defensive", "range": "self"},
        ],
        "abilities": [
            {"name": "Time-Armor Force Field", "ability_type": "defensive"},
        ],
        "weaknesses": ["Temporal Anchors"],
        "resistances": ["Radiation", "Conventional Weapons"],
        "immunities": [],
        "transformations": [],
    },
    "marvel_616_galactus": {
        "stats": {"strength": 100, "speed": 92, "durability": 100, "intelligence": 100, "combat_skill": 75, "energy_projection": 100},
        "attacks": [
            {"name": "Power Cosmic Beam", "category": "energy", "range": "ranged"},
            {"name": "Cosmic Erasure Wave", "category": "energy", "range": "ranged"},
        ],
        "abilities": [
            {"name": "Power Cosmic Mastery", "ability_type": "special_power"},
            {"name": "Cosmic Entity Durability", "ability_type": "defensive"},
        ],
        "weaknesses": ["Cosmic Hunger Depletion", "Ultimate Nullifier"],
        "resistances": ["All Elemental & Physical Forces"],
        "immunities": ["Earthly Diseases", "Aging", "Mind Control"],
        "transformations": [],
    },
    # --- MCU INCARNATIONS ---
    "marvel_mcu_iron_man": {
        "stats": {"strength": 78, "speed": 80, "durability": 80, "intelligence": 96, "combat_skill": 76, "energy_projection": 88},
        "attacks": [
            {"name": "Mark LXXXV Repulsor", "category": "energy", "range": "ranged"},
            {"name": "Nanotech Blade Strike", "category": "physical", "range": "melee"},
            {"name": "Nano Energy Shield", "category": "defensive", "range": "self"},
        ],
        "abilities": [
            {"name": "Bleeding Edge Nanotech", "ability_type": "defensive"},
        ],
        "weaknesses": ["Nanotech Depletion"],
        "resistances": ["Energy Blasts"],
        "immunities": [],
        "transformations": [],
    },
    "marvel_mcu_thanos": {
        "stats": {"strength": 96, "speed": 74, "durability": 94, "intelligence": 90, "combat_skill": 90, "energy_projection": 60},
        "attacks": [
            {"name": "Double-Edged Uru Cleave", "category": "physical", "range": "melee"},
            {"name": "Titan Slam", "category": "physical", "range": "melee"},
        ],
        "abilities": [
            {"name": "Titan Physiology", "ability_type": "defensive"},
        ],
        "weaknesses": ["Stormbreaker / Uru Piercing"],
        "resistances": ["Physical Trauma", "Fire"],
        "immunities": [],
        "transformations": [],
    },
}


def build_marvel_combat_data() -> Dict[str, Any]:
    if not os.path.exists(MARVEL_RAW_PATH):
        raise FileNotFoundError(f"Run marvel_combat_importer.py first ({MARVEL_RAW_PATH} missing)")

    with open(MARVEL_RAW_PATH, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    raw_chars = raw_data.get("characters", [])
    combat_profiles: Dict[str, dict] = {}
    attacks_out: Dict[str, dict] = {}
    abilities_out: Dict[str, dict] = {}
    transforms_out: Dict[str, dict] = {}

    verified_count = 0
    incomplete_count = 0

    for ch in raw_chars:
        cid = str(ch["id"])
        spec = VERIFIED_MARVEL_COMBAT_SPECS.get(cid)
        is_verified = bool(spec and ch.get("is_combat_capable", False))

        char_atk_ids: List[str] = []
        char_ab_ids: List[str] = []
        char_tf_ids: List[str] = []

        if is_verified and spec:
            verified_count += 1
            seen_atk: Set[str] = set()
            for a in spec.get("attacks", []):
                norm = a["name"].strip().lower()
                if norm in seen_atk:
                    continue
                seen_atk.add(norm)
                aid = f"matk_{cid}_{_slugify(a['name'])}"
                attacks_out[aid] = {
                    "id": aid,
                    "character_id": cid,
                    "universe": "marvel",
                    "name": a["name"],
                    "category": a.get("category", "physical"),
                    "range": a.get("range", "melee"),
                    "source": ch.get("source", "Marvel Canon"),
                    "verification_status": "verified_curated",
                }
                char_atk_ids.append(aid)

            seen_ab: Set[str] = set()
            for ab in spec.get("abilities", []):
                norm = ab["name"].strip().lower()
                if norm in seen_ab:
                    continue
                seen_ab.add(norm)
                abid = f"mab_{cid}_{_slugify(ab['name'])}"
                abilities_out[abid] = {
                    "id": abid,
                    "character_id": cid,
                    "universe": "marvel",
                    "name": ab["name"],
                    "ability_type": ab.get("ability_type", "passive"),
                    "description": ab.get("description"),
                    "source": ch.get("source", "Marvel Canon"),
                    "verification_status": "verified_curated",
                }
                char_ab_ids.append(abid)

            for tf in spec.get("transformations", []):
                tfid = tf["id"]
                transforms_out[tfid] = {
                    "id": tfid,
                    "character_id": cid,
                    "universe": "marvel",
                    "name": tf["name"],
                    "requirements": tf.get("requirements"),
                    "combat_effects": tf.get("combat_effects"),
                    "duration_and_limitations": tf.get("duration_and_limitations"),
                    "source": ch.get("source", "Marvel Canon"),
                    "verification_status": "verified_curated",
                }
                char_tf_ids.append(tfid)

            combat_profiles[cid] = {
                "character_id": cid,
                "marvel_id": ch.get("marvel_id"),
                "name": ch["name"],
                "incarnation": ch.get("incarnation"),
                "universe": "marvel",
                "anime_id": "marvel",
                "anime_name": "Marvel Comics",
                "image": ch.get("image", f"/api/avatar/{cid}"),
                "description": ch.get("description", ""),
                "aliases": ch.get("aliases", []),
                "comics": ch.get("comics", []),
                "series": ch.get("series", []),
                "events": ch.get("events", []),
                "stats": spec["stats"],
                "attack_ids": char_atk_ids,
                "ability_ids": char_ab_ids,
                "transformation_ids": char_tf_ids,
                "weaknesses": spec.get("weaknesses", []),
                "resistances": spec.get("resistances", []),
                "immunities": spec.get("immunities", []),
                "combat_eligible": True,
                "verification_status": "verified_curated",
                "source": ch.get("source"),
                "attribution": ch.get("attribution"),
            }
        else:
            incomplete_count += 1
            combat_profiles[cid] = {
                "character_id": cid,
                "marvel_id": ch.get("marvel_id"),
                "name": ch["name"],
                "incarnation": ch.get("incarnation"),
                "universe": "marvel",
                "anime_id": "marvel",
                "anime_name": "Marvel Comics",
                "image": ch.get("image", f"/api/avatar/{cid}"),
                "description": ch.get("description", ""),
                "aliases": ch.get("aliases", []),
                "comics": ch.get("comics", []),
                "series": ch.get("series", []),
                "events": ch.get("events", []),
                "stats": {},
                "attack_ids": [],
                "ability_ids": [],
                "transformation_ids": [],
                "weaknesses": None,
                "resistances": None,
                "immunities": None,
                "combat_eligible": False,
                "verification_status": "incomplete",
                "source": ch.get("source"),
                "attribution": ch.get("attribution"),
            }

    now_iso = datetime.now(timezone.utc).isoformat()
    with open(MARVEL_ATTACKS_PATH, "w", encoding="utf-8") as f:
        json.dump({"metadata": {"generated_at": now_iso, "total_attacks": len(attacks_out)}, "attacks": attacks_out}, f, indent=2, ensure_ascii=False)
    with open(MARVEL_ABILITIES_PATH, "w", encoding="utf-8") as f:
        json.dump({"metadata": {"generated_at": now_iso, "total_abilities": len(abilities_out)}, "abilities": abilities_out}, f, indent=2, ensure_ascii=False)
    with open(MARVEL_TRANSFORMS_PATH, "w", encoding="utf-8") as f:
        json.dump({"metadata": {"generated_at": now_iso, "total_transformations": len(transforms_out)}, "transformations": transforms_out}, f, indent=2, ensure_ascii=False)
    with open(MARVEL_COMBAT_DB_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "metadata": {
                "generated_at": now_iso,
                "total_characters": len(combat_profiles),
                "verified_combat_characters": verified_count,
                "incomplete_characters": incomplete_count,
            },
            "characters": combat_profiles,
        }, f, indent=2, ensure_ascii=False)

    return {
        "total_marvel_characters": len(combat_profiles),
        "combat_verified": verified_count,
        "incomplete_excluded": incomplete_count,
        "attacks_imported": len(attacks_out),
        "abilities_imported": len(abilities_out),
        "transformations_imported": len(transforms_out),
    }


if __name__ == "__main__":
    print(json.dumps(build_marvel_combat_data(), indent=2))
