"""Transform raw scraper JSON output into BigQuery-compatible rows.

ALL game data is sourced exclusively from table_infos.
Only game_link / player_profile_link come from scraper-level keys (for URL / IDs).

Usage:
    import transform
    rows = transform.transform_file("98142396_20260719_191445.json")
"""

import json
import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse


def _int(v):
    if v is None:
        return None
    try:
        return int(str(v).strip())
    except (ValueError, TypeError):
        return None


def _float(v):
    if v is None:
        return None
    try:
        return float(str(v).strip())
    except (ValueError, TypeError):
        return None


def _stat_val(player_stats, stat_key, player_id):
    """Get a stat value for a player from result.stats.player."""
    stat = player_stats.get(stat_key, {})
    values = stat.get("values", {})
    if isinstance(values, dict):
        return values.get(str(player_id))
    return None


def _stat_label(player_stats, stat_key, player_id):
    """Get a stat valuelabel for a player from result.stats.player."""
    stat = player_stats.get(stat_key, {})
    labels = stat.get("valuelabels", {})
    if isinstance(labels, dict):
        return labels.get(str(player_id))
    return None


def _find_result_player(result, player_id):
    for p in result.get("player", []):
        if str(p.get("player_id")) == str(player_id):
            return p
    return None


def _find_opponent_result(result, player_id):
    for p in result.get("player", []):
        if str(p.get("player_id")) != str(player_id):
            return p
    return None


def _parse_map_flags(map_label):
    if not map_label:
        return {"is_beginner_map": None, "is_alt_map": None, "is_map_pack_1": None, "is_map_pack_2": None}
    s = str(map_label)
    is_beginner = "Map A" in s or "Map 0" in s
    is_alt = bool(re.search(r"Map \d+a:", s))
    m = re.search(r"Map (T?\d+)", s)
    map_num = m.group(1) if m else ""
    return {
        "is_beginner_map": is_beginner,
        "is_alt_map": is_alt,
        "is_map_pack_1": map_num in {"9", "10"},
        "is_map_pack_2": map_num in {"11", "12", "13", "14", "T1"},
    }


