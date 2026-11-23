"""
Pokemon Bidding Game: Power Ranking & Auction Valuation System
==============================================================

Provides mathematically balanced ranking formulas for:
1. Base Stat Total (BST)
2. Power Rating (Normalized 1 to 100)
3. Auction Tier (S+, S, A, B, C, D)
4. Rarity Tier
5. Auction Value Score (Estimated bidding price in coins)
"""

def calculate_power_rating(stats, type_modifier=0.0, evolution_stage=1, is_legendary=False, is_mythical=False):
    """
    Calculates a balanced competitive power rating (1 to 100).
    
    Formula components:
    - Base Stat Total (BST): Fundamental baseline power (45% weight)
    - Offensive Specialization: max(Atk, SpAtk) + secondary offense (25% weight)
      In competitive Pokemon, focused attackers (e.g. 135 Atk / 40 SpA) outperform
      flat mediocre stats (80 Atk / 80 SpA) because damage output scales with primary attacking stat.
    - Speed Priority: Speed dictates who acts first (15% weight)
    - Effective Bulk: Harmonic product of HP and both defenses (15% weight)
    - Type Advantage Modifier: Net defensive resistances vs weaknesses (-4.0 to +5.0 pts)
    - Evolution Stage Synergy: Fully evolved Pokemon get small consistency bonus (+1.0 to +2.0 pts)
    
    Crucially: Legendary status is NOT an automatic free pass. Weak legendaries/mythicals
    (Phione, Cosmog, Regigigas with Slow Start) receive fair, realistic ratings matching their stats.
    """
    hp = stats["hp"]
    atk = stats["attack"]
    defense = stats["defense"]
    spa = stats["special_attack"]
    spd = stats["special_defense"]
    spe = stats["speed"]
    bst = stats["total"]

    # 1. Base Stat Total baseline (0 - 45 points)
    # BST ranges from 180 (Sunkern) to 780 (Mega Rayquaza)
    bst_clamped = max(175, min(780, bst))
    bst_score = ((bst_clamped - 175) / (780 - 175)) * 45.0

    # 2. Offensive Specialization (0 - 25 points)
    # Highest offensive stat plus 20% of the other
    primary_offense = max(atk, spa)
    secondary_offense = min(atk, spa)
    effective_offense = primary_offense * 1.0 + secondary_offense * 0.2
    # effective_offense ranges from ~15 to ~220
    offense_clamped = max(15.0, min(220.0, effective_offense))
    offense_score = ((offense_clamped - 15.0) / (220.0 - 15.0)) * 25.0

    # 3. Speed Priority (0 - 15 points)
    # Speed ranges from 5 (Shuckle/Munchlax) to 200 (Regieleki)
    speed_clamped = max(5, min(200, spe))
    speed_score = ((speed_clamped - 5) / (200 - 5)) * 15.0

    # 4. Effective Bulk (0 - 15 points)
    # Physical bulk = HP * Def / 100; Special bulk = HP * SpDef / 100
    eff_bulk = ((hp * defense / 100.0) + (hp * spd / 100.0)) / 2.0
    bulk_clamped = max(5.0, min(250.0, eff_bulk))
    bulk_score = ((bulk_clamped - 5.0) / (250.0 - 5.0)) * 15.0

    # Aggregate base rating
    raw_rating = bst_score + offense_score + speed_score + bulk_score

    # Add type advantage modifier
    raw_rating += type_modifier

    # Evolution stage synergy
    if evolution_stage >= 3:
        raw_rating += 2.0
    elif evolution_stage == 2:
        raw_rating += 1.0

    # Calibrate scaling factor (1.15) to account for stat specialization
    # (since no Pokemon simultaneously possesses max possible in all 4 categories)
    scaled_rating = raw_rating * 1.15

    # Normalize to 1.0 - 100.0
    final_rating = round(max(1.0, min(100.0, scaled_rating)), 1)
    return final_rating


def determine_tier(power_rating):
    """
    Maps power rating to defined competitive tiers:
    S+ Tier : >= 90.0 (Elite legendary/mega tier)
    S Tier  : 80.0 - 89.9 (Very powerful / pseudo-legendary)
    A Tier  : 70.0 - 79.9 (Strong fully-evolved powerhouses)
    B Tier  : 55.0 - 69.9 (Above average battlers)
    C Tier  : 40.0 - 54.9 (Average / mid evolutions)
    D Tier  : < 40.0 (Weak / baby / basic unevolved)
    """
    if power_rating >= 90.0:
        return "S+"
    elif power_rating >= 80.0:
        return "S"
    elif power_rating >= 70.0:
        return "A"
    elif power_rating >= 55.0:
        return "B"
    elif power_rating >= 40.0:
        return "C"
    else:
        return "D"


