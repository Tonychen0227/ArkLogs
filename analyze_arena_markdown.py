import argparse
import html
import json
import math
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


DEFAULT_FOLDER = Path("arena_data_2026_7_11")
DEFAULT_OUTPUT = Path("arena_stats.md")


def to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def format_float(value, digits=1):
    if value is None:
        return "n/a"
    return f"{value:.{digits}f}"


def format_percent(numerator, denominator):
    if not denominator:
        return "n/a"
    return f"{100 * numerator / denominator:.1f}%"


def is_yes(value):
    return str(value).strip().lower() == "yes"


def format_record(record):
    if record is None:
        return "n/a"
    return f"{record['name']} ({record['elo']})"


def format_day(day_item):
    if day_item is None:
        return "n/a"
    day, delta = day_item
    return f"{day} ({delta:+d})"


def clean_map_name(raw_name):
    if not raw_name:
        return "Unknown"
    if ": " in raw_name:
        return raw_name.split(": ", 1)[1]
    return raw_name


def escape_md(value):
    text = str(value)
    return text.replace("|", "\\|")


def escape_html(value):
    return html.escape(str(value), quote=True)


def performance_rating(avg_opponent_elo, wins, games):
    if avg_opponent_elo is None or not games:
        return None
    score_rate = wins / games
    if score_rate <= 0:
        return round(avg_opponent_elo - 800, 1)
    if score_rate >= 1:
        return round(avg_opponent_elo + 800, 1)
    return round(avg_opponent_elo + 400 * math.log10(score_rate / (1 - score_rate)), 1)


