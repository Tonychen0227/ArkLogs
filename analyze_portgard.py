import json
import re

DATA_FILE = "83927465_20260710_213848.json"

# Game speed option 200: values 0-5 are real-time, 9+ are turn-based or no-limit
REALTIME_SPEED_VALUES = {"0", "1", "2", "5"}

def is_realtime(game):
    """Return True if the game was played in real-time mode per table_infos."""
    try:
        speed_value = game["table_infos"]["data"]["options"]["200"]["value"]
        return str(speed_value) in REALTIME_SPEED_VALUES
    except (KeyError, TypeError):
        return False

def parse_minutes(tt):
    """Parse MM:SS thinking time string into decimal minutes."""
    m = re.fullmatch(r"(\d+):(\d{2})", tt)
    if m:
        return int(m.group(1)) + int(m.group(2)) / 60
    return None

def to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0

with open(DATA_FILE, "r", encoding="utf-8") as f:
    data = json.load(f)

portgard_games = [g for g in data if g["player_name"] == "portgard"]

# Keep only real-time games (authoritative from table_infos game speed option)
timed_games = []
for g in portgard_games:
    if not is_realtime(g):
        continue
    mins = parse_minutes(g["Thinking time"])
    if mins is None:
        continue
    timed_games.append((g, mins))

print(f"Total portgard records:              {len(portgard_games)}")
print(f"Real-time games (from table_infos):  {len(timed_games)}")
print()

# --- Average thinking time where portgard is First Player ---
first_player_games = [
    (g, mins) for g, mins in timed_games
    if g["Starting position in first round"] == "First player"
]
print(f"Games as First Player:               {len(first_player_games)}")
if first_player_games:
    avg_tt = sum(m for _, m in first_player_games) / len(first_player_games)
    mins_part = int(avg_tt)
    secs_part = round((avg_tt % 1) * 60)
    print(f"Average thinking time (1st player):  {avg_tt:.2f} min  ({mins_part}m {secs_part:02d}s)")

print()

# --- Points per minute of thinking time (overall, all timed games) ---
total_score = sum(to_int(g["Score"]) for g, _ in timed_games)
total_minutes = sum(m for _, m in timed_games)
pts_per_min = total_score / total_minutes if total_minutes else 0

print(f"Total score (all timed games):       {total_score}")
print(f"Total thinking time (min):           {total_minutes:.2f}")
print(f"Points per minute of thinking time:  {pts_per_min:.2f}")
