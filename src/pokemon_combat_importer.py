"""
Pokémon Combat Data Importer (Phase 1)
======================================
Enriches the existing Pokémon database with official PokéAPI v2 combat data:
- data/moves_database.json      : Official move catalogue (power, accuracy, PP, type, category, priority, target, status/meta, stat changes)
- data/pokemon_abilities.json   : Official ability catalogue with descriptions & metadata
- data/pokemon_learnsets.json   : Official per-Pokémon learnsets (all 1,351 entries including alternate forms) + legal <=4-move default sets

Reuses cached CSVs in cache/ wherever possible and never invents or fabricates moves.
"""

import csv
import json
import os
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(BASE_DIR, "cache")
DATA_DIR = os.path.join(BASE_DIR, "data")
POKEMON_JSON_PATH = os.path.join(DATA_DIR, "pokemon_database.json")

MOVES_OUT_PATH = os.path.join(DATA_DIR, "moves_database.json")
ABILITIES_OUT_PATH = os.path.join(DATA_DIR, "pokemon_abilities.json")
LEARNSETS_OUT_PATH = os.path.join(DATA_DIR, "pokemon_learnsets.json")

POKEAPI_CSV_BASE = "https://raw.githubusercontent.com/PokeAPI/pokeapi/master/data/v2/csv"

# Distinct cache filenames so existing cache/abilities.csv and cache/stats.csv are never overwritten
CSV_SOURCES: Dict[str, str] = {
    "moves.csv": f"{POKEAPI_CSV_BASE}/moves.csv",
    "move_names.csv": f"{POKEAPI_CSV_BASE}/move_names.csv",
    "move_damage_classes.csv": f"{POKEAPI_CSV_BASE}/move_damage_classes.csv",
    "move_targets.csv": f"{POKEAPI_CSV_BASE}/move_targets.csv",
    "move_meta.csv": f"{POKEAPI_CSV_BASE}/move_meta.csv",
    "move_meta_ailments.csv": f"{POKEAPI_CSV_BASE}/move_meta_ailments.csv",
    "move_meta_stat_changes.csv": f"{POKEAPI_CSV_BASE}/move_meta_stat_changes.csv",
    "pokemon_moves.csv": f"{POKEAPI_CSV_BASE}/pokemon_moves.csv",
    "abilities_master.csv": f"{POKEAPI_CSV_BASE}/abilities.csv",
    "pokemon_abilities_map.csv": f"{POKEAPI_CSV_BASE}/pokemon_abilities.csv",
    "ability_prose.csv": f"{POKEAPI_CSV_BASE}/ability_prose.csv",
    "stat_names.csv": f"{POKEAPI_CSV_BASE}/stats.csv",
    "type_names.csv": f"{POKEAPI_CSV_BASE}/types.csv",
    "ability_names.csv": f"{POKEAPI_CSV_BASE}/ability_names.csv",
}


