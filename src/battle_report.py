"""Summarize the authoritative turn log for results and combat awards."""

from collections import defaultdict


def describe_tournament(results, players):
    fighters = {
        str(character["id"]): character
        for player in players
        for character in player.team
    }
    contributions = defaultdict(lambda: {"damage": 0, "knockouts": 0})
    for match in results.get("matches", []):
        decisive_action = None
        for turn in match.get("turn_log", []):
            actions = turn.get("action_details", [])
            for index, action in enumerate(actions):
                fighter_id = action.get("attacker_id")
                damage = action.get("damage", 0)
                if not fighter_id or not damage:
                    continue
                contribution = contributions[fighter_id]
                contribution["damage"] += damage
                next_action = actions[index + 1] if index + 1 < len(actions) else {}
                if next_action.get("event_type") == "faint" and next_action.get("side") == action.get("target_side"):
                    contribution["knockouts"] += 1
                    attacker = fighters.get(fighter_id, {}).get("name", "Fighter")
                    defender = fighters.get(action.get("defender_id"), {}).get("name", "opponent")
                    decisive_action = f"{attacker} knocked out {defender} with {action['move_name']}."
        if match.get("reason") == "TEAM_ELIMINATION" and decisive_action:
            match["explanation"] = decisive_action
        elif match.get("is_draw"):
            match["explanation"] = "Neither side secured a decisive finish."
        elif match.get("turns_played") == 0:
            match["explanation"] = "One side had no eligible fighters."

    ranked = sorted(contributions, key=lambda cid: (
        -contributions[cid]["knockouts"], -contributions[cid]["damage"], cid
    ))
    if ranked:
        winner_id = ranked[0]
        winner = fighters.get(winner_id)
        if winner:
            results["combat_mvp"] = {
                "id": winner_id, "name": winner["name"], "image": winner.get("image"),
                "franchise": winner.get("anime_name"), **contributions[winner_id],
            }
    purchased = [
        cid for cid in ranked if fighters.get(cid, {}).get("auction_cost", 0) > 0
    ]
    if purchased:
        best = max(purchased, key=lambda cid: contributions[cid]["damage"] / fighters[cid]["auction_cost"])
        results["best_value"] = {
            "name": fighters[best]["name"], "cost": fighters[best]["auction_cost"],
            "damage": contributions[best]["damage"],
        }