def transform_row(raw):
    """Transform a single raw scraper row into a BigQuery-compatible dict.

    All game data comes from raw['table_infos']['data'].
    """
    # --- IDs from scraper-level keys ---
    game_link = raw.get("game_link", "")
    table_id = None
    if game_link:
        qs = parse_qs(urlparse(game_link).query)
        table_id = _int(qs.get("table", [None])[0])

    player_link = raw.get("player_profile_link", "")
    player_id = None
    if player_link:
        qs = parse_qs(urlparse(player_link).query)
        player_id = _int(qs.get("id", [None])[0])

    # --- table_infos ---
    ti_data = raw.get("table_infos", {}).get("data", {})
    if not ti_data:
        return None

    result = ti_data.get("result", {})
    options = ti_data.get("options", {})
    player_stats = result.get("stats", {}).get("player", {})

    # If we couldn't get player_id from URL, try from table_infos by name
    if player_id is None:
        pid_str = raw.get("player_name")
        for p in result.get("player", []):
            if p.get("name") == pid_str:
                player_id = _int(p.get("player_id"))
                break

    rp = _find_result_player(result, player_id) or {}
    opp_rp = _find_opponent_result(result, player_id) or {}
    opponent_id = _int(opp_rp.get("player_id"))
    pid = str(player_id) if player_id else ""

    # --- ELO (full decimals) ---
    rank_after = _float(rp.get("rank_after_game"))
    point_win = _float(rp.get("point_win"))
    pre_match_elo = (rank_after - point_win) if rank_after is not None and point_win is not None else None
    post_match_elo = rank_after
    elo_delta = point_win

    opp_rank_after = _float(opp_rp.get("rank_after_game"))
    opp_point_win = _float(opp_rp.get("point_win"))
    opponent_elo = (opp_rank_after - opp_point_win) if opp_rank_after is not None and opp_point_win is not None else None

    # --- Arena rating (full string precision) ---
    arena_after = rp.get("arena_after_game")
    arena_win = rp.get("arena_points_win")
    pre_match_arena = None
    if arena_after is not None and arena_win is not None:
        try:
            pre_match_arena = str(float(arena_after) - float(arena_win))
        except (ValueError, TypeError):
            pass

    # --- Timestamp (precise from result.time_end) ---
    time_end_str = result.get("time_end")
    game_ended_at = None
    if time_end_str:
        try:
            dt = datetime.strptime(time_end_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            game_ended_at = dt.isoformat()
        except ValueError:
            pass

    # --- Concede ---
    concede = _int(result.get("concede")) or 0

    # --- Map ---
    map_label = _stat_label(player_stats, "map", pid)
    map_flags = _parse_map_flags(map_label)

    # --- Marine Worlds (option 111) ---
    opt_111 = options.get("111", {})
    is_mw_val = opt_111.get("value")
    is_mw = _int(is_mw_val) if is_mw_val is not None else None

    # --- Score / Game result ---
    score = _int(_stat_val(player_stats, "score", pid))
    game_rank = _int(rp.get("gamerank"))

    # --- Thinking time (seconds from reflexion_time) ---
    thinking_time_secs = _int(_stat_val(player_stats, "reflexion_time", pid))

    # --- Starting position ---
    starting_pos = _stat_label(player_stats, "position", pid)

    # --- Triggered end of game ---
    end_game_val = _int(_stat_val(player_stats, "endGameTriggered", pid))
    triggered_end = end_game_val == 1 if end_game_val is not None else None

    out = {
        "table_id": table_id or _int(ti_data.get("id")),
        "url": game_link or None,
        "player": rp.get("name"),
        "player_id": player_id,
        "opponent_id": opponent_id,
        "elo": pre_match_elo,
        "elo_delta": elo_delta,
        "pre_match_elo": pre_match_elo,
        "post_match_elo": post_match_elo,
        "opponent_elo": opponent_elo,
        "pre_match_arena_rating": pre_match_arena,
        "post_match_arena_rating": str(arena_after) if arena_after is not None else None,
        "arena_rating_delta": str(arena_win) if arena_win is not None else None,
        "game_ended_at": game_ended_at,
        "concede": concede,
        "Map": map_label,
        "is_beginner_map": map_flags["is_beginner_map"],
        "is_alt_map": map_flags["is_alt_map"],
        "is_map_pack_1": map_flags["is_map_pack_1"],
        "is_map_pack_2": map_flags["is_map_pack_2"],
        "is_mw": is_mw,
        "Game_result": game_rank,
        "Score": score,
        "Appeal": _int(_stat_val(player_stats, "appeal", pid)),
        "Conservation": _int(_stat_val(player_stats, "conservation", pid)),
        "Reputation": _int(_stat_val(player_stats, "reputation", pid)),
        "Starting_position_in_first_round": starting_pos,
        "Thinking_time": thinking_time_secs,
        "Number_of_turns": _int(_stat_val(player_stats, "turns", pid)),
        "Number_of_breaks_triggered": _int(_stat_val(player_stats, "breaksTriggered", pid)),
        "Triggered_end_of_game": triggered_end,
        "end_game_triggered": triggered_end,
        "Build_actions": _int(_stat_val(player_stats, "actionBuild", pid)),
        "Animals_actions": _int(_stat_val(player_stats, "actionAnimals", pid)),
        "Cards_actions": _int(_stat_val(player_stats, "actionCards", pid)),
        "Association_actions": _int(_stat_val(player_stats, "actionAssociation", pid)),
        "Sponsors_actions": _int(_stat_val(player_stats, "actionSponsors", pid)),
        "X_Tokens_gained": _int(_stat_val(player_stats, "xTokenGained", pid)),
        "X_Tokens_gained_instead_of_action": _int(_stat_val(player_stats, "xTokenGainedInsteadOfAction", pid)),
        "X_Tokens_used": _int(_stat_val(player_stats, "xTokenUsed", pid)),
        "Money_gained": _int(_stat_val(player_stats, "moneyGained", pid)),
        "Money_gained_through_income": _int(_stat_val(player_stats, "moneyGainedIncome", pid)),
        "Money_spent_on_animals": _int(_stat_val(player_stats, "moneyUsedAnimals", pid)),
        "Money_spent_on_enclosures": _int(_stat_val(player_stats, "moneyUsedBuild", pid)),
        "Money_spent_on_donations": _int(_stat_val(player_stats, "moneyUsedDonations", pid)),
        "Money_spent_for_playing_cards_from_reputation_range": _int(_stat_val(player_stats, "moneyUsedFromDisplay", pid)),
        "Cards_drawn_from_deck": _int(_stat_val(player_stats, "cardsDrawn", pid)),
        "Cards_taken_from_reputation_range": _int(_stat_val(player_stats, "cardsTaken", pid)),
        "Snapped_cards": _int(_stat_val(player_stats, "cardsSnapped", pid)),
        "Discarded_cards": _int(_stat_val(player_stats, "cardsDiscarded", pid)),
        "Played_sponsors": _int(_stat_val(player_stats, "sponsorsPlayed", pid)),
        "Played_animals": _int(_stat_val(player_stats, "animalsPlayed", pid)),
        "Released_animals": _int(_stat_val(player_stats, "animalsReleased", pid)),
        "Association_workers": _int(_stat_val(player_stats, "associationWorkers", pid)),
        "Donation_association_tasks": _int(_stat_val(player_stats, "associationDonation", pid)),
        "Reputation_association_tasks": _int(_stat_val(player_stats, "associationReputation", pid)),
        "Partner_zoo_association_tasks": _int(_stat_val(player_stats, "associationPartner", pid)),
        "University_association_tasks": _int(_stat_val(player_stats, "associationUniversity", pid)),
        "Conservation_project_association_tasks": _int(_stat_val(player_stats, "associationConservation", pid)),
        "Built_enclosures": _int(_stat_val(player_stats, "builtEnclosures", pid)),
        "Built_kiosks": _int(_stat_val(player_stats, "builtKiosks", pid)),
        "Built_pavilions": _int(_stat_val(player_stats, "builtPavilions", pid)),
        "Built_unique_buildings": _int(_stat_val(player_stats, "builtUniqueStructures", pid)),
        "Covered_hexes": _int(_stat_val(player_stats, "coveredHexes", pid)),
        "Empty_hexes": _int(_stat_val(player_stats, "emptyHexes", pid)),
        "Upgraded_action_cards": _int(_stat_val(player_stats, "upgradedCards", pid)),
        "Upgraded_Animals_action_card": _int(_stat_val(player_stats, "upgradedActionAnimals", pid)) == 1,
        "Upgraded_Build_action_card": _int(_stat_val(player_stats, "upgradedActionBuild", pid)) == 1,
        "Upgraded_Cards_action_card": _int(_stat_val(player_stats, "upgradedActionCards", pid)) == 1,
        "Upgraded_Sponsors_action_card": _int(_stat_val(player_stats, "upgradedActionSponsors", pid)) == 1,
        "Upgraded_Association_action_card": _int(_stat_val(player_stats, "upgradedActionAssociation", pid)) == 1,
        "Africa_icons": _int(_stat_val(player_stats, "iconAfrica", pid)),
        "Europe_icons": _int(_stat_val(player_stats, "iconEurope", pid)),
        "Asia_icons": _int(_stat_val(player_stats, "iconAsia", pid)),
        "Australia_icons": _int(_stat_val(player_stats, "iconAustralia", pid)),
        "Americas_icons": _int(_stat_val(player_stats, "iconAmericas", pid)),
        "Bird_icons": _int(_stat_val(player_stats, "iconBird", pid)),
        "Predator_icons": _int(_stat_val(player_stats, "iconPredator", pid)),
        "Herbivore_icons": _int(_stat_val(player_stats, "iconHerbivore", pid)),
        "Bear_icons": _int(_stat_val(player_stats, "iconBear", pid)),
        "Reptile_icons": _int(_stat_val(player_stats, "iconReptile", pid)),
        "Primate_icons": _int(_stat_val(player_stats, "iconPrimate", pid)),
        "Petting_Zoo_icons": _int(_stat_val(player_stats, "iconPet", pid)),
        "Sea_Animal_icons": _int(_stat_val(player_stats, "iconSeaAnimal", pid)),
        "Water_icons": _int(_stat_val(player_stats, "iconWater", pid)),
        "Rock_icons": _int(_stat_val(player_stats, "iconRock", pid)),
        "Science_icons": _int(_stat_val(player_stats, "iconScience", pid)),
        "action_1": _stat_label(player_stats, "drafted1", pid),
        "action_2": _stat_label(player_stats, "drafted2", pid),
        "action_3": _stat_label(player_stats, "drafted3", pid),
        "animals_action": _stat_val(player_stats, "actionCardAnimals", pid),
        "sponsors_action": _stat_val(player_stats, "actionCardSponsors", pid),
        "assoc_action": _stat_val(player_stats, "actionCardAssociation", pid),
        "build_action": _stat_val(player_stats, "actionCardBuild", pid),
        "cards_action": _stat_val(player_stats, "actionCardCards", pid),
    }
    return out


def transform_file(filepath):
    """Load a scraper JSON file and return transformed rows."""
    with open(filepath, encoding="utf-8") as f:
        raw_rows = json.load(f)
    rows = []
    for r in raw_rows:
        transformed = transform_row(r)
        if transformed is not None:
            rows.append(transformed)
    return rows


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python transform.py <scraper_output.json>")
        sys.exit(1)
    rows = transform_file(sys.argv[1])
    print(json.dumps(rows[:2], indent=2, default=str))
    print(f"\n... {len(rows)} rows transformed.")