def load_player_records(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    owner_counts = Counter(record.get("player_name") for record in data if record.get("player_name"))
    if not owner_counts:
        raise ValueError(f"No player_name values found in {path}")

    owner = owner_counts.most_common(1)[0][0]
    owner_records = []
    seen_game_links = set()

    for record in data:
        if record.get("player_name") != owner:
            continue
        if not record.get("is_arena"):
            continue
        if record.get("player_arena_elo_before") is None:
            continue

        game_link = record.get("game_link")
        if game_link in seen_game_links:
            continue
        seen_game_links.add(game_link)
        owner_records.append(record)

    return owner, owner_records


def build_game_player_lookup(folder):
    lookup = {}
    for path in sorted(folder.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for record in data:
            if not record.get("is_arena"):
                continue
            if record.get("player_arena_elo_before") is None:
                continue
            game_link = record.get("game_link")
            player_name = record.get("player_name")
            if not game_link or not player_name:
                continue
            lookup.setdefault((game_link, player_name), record)
    return lookup


def analyze_player(records, game_player_lookup):
    upgrade_fields = {
        "build": "Upgraded Build action card",
        "association": "Upgraded Association action card",
        "sponsors": "Upgraded Sponsors action card",
        "animals": "Upgraded Animals action card",
        "cards": "Upgraded Cards action card",
    }
    icon_fields = {
        "africa": "Africa icons",
        "europe": "Europe icons",
        "asia": "Asia icons",
        "australia": "Australia icons",
        "americas": "Americas icons",
        "bird": "Bird icons",
        "predator": "Predator icons",
        "herbivore": "Herbivore icons",
        "bear": "Bear icons",
        "reptile": "Reptile icons",
        "primate": "Primate icons",
        "petting_zoo": "Petting Zoo icons",
        "sea_animal": "Sea Animal icons",
    }
    action_fields = {
        "build": "Build actions",
        "animals": "Animals actions",
        "sponsors": "Sponsors actions",
        "association": "Association actions",
        "cards": "Cards actions",
        "x_back": "X-Tokens gained instead of action",
    }
    stats = {
        "games": 0,
        "wins": 0,
        "losses": 0,
        "arena_max": None,
        "opponent_elos": [],
        "non_conceded_games": 0,
        "turns_total": 0,
        "points_total": 0,
        "first_games": 0,
        "first_wins": 0,
        "second_games": 0,
        "second_wins": 0,
        "map_stats": defaultdict(lambda: {"games": 0, "wins": 0}),
        "daily_delta": defaultdict(int),
        "best_win": None,
        "worst_loss": None,
        "upgrade_counts": {key: 0 for key in upgrade_fields},
        "upgrade_games": {key: 0 for key in upgrade_fields},
        "upgraded_action_cards_total": 0,
        "upgraded_action_cards_games": 0,
        "breaks_caused": 0,
        "breaks_total": 0,
        "break_games": 0,
        "rounds_total": 0,
        "endgame_triggers": 0,
        "endgame_games": 0,
        "action_totals": {key: 0 for key in action_fields},
        "action_games": {key: 0 for key in action_fields},
        "total_actions": 0,
        "total_action_games": 0,
        "icon_totals": {key: 0 for key in icon_fields},
        "icon_games": {key: 0 for key in icon_fields},
    }

    for record in records:
        stats["games"] += 1
        win = str(record.get("Game result", "")).startswith("1st")
        if win:
            stats["wins"] += 1
        else:
            stats["losses"] += 1

        seat = record.get("Starting position in first round")
        if seat == "First player":
            stats["first_games"] += 1
            if win:
                stats["first_wins"] += 1
        elif seat == "Second player":
            stats["second_games"] += 1
            if win:
                stats["second_wins"] += 1

        arena_before = to_int(record.get("player_arena_elo_before"))
        arena_delta = to_int(record.get("player_arena_elo_delta")) or 0
        if arena_before is not None:
            arena_after = arena_before + arena_delta
            current_max = stats["arena_max"]
            if current_max is None:
                stats["arena_max"] = max(arena_before, arena_after)
            else:
                stats["arena_max"] = max(current_max, arena_before, arena_after)

        opponent_elo = to_int(record.get("opponent_elo_before"))
        if opponent_elo is not None:
            stats["opponent_elos"].append(opponent_elo)

        epoch_ms = record.get("epoch_ms")
        if epoch_ms:
            day = datetime.fromtimestamp(epoch_ms / 1000).strftime("%Y-%m-%d")
            stats["daily_delta"][day] += arena_delta

        turns = to_int(record.get("Number of turns"))
        score = to_int(record.get("Score"))
        if not record.get("conceded") and turns and score is not None:
            stats["non_conceded_games"] += 1
            stats["turns_total"] += turns
            stats["points_total"] += score

        map_name = clean_map_name(record.get("Map"))
        stats["map_stats"][map_name]["games"] += 1
        if win:
            stats["map_stats"][map_name]["wins"] += 1

        opponent_name = record.get("opponent_name")
        if opponent_name and opponent_elo is not None:
            candidate = {"name": opponent_name, "elo": opponent_elo}
            if win:
                if stats["best_win"] is None or opponent_elo > stats["best_win"]["elo"]:
                    stats["best_win"] = candidate
            else:
                if stats["worst_loss"] is None or opponent_elo < stats["worst_loss"]["elo"]:
                    stats["worst_loss"] = candidate

        for key, field_name in upgrade_fields.items():
            value = record.get(field_name)
            if value is None:
                continue
            stats["upgrade_games"][key] += 1
            if is_yes(value):
                stats["upgrade_counts"][key] += 1

        total_actions_this_game = 0
        has_all_action_fields = True
        for key, field_name in action_fields.items():
            action_count = to_int(record.get(field_name))
            if action_count is None:
                has_all_action_fields = False
                continue
            stats["action_totals"][key] += action_count
            stats["action_games"][key] += 1
            total_actions_this_game += action_count
        if has_all_action_fields:
            stats["total_actions"] += total_actions_this_game
            stats["total_action_games"] += 1

        for key, field_name in icon_fields.items():
            icon_count = to_int(record.get(field_name))
            if icon_count is None:
                continue
            stats["icon_totals"][key] += icon_count
            stats["icon_games"][key] += 1

        upgraded_action_cards = to_int(record.get("Upgraded action cards"))
        if upgraded_action_cards is not None:
            stats["upgraded_action_cards_total"] += upgraded_action_cards
            stats["upgraded_action_cards_games"] += 1

        endgame_triggered = record.get("Triggered end of game")
        if endgame_triggered is not None:
            stats["endgame_games"] += 1
            if is_yes(endgame_triggered):
                stats["endgame_triggers"] += 1

        player_breaks = to_int(record.get("Number of breaks triggered"))
        if player_breaks is not None:
            opponent_name = record.get("opponent_name")
            opponent_record = game_player_lookup.get((record.get("game_link"), opponent_name)) if opponent_name else None
            opponent_breaks = to_int(opponent_record.get("Number of breaks triggered")) if opponent_record else None
            if opponent_breaks is not None:
                total_breaks = player_breaks + opponent_breaks
                stats["breaks_caused"] += player_breaks
                stats["breaks_total"] += total_breaks
                stats["break_games"] += 1
                stats["rounds_total"] += total_breaks + 1

    avg_opponent_elo = None
    if stats["opponent_elos"]:
        avg_opponent_elo = sum(stats["opponent_elos"]) / len(stats["opponent_elos"])

    average_turns = None
    average_points_per_turn = None
    average_points = None
    if stats["non_conceded_games"]:
        average_turns = stats["turns_total"] / stats["non_conceded_games"]
        average_points = stats["points_total"] / stats["non_conceded_games"]
    if stats["turns_total"]:
        average_points_per_turn = stats["points_total"] / stats["turns_total"]

    best_day = None
    worst_day = None
    if stats["daily_delta"]:
        best_day = max(stats["daily_delta"].items(), key=lambda item: item[1])
        worst_day = min(stats["daily_delta"].items(), key=lambda item: item[1])

    map_rows = []
    for map_name, map_stats in sorted(stats["map_stats"].items()):
        wins = map_stats["wins"]
        games = map_stats["games"]
        map_rows.append({
            "map": map_name,
            "wins": wins,
            "losses": games - wins,
            "winrate": format_percent(wins, games),
        })

    upgrade_rates = {
        key: {
            "count": stats["upgrade_counts"][key],
            "games": stats["upgrade_games"][key],
            "rate": format_percent(stats["upgrade_counts"][key], stats["upgrade_games"][key]),
        }
        for key in upgrade_fields
    }

    avg_upgrades_per_game = None
    if stats["upgraded_action_cards_games"]:
        avg_upgrades_per_game = stats["upgraded_action_cards_total"] / stats["upgraded_action_cards_games"]

    misc = {
        "break_share": format_percent(stats["breaks_caused"], stats["breaks_total"]),
        "break_share_count": f"{stats['breaks_caused']}/{stats['breaks_total']}" if stats["breaks_total"] else "n/a",
        "avg_rounds": (stats["rounds_total"] / stats["break_games"]) if stats["break_games"] else None,
        "endgame_trigger_rate": format_percent(stats["endgame_triggers"], stats["endgame_games"]),
        "endgame_trigger_count": f"{stats['endgame_triggers']}/{stats['endgame_games']}" if stats["endgame_games"] else "n/a",
    }

    action_utilization = {
        key: (stats["action_totals"][key] / stats["action_games"][key]) if stats["action_games"][key] else None
        for key in action_fields
    }
    avg_actions_per_game = (stats["total_actions"] / stats["total_action_games"]) if stats["total_action_games"] else None
    icon_averages = {
        key: (stats["icon_totals"][key] / stats["icon_games"][key]) if stats["icon_games"][key] else None
        for key in icon_fields
    }

    return {
        "games": stats["games"],
        "wins": stats["wins"],
        "losses": stats["losses"],
        "winrate": format_percent(stats["wins"] , stats["games"]),
        "arena_max": stats["arena_max"],
        "avg_opponent_elo": avg_opponent_elo,
        "performance": performance_rating(avg_opponent_elo, stats["wins"], stats["games"]),
        "avg_turns": average_turns,
        "avg_points_per_turn": average_points_per_turn,
        "avg_points": average_points,
        "first_player": f"{stats['first_wins']}-{stats['first_games'] - stats['first_wins']} ({format_percent(stats['first_wins'], stats['first_games'])})",
        "second_player": f"{stats['second_wins']}-{stats['second_games'] - stats['second_wins']} ({format_percent(stats['second_wins'], stats['second_games'])})",
        "best_day": best_day,
        "worst_day": worst_day,
        "best_win": stats["best_win"],
        "worst_loss": stats["worst_loss"],
        "upgrade_rates": upgrade_rates,
        "avg_upgrades_per_game": avg_upgrades_per_game,
        "action_utilization": action_utilization,
        "avg_actions_per_game": avg_actions_per_game,
        "icon_averages": icon_averages,
        "misc": misc,
        "maps": map_rows,
    }


def build_markdown(results, folder):
    lines = [
        "# Arena Stats",
        "",
        f"Source folder: `{folder}`",
        "",
        "Arena-only games with `player_arena_elo_before` present are included. `table_infos` is ignored. Each file is filtered to its prevalent `player_name`, then deduplicated by `game_link`.",
        "",
        "## Summary",
        "",
        "| Player | Games | Winrate | Max Arena | Avg Opp Elo | Perf Rating | Avg Turns NC | Avg Pts/Turn NC | Avg Pts NC | First Player WR | Second Player WR |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]

    for player, summary in results:
        lines.append(
            "| {player} | {games} | {wins}-{losses} ({winrate}) | {arena_max} | {avg_opp} | {perf} | {avg_turns} | {avg_ppt} | {avg_points} | {first_wr} | {second_wr} |".format(
                player=escape_md(player),
                games=summary["games"],
                wins=summary["wins"],
                losses=summary["losses"],
                winrate=summary["winrate"],
                arena_max=summary["arena_max"] if summary["arena_max"] is not None else "n/a",
                avg_opp=format_float(summary["avg_opponent_elo"], 1),
                perf=format_float(summary["performance"], 1),
                avg_turns=format_float(summary["avg_turns"], 2),
                avg_ppt=format_float(summary["avg_points_per_turn"], 3),
                avg_points=format_float(summary["avg_points"], 2),
                first_wr=escape_md(summary["first_player"]),
                second_wr=escape_md(summary["second_player"]),
            )
        )

    lines.extend([
        "",
        "## Upgrade Rates",
        "",
        "| Player | Build | Assoc | Sponsors | Animals | Cards | Avg Upgrades/Game |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])

    for player, summary in results:
        upgrades = summary["upgrade_rates"]
        lines.append(
            "| {player} | {build} | {association} | {sponsors} | {animals} | {cards} | {avg_upgrades} |".format(
                player=escape_md(player),
                build=escape_md(upgrades["build"]["rate"]),
                association=escape_md(upgrades["association"]["rate"]),
                sponsors=escape_md(upgrades["sponsors"]["rate"]),
                animals=escape_md(upgrades["animals"]["rate"]),
                cards=escape_md(upgrades["cards"]["rate"]),
                avg_upgrades=escape_md(format_float(summary["avg_upgrades_per_game"], 2)),
            )
        )

    lines.extend([
        "",
        "## Miscellaneous Stats",
        "",
        "| Player | Break Share | Avg Rounds/Game | Endgame Trigger Rate |",
        "| --- | --- | ---: | --- |",
    ])

    for player, summary in results:
        misc = summary["misc"]
        lines.append(
            "| {player} | {break_share} ({break_counts}) | {avg_rounds} | {endgame_rate} ({endgame_counts}) |".format(
                player=escape_md(player),
                break_share=escape_md(misc["break_share"]),
                break_counts=escape_md(misc["break_share_count"]),
                avg_rounds=escape_md(format_float(misc["avg_rounds"], 2)),
                endgame_rate=escape_md(misc["endgame_trigger_rate"]),
                endgame_counts=escape_md(misc["endgame_trigger_count"]),
            )
        )

    lines.extend([
        "",
        "## Action Utilization Rates",
        "",
        "| Player | Build/Game | Animals/Game | Sponsors/Game | Assoc/Game | Cards/Game | X Back/Game | Avg Actions/Game |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])

    for player, summary in results:
        actions = summary["action_utilization"]
        lines.append(
            "| {player} | {build} | {animals} | {sponsors} | {association} | {cards} | {x_back} | {avg_actions} |".format(
                player=escape_md(player),
                build=escape_md(format_float(actions["build"], 2)),
                animals=escape_md(format_float(actions["animals"], 2)),
                sponsors=escape_md(format_float(actions["sponsors"], 2)),
                association=escape_md(format_float(actions["association"], 2)),
                cards=escape_md(format_float(actions["cards"], 2)),
                x_back=escape_md(format_float(actions["x_back"], 2)),
                avg_actions=escape_md(format_float(summary["avg_actions_per_game"], 2)),
            )
        )

    lines.extend([
        "",
        "## Average Icons Per Game",
        "",
        "| Player | Africa | Europe | Asia | Australia | Americas | Bird | Predator | Herbivore | Bear | Reptile | Primate | Petting Zoo | Sea Animal |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])

    for player, summary in results:
        icons = summary["icon_averages"]
        lines.append(
            "| {player} | {africa} | {europe} | {asia} | {australia} | {americas} | {bird} | {predator} | {herbivore} | {bear} | {reptile} | {primate} | {petting_zoo} | {sea_animal} |".format(
                player=escape_md(player),
                africa=escape_md(format_float(icons["africa"], 2)),
                europe=escape_md(format_float(icons["europe"], 2)),
                asia=escape_md(format_float(icons["asia"], 2)),
                australia=escape_md(format_float(icons["australia"], 2)),
                americas=escape_md(format_float(icons["americas"], 2)),
                bird=escape_md(format_float(icons["bird"], 2)),
                predator=escape_md(format_float(icons["predator"], 2)),
                herbivore=escape_md(format_float(icons["herbivore"], 2)),
                bear=escape_md(format_float(icons["bear"], 2)),
                reptile=escape_md(format_float(icons["reptile"], 2)),
                primate=escape_md(format_float(icons["primate"], 2)),
                petting_zoo=escape_md(format_float(icons["petting_zoo"], 2)),
                sea_animal=escape_md(format_float(icons["sea_animal"], 2)),
            )
        )

    lines.extend([
        "",
        "## Daily Swings And Opponents",
        "",
        "| Player | Most Arena Gained 1 Day | Most Arena Lost 1 Day | Strongest Opponent Beat | Weakest Opponent Lost To |",
        "| --- | --- | --- | --- | --- |",
    ])

    for player, summary in results:
        lines.append(
            "| {player} | {best_day} | {worst_day} | {best_win} | {worst_loss} |".format(
                player=escape_md(player),
                best_day=escape_md(format_day(summary["best_day"])),
                worst_day=escape_md(format_day(summary["worst_day"])),
                best_win=escape_md(format_record(summary["best_win"])),
                worst_loss=escape_md(format_record(summary["worst_loss"])),
            )
        )

    lines.extend([
        "",
        "## Map Winrates",
    ])

    for player, summary in results:
        lines.extend([
            "",
            f"### {escape_md(player)}",
            "",
            "| Map | Wins | Losses | Winrate |",
            "| --- | ---: | ---: | ---: |",
        ])
        for map_row in summary["maps"]:
            lines.append(
                "| {map_name} | {wins} | {losses} | {winrate} |".format(
                    map_name=escape_md(map_row["map"]),
                    wins=map_row["wins"],
                    losses=map_row["losses"],
                    winrate=map_row["winrate"],
                )
            )

    lines.extend([
        "",
        "## Notes",
        "",
        "- Performance rating uses the Elo-style estimate `avg_opponent_elo + 400 * log10(score_rate / (1 - score_rate))`, capped to `avg_opponent_elo +/- 800` for 100% or 0% score rates.",
        "- Non-conceded averages exclude records where `conceded` is true.",
    ])
    return "\n".join(lines) + "\n"


def build_html(results, folder):
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '  <meta charset="utf-8">',
        '  <meta name="viewport" content="width=device-width, initial-scale=1">',
        "  <title>Arena Stats</title>",
        "  <style>",
        "    :root { color-scheme: light; }",
        "    body { font-family: Segoe UI, Arial, sans-serif; margin: 24px; line-height: 1.5; color: #1f2328; }",
        "    h1, h2, h3 { margin-bottom: 0.4em; }",
        "    p, ul { margin-top: 0; }",
        "    table, th, td { box-sizing: border-box; }",
        "    table { border-collapse: collapse; margin: 16px 0 24px; min-width: 720px; }",
        "    th, td { border: 1px solid #8c959f; padding: 8px 10px; text-align: left; vertical-align: top; }",
        "    th { background: #f6f8fa; }",
        "    td.num, th.num { text-align: right; }",
        "    .table-wrap { overflow-x: auto; }",
        "    code { background: #f6f8fa; padding: 0.1em 0.3em; border-radius: 4px; }",
        "    @page { size: auto; margin: 12mm; }",
        "    @media print {",
        "      body { margin: 0; font-size: 10pt; }",
        "      table { width: 100%; min-width: 0; table-layout: fixed; margin: 12px 0 18px; font-size: 8.5pt; }",
        "      th, td { padding: 4px 6px; overflow-wrap: anywhere; word-break: break-word; }",
        "      .table-wrap { overflow: visible; }",
        "      code { white-space: normal; }",
        "    }",
        "  </style>",
        "</head>",
        "<body>",
        "  <h1>Arena Stats</h1>",
        f"  <p>Source folder: <code>{escape_html(folder)}</code></p>",
        "  <p>Arena-only games with <code>player_arena_elo_before</code> present are included. <code>table_infos</code> is ignored. Each file is filtered to its prevalent <code>player_name</code>, then deduplicated by <code>game_link</code>.</p>",
        "  <h2>Summary</h2>",
        "  <div class=\"table-wrap\">",
        "    <table>",
        "      <thead>",
        "        <tr>",
        "          <th>Player</th>",
        "          <th class=\"num\">Games</th>",
        "          <th>Winrate</th>",
        "          <th class=\"num\">Max Arena</th>",
        "          <th class=\"num\">Avg Opp Elo</th>",
        "          <th class=\"num\">Perf Rating</th>",
        "          <th class=\"num\">Avg Turns NC</th>",
        "          <th class=\"num\">Avg Pts/Turn NC</th>",
        "          <th class=\"num\">Avg Pts NC</th>",
        "          <th>First Player WR</th>",
        "          <th>Second Player WR</th>",
        "        </tr>",
        "      </thead>",
        "      <tbody>",
    ]

    for player, summary in results:
        parts.extend([
            "        <tr>",
            f"          <td>{escape_html(player)}</td>",
            f"          <td class=\"num\">{summary['games']}</td>",
            f"          <td>{escape_html('{}-{} ({})'.format(summary['wins'], summary['losses'], summary['winrate']))}</td>",
            f"          <td class=\"num\">{escape_html(summary['arena_max'] if summary['arena_max'] is not None else 'n/a')}</td>",
            f"          <td class=\"num\">{escape_html(format_float(summary['avg_opponent_elo'], 1))}</td>",
            f"          <td class=\"num\">{escape_html(format_float(summary['performance'], 1))}</td>",
            f"          <td class=\"num\">{escape_html(format_float(summary['avg_turns'], 2))}</td>",
            f"          <td class=\"num\">{escape_html(format_float(summary['avg_points_per_turn'], 3))}</td>",
            f"          <td class=\"num\">{escape_html(format_float(summary['avg_points'], 2))}</td>",
            f"          <td>{escape_html(summary['first_player'])}</td>",
            f"          <td>{escape_html(summary['second_player'])}</td>",
            "        </tr>",
        ])

    parts.extend([
        "      </tbody>",
        "    </table>",
        "  </div>",
        "  <h2>Upgrade Rates</h2>",
        "  <div class=\"table-wrap\">",
        "    <table>",
        "      <thead>",
        "        <tr>",
        "          <th>Player</th>",
        "          <th class=\"num\">Build</th>",
        "          <th class=\"num\">Assoc</th>",
        "          <th class=\"num\">Sponsors</th>",
        "          <th class=\"num\">Animals</th>",
        "          <th class=\"num\">Cards</th>",
        "          <th class=\"num\">Avg Upgrades/Game</th>",
        "        </tr>",
        "      </thead>",
        "      <tbody>",
    ])

    for player, summary in results:
        upgrades = summary["upgrade_rates"]
        parts.extend([
            "        <tr>",
            f"          <td>{escape_html(player)}</td>",
            f"          <td class=\"num\">{escape_html(upgrades['build']['rate'])}</td>",
            f"          <td class=\"num\">{escape_html(upgrades['association']['rate'])}</td>",
            f"          <td class=\"num\">{escape_html(upgrades['sponsors']['rate'])}</td>",
            f"          <td class=\"num\">{escape_html(upgrades['animals']['rate'])}</td>",
            f"          <td class=\"num\">{escape_html(upgrades['cards']['rate'])}</td>",
            f"          <td class=\"num\">{escape_html(format_float(summary['avg_upgrades_per_game'], 2))}</td>",
            "        </tr>",
        ])

    parts.extend([
        "      </tbody>",
        "    </table>",
        "  </div>",
        "  <h2>Miscellaneous Stats</h2>",
        "  <div class=\"table-wrap\">",
        "    <table>",
        "      <thead>",
        "        <tr>",
        "          <th>Player</th>",
        "          <th>Break Share</th>",
        "          <th class=\"num\">Avg Rounds/Game</th>",
        "          <th>Endgame Trigger Rate</th>",
        "        </tr>",
        "      </thead>",
        "      <tbody>",
    ])

    for player, summary in results:
        misc = summary["misc"]
        parts.extend([
            "        <tr>",
            f"          <td>{escape_html(player)}</td>",
            f"          <td>{escape_html('{} ({})'.format(misc['break_share'], misc['break_share_count']))}</td>",
            f"          <td class=\"num\">{escape_html(format_float(misc['avg_rounds'], 2))}</td>",
            f"          <td>{escape_html('{} ({})'.format(misc['endgame_trigger_rate'], misc['endgame_trigger_count']))}</td>",
            "        </tr>",
        ])

    parts.extend([
        "      </tbody>",
        "    </table>",
        "  </div>",
        "  <h2>Action Utilization Rates</h2>",
        "  <div class=\"table-wrap\">",
        "    <table>",
        "      <thead>",
        "        <tr>",
        "          <th>Player</th>",
        "          <th class=\"num\">Build/Game</th>",
        "          <th class=\"num\">Animals/Game</th>",
        "          <th class=\"num\">Sponsors/Game</th>",
        "          <th class=\"num\">Assoc/Game</th>",
        "          <th class=\"num\">Cards/Game</th>",
        "          <th class=\"num\">X Back/Game</th>",
        "          <th class=\"num\">Avg Actions/Game</th>",
        "        </tr>",
        "      </thead>",
        "      <tbody>",
    ])

    for player, summary in results:
        actions = summary["action_utilization"]
        parts.extend([
            "        <tr>",
            f"          <td>{escape_html(player)}</td>",
            f"          <td class=\"num\">{escape_html(format_float(actions['build'], 2))}</td>",
            f"          <td class=\"num\">{escape_html(format_float(actions['animals'], 2))}</td>",
            f"          <td class=\"num\">{escape_html(format_float(actions['sponsors'], 2))}</td>",
            f"          <td class=\"num\">{escape_html(format_float(actions['association'], 2))}</td>",
            f"          <td class=\"num\">{escape_html(format_float(actions['cards'], 2))}</td>",
            f"          <td class=\"num\">{escape_html(format_float(actions['x_back'], 2))}</td>",
            f"          <td class=\"num\">{escape_html(format_float(summary['avg_actions_per_game'], 2))}</td>",
            "        </tr>",
        ])

    parts.extend([
        "      </tbody>",
        "    </table>",
        "  </div>",
        "  <h2>Average Icons Per Game</h2>",
        "  <div class=\"table-wrap\">",
        "    <table>",
        "      <thead>",
        "        <tr>",
        "          <th>Player</th>",
        "          <th class=\"num\">Africa</th>",
        "          <th class=\"num\">Europe</th>",
        "          <th class=\"num\">Asia</th>",
        "          <th class=\"num\">Australia</th>",
        "          <th class=\"num\">Americas</th>",
        "          <th class=\"num\">Bird</th>",
        "          <th class=\"num\">Predator</th>",
        "          <th class=\"num\">Herbivore</th>",
        "          <th class=\"num\">Bear</th>",
        "          <th class=\"num\">Reptile</th>",
        "          <th class=\"num\">Primate</th>",
        "          <th class=\"num\">Petting Zoo</th>",
        "          <th class=\"num\">Sea Animal</th>",
        "        </tr>",
        "      </thead>",
        "      <tbody>",
    ])

    for player, summary in results:
        icons = summary["icon_averages"]
        parts.extend([
            "        <tr>",
            f"          <td>{escape_html(player)}</td>",
            f"          <td class=\"num\">{escape_html(format_float(icons['africa'], 2))}</td>",
            f"          <td class=\"num\">{escape_html(format_float(icons['europe'], 2))}</td>",
            f"          <td class=\"num\">{escape_html(format_float(icons['asia'], 2))}</td>",
            f"          <td class=\"num\">{escape_html(format_float(icons['australia'], 2))}</td>",
            f"          <td class=\"num\">{escape_html(format_float(icons['americas'], 2))}</td>",
            f"          <td class=\"num\">{escape_html(format_float(icons['bird'], 2))}</td>",
            f"          <td class=\"num\">{escape_html(format_float(icons['predator'], 2))}</td>",
            f"          <td class=\"num\">{escape_html(format_float(icons['herbivore'], 2))}</td>",
            f"          <td class=\"num\">{escape_html(format_float(icons['bear'], 2))}</td>",
            f"          <td class=\"num\">{escape_html(format_float(icons['reptile'], 2))}</td>",
            f"          <td class=\"num\">{escape_html(format_float(icons['primate'], 2))}</td>",
            f"          <td class=\"num\">{escape_html(format_float(icons['petting_zoo'], 2))}</td>",
            f"          <td class=\"num\">{escape_html(format_float(icons['sea_animal'], 2))}</td>",
            "        </tr>",
        ])

    parts.extend([
        "      </tbody>",
        "    </table>",
        "  </div>",
        "  <h2>Daily Swings And Opponents</h2>",
        "  <div class=\"table-wrap\">",
        "    <table>",
        "      <thead>",
        "        <tr>",
        "          <th>Player</th>",
        "          <th>Most Arena Gained 1 Day</th>",
        "          <th>Most Arena Lost 1 Day</th>",
        "          <th>Strongest Opponent Beat</th>",
        "          <th>Weakest Opponent Lost To</th>",
        "        </tr>",
        "      </thead>",
        "      <tbody>",
    ])

    for player, summary in results:
        parts.extend([
            "        <tr>",
            f"          <td>{escape_html(player)}</td>",
            f"          <td>{escape_html(format_day(summary['best_day']))}</td>",
            f"          <td>{escape_html(format_day(summary['worst_day']))}</td>",
            f"          <td>{escape_html(format_record(summary['best_win']))}</td>",
            f"          <td>{escape_html(format_record(summary['worst_loss']))}</td>",
            "        </tr>",
        ])

    parts.extend([
        "      </tbody>",
        "    </table>",
        "  </div>",
        "  <h2>Map Winrates</h2>",
    ])

    for player, summary in results:
        parts.extend([
            f"  <h3>{escape_html(player)}</h3>",
            "  <div class=\"table-wrap\">",
            "    <table>",
            "      <thead>",
            "        <tr>",
            "          <th>Map</th>",
            "          <th class=\"num\">Wins</th>",
            "          <th class=\"num\">Losses</th>",
            "          <th class=\"num\">Winrate</th>",
            "        </tr>",
            "      </thead>",
            "      <tbody>",
        ])
        for map_row in summary["maps"]:
            parts.extend([
                "        <tr>",
                f"          <td>{escape_html(map_row['map'])}</td>",
                f"          <td class=\"num\">{map_row['wins']}</td>",
                f"          <td class=\"num\">{map_row['losses']}</td>",
                f"          <td class=\"num\">{escape_html(map_row['winrate'])}</td>",
                "        </tr>",
            ])
        parts.extend([
            "      </tbody>",
            "    </table>",
            "  </div>",
        ])

    parts.extend([
        "  <h2>Notes</h2>",
        "  <ul>",
        "    <li>Performance rating uses the Elo-style estimate <code>avg_opponent_elo + 400 * log10(score_rate / (1 - score_rate))</code>, capped to <code>avg_opponent_elo +/- 800</code> for 100% or 0% score rates.</li>",
        "    <li>Non-conceded averages exclude records where <code>conceded</code> is true.</li>",
        "  </ul>",
        "</body>",
        "</html>",
    ])
    return "\n".join(parts) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Analyze arena logs and write markdown and HTML tables.")
    parser.add_argument("folder", nargs="?", default=str(DEFAULT_FOLDER), help="Folder containing exported JSON log files.")
    parser.add_argument("-o", "--output", default=str(DEFAULT_OUTPUT), help="Output markdown file path.")
    args = parser.parse_args()

    folder = Path(args.folder)
    if not folder.exists() or not folder.is_dir():
        raise SystemExit(f"Folder not found: {folder}")

    results = []
    game_player_lookup = build_game_player_lookup(folder)
    for path in sorted(folder.glob("*.json")):
        player, records = load_player_records(path)
        results.append((player, analyze_player(records, game_player_lookup)))

    markdown = build_markdown(results, folder)
    output_path = Path(args.output)
    html_output_path = output_path.with_suffix(".html")
    output_path.write_text(markdown, encoding="utf-8")
    html_output_path.write_text(build_html(results, folder), encoding="utf-8")
    print(f"Wrote markdown report to {output_path}")
    print(f"Wrote HTML report to {html_output_path}")


if __name__ == "__main__":
    main()