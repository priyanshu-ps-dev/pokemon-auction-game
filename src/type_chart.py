# Type effectiveness chart for calculating defensive rating and type advantages

TYPES = [
    "Normal", "Fire", "Water", "Grass", "Electric", "Ice",
    "Fighting", "Poison", "Ground", "Flying", "Psychic", "Bug",
    "Rock", "Ghost", "Dragon", "Steel", "Dark", "Fairy"
]

# Attacking Type -> { Defending Type -> Multiplier }
TYPE_CHART = {
    "Normal": {"Rock": 0.5, "Ghost": 0.0, "Steel": 0.5},
    "Fire": {"Fire": 0.5, "Water": 0.5, "Grass": 2.0, "Ice": 2.0, "Bug": 2.0, "Rock": 0.5, "Dragon": 0.5, "Steel": 2.0},
    "Water": {"Fire": 2.0, "Water": 0.5, "Grass": 0.5, "Ground": 2.0, "Rock": 2.0, "Dragon": 0.5},
    "Grass": {"Fire": 0.5, "Water": 2.0, "Grass": 0.5, "Poison": 0.5, "Ground": 2.0, "Flying": 0.5, "Bug": 0.5, "Rock": 2.0, "Dragon": 0.5, "Steel": 0.5},
    "Electric": {"Water": 2.0, "Grass": 0.5, "Electric": 0.5, "Ground": 0.0, "Flying": 2.0, "Dragon": 0.5},
    "Ice": {"Fire": 0.5, "Water": 0.5, "Grass": 2.0, "Ice": 0.5, "Ground": 2.0, "Flying": 2.0, "Dragon": 2.0, "Steel": 0.5},
    "Fighting": {"Normal": 2.0, "Ice": 2.0, "Poison": 0.5, "Flying": 0.5, "Psychic": 0.5, "Bug": 0.5, "Rock": 2.0, "Ghost": 0.0, "Dark": 2.0, "Steel": 2.0, "Fairy": 0.5},
    "Poison": {"Grass": 2.0, "Poison": 0.5, "Ground": 0.5, "Rock": 0.5, "Ghost": 0.5, "Steel": 0.0, "Fairy": 2.0},
    "Ground": {"Fire": 2.0, "Grass": 0.5, "Electric": 2.0, "Poison": 2.0, "Flying": 0.0, "Bug": 0.5, "Rock": 2.0, "Steel": 2.0},
    "Flying": {"Grass": 2.0, "Electric": 0.5, "Fighting": 2.0, "Bug": 2.0, "Rock": 0.5, "Steel": 0.5},
    "Psychic": {"Fighting": 2.0, "Poison": 2.0, "Psychic": 0.5, "Dark": 0.0, "Steel": 0.5},
    "Bug": {"Fire": 0.5, "Grass": 2.0, "Fighting": 0.5, "Poison": 0.5, "Flying": 0.5, "Psychic": 2.0, "Ghost": 0.5, "Dark": 2.0, "Steel": 0.5, "Fairy": 0.5},
    "Rock": {"Fire": 2.0, "Ice": 2.0, "Fighting": 0.5, "Ground": 0.5, "Flying": 2.0, "Bug": 2.0, "Steel": 0.5},
    "Ghost": {"Normal": 0.0, "Psychic": 2.0, "Ghost": 2.0, "Dark": 0.5},
    "Dragon": {"Dragon": 2.0, "Steel": 0.5, "Fairy": 0.0},
    "Steel": {"Fire": 0.5, "Water": 0.5, "Electric": 0.5, "Ice": 2.0, "Rock": 2.0, "Steel": 0.5, "Fairy": 2.0},
    "Dark": {"Fighting": 0.5, "Psychic": 2.0, "Ghost": 2.0, "Dark": 0.5, "Fairy": 0.5},
    "Fairy": {"Fire": 0.5, "Fighting": 2.0, "Poison": 0.5, "Dragon": 2.0, "Dark": 2.0, "Steel": 0.5}
}

def calculate_defensive_effectiveness(defending_types):
    """
    Calculates defensive multiplier for each of the 18 attacking types against given defending types.
    Returns:
        dict: {
            "multipliers": { attacking_type: float },
            "immunities": list,
            "resistances": list,
            "weaknesses": list,
            "net_defensive_score": float (-5.0 to +6.0)
        }
    """
    clean_types = [t.capitalize() for t in defending_types if t.capitalize() in TYPES]
    if not clean_types:
        return {"multipliers": {}, "immunities": [], "resistances": [], "weaknesses": [], "net_defensive_score": 0.0}

    multipliers = {}
    immunities = []
    resistances = []
    weaknesses = []

    for atk in TYPES:
        mult = 1.0
        for df in clean_types:
            mult *= TYPE_CHART.get(atk, {}).get(df, 1.0)
        multipliers[atk] = mult
        if mult == 0.0:
            immunities.append(atk)
        elif mult < 1.0:
            resistances.append(atk)
        elif mult > 1.0:
            weaknesses.append(atk)

    # Calculate net score:
    # Each immunity is worth +2.0
    # Each 0.5x resistance is worth +1.0 (0.25x resistance worth +1.5)
    # Each 2.0x weakness is worth -1.0
    # Each 4.0x weakness is worth -2.5 (severe vulnerability)
    score = 0.0
    for atk, mult in multipliers.items():
        if mult == 0.0:
            score += 2.0
        elif mult <= 0.25:
            score += 1.5
        elif mult <= 0.5:
            score += 1.0
        elif mult >= 4.0:
            score -= 2.5
        elif mult >= 2.0:
            score -= 1.0

    # Scale score to a normalized type modifier between -4.0 and +5.0
    type_modifier = round(max(-4.0, min(5.0, score * 0.75)), 1)

    return {
        "multipliers": multipliers,
        "immunities": immunities,
        "resistances": resistances,
        "weaknesses": weaknesses,
        "net_defensive_score": type_modifier
    }