def determine_rarity_tier(is_mythical, is_legendary, is_starter, bst, stage, identifier):
    """
    Determines Pokémon Rarity Tier:
    - Mythical
    - Legendary
    - Sub-Legendary (Birds, Beasts, Titans, Ultra Beasts, Paradox)
    - Pseudo-Legendary (600 BST 3-stage powerhouses)
    - Starter Final / Starter Basic
    - Rare
    - Uncommon
    - Common
    """
    ident_lower = identifier.lower()
    
    if is_mythical:
        return "Mythical"
    
    # Sub-legendaries / Ultra Beasts / Paradox / Minor legends:
    sub_legendary_keywords = [
        "articuno", "zapdos", "moltres", "raikou", "entei", "suicune",
        "regirock", "regice", "registeel", "latias", "latios", "uxie", "mesprit", "azelf",
        "heatran", "regigigas", "cresselia", "cobalion", "terrakion", "virizion", "tornadus", "thundurus", "landorus",
        "type-null", "silvally", "tapu-", "nihilego", "buzzwole", "pheromosa", "xurkitree", "celesteela", "kartana", "guzzlord", "poipole", "naganadel", "stakataka", "blacephalon",
        "kubfu", "urshifu", "regieleki", "regidrago", "glastrier", "spectrier", "enamorus",
        "ting-lu", "chien-pao", "wo-chien", "chi-yu", "roaring-moon", "iron-valiant", "flutter-mane", "iron-bundle",
        "iron-hands", "iron-jugulis", "iron-moth", "iron-thorns", "scream-tail", "brute-bonnet", "slither-wing", "sandy-shocks", "great-tusk", "iron-leaves", "walking-wake", "gouging-fire", "raging-bolt", "iron-boulder", "iron-crown", "ogerpon", "okidogi", "munkidori", "fezandipiti"
    ]
    
    if is_legendary:
        for kw in sub_legendary_keywords:
            if kw in ident_lower:
                return "Sub-Legendary"
        return "Legendary"
    
    # Check Paradox / Ultra Beast even if is_legendary not marked in species table
    for kw in ["roaring-moon", "iron-valiant", "flutter-mane", "iron-bundle", "iron-hands", "walking-wake", "gouging-fire", "raging-bolt", "iron-leaves", "iron-boulder", "iron-crown"]:
        if kw in ident_lower:
            return "Sub-Legendary"

    # Pseudo-Legendary: 600 BST and 3 stages
    if bst >= 600 and stage >= 3:
        return "Pseudo-Legendary"

    # Starters
    if is_starter:
        if stage >= 3 or "mega" in ident_lower or "gmax" in ident_lower:
            return "Starter Final"
        return "Starter"

    # Standard progression
    if stage >= 3 or bst >= 510 or "mega" in ident_lower:
        return "Rare"
    elif stage == 2 or bst >= 410:
        return "Uncommon"
    else:
        return "Common"


def calculate_auction_value(power_rating, rarity_tier, bst, tier):
    """
    Calculates estimated bidding auction value in coins.
    Designed for engaging bidding mechanics:
    - Base bid scales progressively with power rating
    - Rarity tier multipliers add collection prestige
    - Tier milestone bonuses create high-stakes bidding for S and S+ assets
    """
    rarity_multipliers = {
        "Mythical": 1.50,
        "Legendary": 1.45,
        "Sub-Legendary": 1.30,
        "Pseudo-Legendary": 1.25,
        "Starter Final": 1.20,
        "Starter": 1.10,
        "Rare": 1.05,
        "Uncommon": 1.00,
        "Common": 0.90
    }
    
    mult = rarity_multipliers.get(rarity_tier, 1.0)
    
    # Base curve: (PR ^ 1.8) * 2.2
    base_price = (power_rating ** 1.8) * 2.2
    
    # Tier milestone bonus
    tier_bonus = 0
    if tier == "S+":
        tier_bonus = 600
    elif tier == "S":
        tier_bonus = 350
    elif tier == "A":
        tier_bonus = 150
        
    estimated_value = (base_price * mult) + tier_bonus + (bst * 0.4)
    # Round to nearest 10 for clean auction game prices
    final_score = int(round(estimated_value / 10.0) * 10)
    return max(100, final_score)
