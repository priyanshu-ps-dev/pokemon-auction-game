"""Shared interactions for anime and MCU techniques in automatic and manual battles."""


def spend_stamina(attacker, technique):
    costs = {"defensive": 6, "healing": 18, "support": 10, "magic": 12, "mental": 12}
    cost = technique.get("stamina_cost", costs.get(technique.get("category"), 8))
    if attacker.stamina < cost:
        attacker.stamina = min(attacker.max_stamina, attacker.stamina + 16)
        return False
    attacker.stamina -= cost
    return True


def resolve_technique_damage(attacker, defender, technique, power, offense, defense, rng):
    category = technique.get("category", "physical")
    tags = {category.casefold()}
    element = technique.get("element_or_energy_type")
    if element:
        tags.add(element.casefold())
    name = technique["name"]
    immunities = {tag.casefold() for tag in getattr(defender, "immunities", ())}
    if tags & immunities:
        return 0, f"{defender.name} is immune to {name}."

    if technique.get("range") == "contact" and attacker.effective_speed < defender.effective_speed * 0.65:
        return 0, f"{defender.name} evaded {attacker.name}'s {name} before contact."

    weaknesses = {tag.casefold() for tag in getattr(defender, "weaknesses", ())}
    resistances = {tag.casefold() for tag in getattr(defender, "resistances", ())}
    multiplier = 1.4 if tags & weaknesses else 1.0
    if tags & resistances:
        multiplier *= 0.65
    if getattr(defender, "has_ability_type", lambda _: False)("defensive"):
        multiplier *= 0.90

    # A gap in stopping power matters more than the raw 1–100 stat difference.
    # Weapon output includes the weapon itself rather than just its wielder's strength.
    if category in ("weapon", "ranged"):
        offense = max(offense, 43)
    ratio = max(0.08, offense / max(8, defense))
    damage = int(power * 0.5 * ratio ** 1.6 * multiplier * rng.uniform(0.95, 1.05))
    actual = defender.take_damage(max(0, damage))
    context = " It exploited a weakness." if tags & weaknesses else ""
    if tags & resistances:
        context += " The defender resisted the technique."
    return actual, f"{attacker.name} used {name} for {actual} damage.{context}"


def end_nonpokemon_turn(fighter, events):
    if not fighter or fighter.is_fainted or not hasattr(fighter, "shield_turns"):
        return
    fighter.shield_turns = max(0, fighter.shield_turns - 1)
    tick = getattr(fighter, "tick_transformation", None)
    expiry = tick() if tick else None
    if expiry:
        events.append(expiry)
    if fighter.has_ability_type("healing_support"):
        healed = fighter.heal(max(1, fighter.max_hp // 20))
        if healed:
            events.append(f"{fighter.name} regenerated {healed} HP.")