def _safe_int(val: Any, default: Optional[int] = None) -> Optional[int]:
    if val is None or val == "":
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def download_missing_csvs() -> Dict[str, str]:
    """Downloads only missing or empty CSVs into cache/ (idempotent)."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    statuses: Dict[str, str] = {}
    for local_name, url in CSV_SOURCES.items():
        dest = os.path.join(CACHE_DIR, local_name)
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            statuses[local_name] = "cached"
            continue
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 PokemonAuctionCombatImporter/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp, open(dest, "wb") as f:
            f.write(resp.read())
        statuses[local_name] = "downloaded"
    return statuses


def _load_csv(filename: str) -> List[Dict[str, str]]:
    path = os.path.join(CACHE_DIR, filename)
    with open(path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


UNDESIRABLE_DEFAULT_MOVES = {
    "explosion", "self-destruct", "misty-explosion", "final-gambit", "memento",
    "healing-wish", "lunar-dance", "hyper-beam", "giga-impact", "frenzy-plant",
    "blast-burn", "hydro-cannon", "roar-of-time", "rock-wrecker", "eternabeam",
    "solar-beam", "solar-blade", "skull-bash", "sky-attack", "focus-punch",
    "freeze-shock", "ice-burn", "geomancy", "meteor-beam", "electro-shot",
    "last-resort", "dream-eater", "snore", "sleep-talk", "belch",
    "synchronoise", "burn-up", "double-shock", "bide", "counter", "mirror-coat",
    "metal-burst", "future-sight", "doom-desire", "steel-roller", "endeavor",
}


def _select_default_moveset(
    learnable_ids: List[int],
    moves_by_id: Dict[int, dict],
    pokemon_types: List[str],
    pokemon_stats: Optional[dict] = None,
) -> List[int]:
    """
    Intelligently selects up to 4 legitimate moves strictly from `learnable_ids`:
    - Aligns Physical/Special preference with the Pokémon's Attack vs Special Attack.
    - Penalizes self-KO, recharge, 2-turn charge, and conditional moves.
    - Weights STAB, accuracy, PP (>= 5), recoil, and type coverage.
    - Includes at most 1 useful status/healing move if appropriate.
    """
    if not learnable_ids:
        return []

    valid_moves = [moves_by_id[mid] for mid in learnable_ids if mid in moves_by_id and moves_by_id[mid].get("is_main_series", True)]
    if not valid_moves:
        return []

    pstats = pokemon_stats or {}
    atk_stat = pstats.get("attack", 70)
    spa_stat = pstats.get("special_attack", 70)
    type_set = {t.capitalize() for t in pokemon_types}

    def _move_score(m: dict) -> Tuple[float, int]:
        ident = m.get("identifier", "")
        power = m.get("power") or 0
        acc = (m.get("accuracy") or 100) / 100.0
        pp = m.get("pp") or 10
        cat = m.get("category", "Status")
        meta = m.get("meta") or {}

        if cat == "Status" or power <= 0:
            return (0.0, -m["id"])

        stab = 1.5 if m["type"] in type_set else 1.0
        # Physical/Special alignment bonus
        if cat == "Physical":
            stat_fit = 1.15 if atk_stat >= spa_stat else 0.80
        else:
            stat_fit = 1.15 if spa_stat >= atk_stat else 0.80

        score = power * stab * acc * stat_fit

        # Penalize recoil, low PP, and undesirable/conditional/self-KO/recharge moves
        if (meta.get("drain") or 0) < 0:
            score *= 0.82
        if pp < 5:
            score *= 0.65
        if ident in UNDESIRABLE_DEFAULT_MOVES:
            score *= 0.25

        return (round(score, 2), -m["id"])

    selected: List[int] = []
    used: Set[int] = set()

    # 1. Pick strongest STAB damaging move for each of the Pokémon's types
    for ptype in pokemon_types:
        stab_moves = [
            m for m in valid_moves
            if m["type"] == ptype.capitalize()
            and m["category"] in ("Physical", "Special")
            and (m.get("power") or 0) > 0
            and m["id"] not in used
        ]
        if stab_moves:
            best = max(stab_moves, key=_move_score)
            selected.append(best["id"])
            used.add(best["id"])
            if len(selected) >= 4:
                return selected

    # 2. Pick strongest coverage damaging moves (distinct types)
    selected_types = {moves_by_id[mid]["type"] for mid in selected}
    coverage_moves = [
        m for m in valid_moves
        if m["category"] in ("Physical", "Special")
        and (m.get("power") or 0) > 0
        and m["type"] not in selected_types
        and m["id"] not in used
    ]
    coverage_moves.sort(key=_move_score, reverse=True)
    for m in coverage_moves:
        if len(selected) >= 3:
            break
        if m["type"] not in selected_types:
            selected.append(m["id"])
            used.add(m["id"])
            selected_types.add(m["type"])

    # 3. Useful Status / Healing / Stat-boost move if slot remains
    if len(selected) < 4:
        status_moves = [
            m for m in valid_moves
            if m["category"] == "Status"
            and m["id"] not in used
            and m.get("identifier") not in UNDESIRABLE_DEFAULT_MOVES
            and (
                (m["meta"].get("ailment") not in (None, "none") and (m.get("accuracy") or 100) >= 75)
                or (m["meta"].get("healing") or 0) > 0
                or len(m["meta"].get("stat_changes") or []) > 0
            )
        ]
        if status_moves:
            best_status = max(status_moves, key=lambda m: (m.get("accuracy") or 100, (m["meta"].get("healing") or 0), -m["id"]))
            selected.append(best_status["id"])
            used.add(best_status["id"])

    # 4. Fill remaining slots up to 4 with highest-scoring moves
    if len(selected) < 4:
        remaining = [m for m in valid_moves if m["id"] not in used]
        remaining.sort(key=_move_score, reverse=True)
        for m in remaining:
            selected.append(m["id"])
            used.add(m["id"])
            if len(selected) >= 4:
                break

    return selected[:4]


def build_pokemon_combat_data() -> Dict[str, Any]:
    """Runs the full idempotent Pokémon combat data import and writes output JSONs."""
    csv_statuses = download_missing_csvs()
    errors: List[str] = []

    # Load lookup tables
    type_names = {
        _safe_int(r["id"]): r["identifier"].capitalize()
        for r in _load_csv("type_names.csv")
        if _safe_int(r["id"]) is not None
    }
    damage_classes = {
        _safe_int(r["id"]): r["identifier"].capitalize()
        for r in _load_csv("move_damage_classes.csv")
        if _safe_int(r["id"]) is not None
    }
    targets = {
        _safe_int(r["id"]): r["identifier"]
        for r in _load_csv("move_targets.csv")
        if _safe_int(r["id"]) is not None
    }
    ailments = {
        _safe_int(r["id"]): r["identifier"]
        for r in _load_csv("move_meta_ailments.csv")
        if _safe_int(r["id"]) is not None
    }
    stat_names = {
        _safe_int(r["id"]): r["identifier"].replace("-", "_")
        for r in _load_csv("stat_names.csv")
        if _safe_int(r["id"]) is not None
    }

    # English move names (language_id == 9)
    move_names: Dict[int, str] = {}
    for r in _load_csv("move_names.csv"):
        if r.get("local_language_id") == "9":
            mid = _safe_int(r.get("move_id"))
            if mid is not None:
                move_names[mid] = r["name"]

    # Move meta & stat changes
    move_stat_changes: Dict[int, List[Dict[str, Any]]] = {}
    for r in _load_csv("move_meta_stat_changes.csv"):
        mid = _safe_int(r.get("move_id"))
        sid = _safe_int(r.get("stat_id"))
        chg = _safe_int(r.get("change"))
        if mid is not None and sid is not None and chg is not None:
            move_stat_changes.setdefault(mid, []).append({
                "stat": stat_names.get(sid, f"stat_{sid}"),
                "change": chg,
            })

    move_meta_map: Dict[int, dict] = {}
    for r in _load_csv("move_meta.csv"):
        mid = _safe_int(r.get("move_id"))
        if mid is None:
            continue
        ailment_id = _safe_int(r.get("meta_ailment_id"), 0)
        ailment_name = ailments.get(ailment_id, "none")
        move_meta_map[mid] = {
            "ailment": None if ailment_name in ("none", "unknown") else ailment_name,
            "ailment_chance": _safe_int(r.get("ailment_chance"), 0),
            "crit_rate": _safe_int(r.get("crit_rate"), 0),
            "drain": _safe_int(r.get("drain"), 0),
            "healing": _safe_int(r.get("healing"), 0),
            "flinch_chance": _safe_int(r.get("flinch_chance"), 0),
            "stat_chance": _safe_int(r.get("stat_chance"), 0),
            "min_hits": _safe_int(r.get("min_hits")),
            "max_hits": _safe_int(r.get("max_hits")),
            "min_turns": _safe_int(r.get("min_turns")),
            "max_turns": _safe_int(r.get("max_turns")),
            "stat_changes": move_stat_changes.get(mid, []),
        }

    # 1. Build Moves Database
    moves_by_id: Dict[int, dict] = {}
    for r in _load_csv("moves.csv"):
        mid = _safe_int(r.get("id"))
        if mid is None:
            errors.append(f"Skipped malformed move row: {r}")
            continue
        # Exclude shadow/unknown non-standard moves if type_id >= 10000
        type_id = _safe_int(r.get("type_id"))
        mtype = type_names.get(type_id, "Unknown")
        dmg_class_id = _safe_int(r.get("damage_class_id"))
        category = damage_classes.get(dmg_class_id, "Status")
        meta = move_meta_map.get(mid, {
            "ailment": None,
            "ailment_chance": 0,
            "crit_rate": 0,
            "drain": 0,
            "healing": 0,
            "flinch_chance": 0,
            "stat_chance": 0,
            "min_hits": None,
            "max_hits": None,
            "min_turns": None,
            "max_turns": None,
            "stat_changes": move_stat_changes.get(mid, []),
        })
        moves_by_id[mid] = {
            "id": mid,
            "identifier": r.get("identifier", f"move-{mid}"),
            "name": move_names.get(mid, r.get("identifier", f"Move {mid}").replace("-", " ").title()),
            "generation_id": _safe_int(r.get("generation_id")),
            "type": mtype,
            "category": category,
            "power": _safe_int(r.get("power")),
            "accuracy": _safe_int(r.get("accuracy")),
            "pp": _safe_int(r.get("pp")),
            "priority": _safe_int(r.get("priority"), 0),
            "target": targets.get(_safe_int(r.get("target_id")), "selected-pokemon"),
            "effect_chance": _safe_int(r.get("effect_chance")),
            "is_main_series": (mtype != "Shadow" and mid < 10000),
            "meta": meta,
            "source": "PokéAPI v2 CSV",
        }

    moves_payload = {
        "metadata": {
            "version": "1.0.0",
            "source": "PokéAPI v2 CSV (moves.csv, move_meta.csv, move_meta_stat_changes.csv)",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_moves": len(moves_by_id),
        },
        "moves": {str(mid): m for mid, m in sorted(moves_by_id.items())},
    }
    with open(MOVES_OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(moves_payload, f, indent=2, ensure_ascii=False)

    # 2. Build Pokémon Abilities Database
    ability_names: Dict[int, str] = {}
    for r in _load_csv("ability_names.csv"):
        if r.get("local_language_id") == "9":
            aid = _safe_int(r.get("ability_id"))
            if aid is not None:
                ability_names[aid] = r["name"]

    ability_prose: Dict[int, Dict[str, str]] = {}
    for r in _load_csv("ability_prose.csv"):
        if r.get("local_language_id") == "9":
            aid = _safe_int(r.get("ability_id"))
            if aid is not None:
                ability_prose[aid] = {
                    "short_effect": " ".join((r.get("short_effect") or "").split()),
                    "effect": " ".join((r.get("effect") or "").split()),
                }

    abilities_by_id: Dict[str, dict] = {}
    for r in _load_csv("abilities_master.csv"):
        aid = _safe_int(r.get("id"))
        if aid is None:
            continue
        prose = ability_prose.get(aid, {})
        name = ability_names.get(aid, r.get("identifier", f"ability-{aid}").replace("-", " ").title())
        abilities_by_id[str(aid)] = {
            "id": aid,
            "identifier": r.get("identifier", ""),
            "name": name,
            "generation_id": _safe_int(r.get("generation_id")),
            "is_main_series": r.get("is_main_series") == "1",
            "short_effect": prose.get("short_effect") or None,
            "effect": prose.get("effect") or None,
            "source": "PokéAPI v2 CSV",
        }

    abilities_payload = {
        "metadata": {
            "version": "1.0.0",
            "source": "PokéAPI v2 CSV (abilities.csv, ability_names.csv, ability_prose.csv)",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_abilities": len(abilities_by_id),
        },
        "abilities": abilities_by_id,
    }
    with open(ABILITIES_OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(abilities_payload, f, indent=2, ensure_ascii=False)

    # 3. Build Pokémon Abilities Map (per-Pokémon slot & is_hidden from pokemon_abilities.csv)
    pkmn_ability_map: Dict[int, List[dict]] = {}
    for r in _load_csv("pokemon_abilities_map.csv"):
        pid = _safe_int(r.get("pokemon_id"))
        aid = _safe_int(r.get("ability_id"))
        slot = _safe_int(r.get("slot"), 1)
        is_hidden = r.get("is_hidden") == "1"
        if pid is not None and aid is not None:
            ab_info = abilities_by_id.get(str(aid), {})
            pkmn_ability_map.setdefault(pid, []).append({
                "ability_id": aid,
                "name": ab_info.get("name", ability_names.get(aid, f"Ability {aid}")),
                "slot": slot,
                "is_hidden": is_hidden,
            })
    for pid in pkmn_ability_map:
        pkmn_ability_map[pid].sort(key=lambda a: (a["is_hidden"], a["slot"]))

    # 4. Build Pokémon Learnsets (direct per-pokemon_id from pokemon_moves.csv)
    direct_learnsets: Dict[int, Set[int]] = {}
    for r in _load_csv("pokemon_moves.csv"):
        pid = _safe_int(r.get("pokemon_id"))
        mid = _safe_int(r.get("move_id"))
        if pid is not None and mid is not None and mid in moves_by_id and moves_by_id[mid].get("is_main_series", True):
            direct_learnsets.setdefault(pid, set()).add(mid)

    with open(POKEMON_JSON_PATH, "r", encoding="utf-8") as f:
        pokemon_list = json.load(f)

    # Index base species pokemon_id by national_id for form fallback ONLY when a form has 0 direct entries
    base_pid_by_national: Dict[int, int] = {}
    for p in pokemon_list:
        if p.get("is_default", True):
            base_pid_by_national[p["national_id"]] = p["id"]

    learnsets_out: Dict[str, dict] = {}
    direct_count = 0
    inherited_count = 0
    empty_count = 0

    for p in pokemon_list:
        pid = p["id"]
        nid = p["national_id"]
        move_set = direct_learnsets.get(pid, set())
        learnset_source = "direct_pokemon_moves"

        if not move_set and not p.get("is_default", True):
            base_pid = base_pid_by_national.get(nid)
            if base_pid and base_pid in direct_learnsets:
                move_set = direct_learnsets[base_pid]
                learnset_source = "inherited_from_base_species"
                inherited_count += 1
            else:
                learnset_source = "none_available"
                empty_count += 1
        elif move_set:
            direct_count += 1
        else:
            learnset_source = "none_available"
            empty_count += 1

        sorted_moves = sorted(move_set)
        default_moveset = _select_default_moveset(sorted_moves, moves_by_id, p.get("types", []), p.get("stats"))

        learnsets_out[str(pid)] = {
            "pokemon_id": pid,
            "national_id": nid,
            "name": p["name"],
            "is_default": p.get("is_default", True),
            "abilities": pkmn_ability_map.get(pid, []),
            "learnset_source": learnset_source,
            "learnable_move_count": len(sorted_moves),
            "learnable_move_ids": sorted_moves,
            "default_moveset": default_moveset,
        }

    learnsets_payload = {
        "metadata": {
            "version": "1.0.0",
            "source": "PokéAPI v2 CSV (pokemon_moves.csv) + data/pokemon_database.json",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_pokemon": len(learnsets_out),
            "direct_learnsets": direct_count,
            "inherited_form_learnsets": inherited_count,
            "empty_learnsets": empty_count,
        },
        "learnsets": learnsets_out,
    }
    with open(LEARNSETS_OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(learnsets_payload, f, indent=2, ensure_ascii=False)

    return {
        "csv_statuses": csv_statuses,
        "pokemon_processed": len(learnsets_out),
        "total_moves": len(moves_by_id),
        "total_abilities": len(abilities_by_id),
        "direct_learnsets": direct_count,
        "inherited_form_learnsets": inherited_count,
        "empty_learnsets": empty_count,
        "errors": errors,
    }


if __name__ == "__main__":
    summary = build_pokemon_combat_data()
    print(json.dumps(summary, indent=2))
