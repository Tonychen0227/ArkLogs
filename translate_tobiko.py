import json
import re
from collections import OrderedDict

src = json.load(open("tobiko.json", encoding="utf-8"))
logs = src["data"]["logs"]

# Event types that represent genuine player decisions (non-trivial).
# Everything else (state-machine, sync, token bookkeeping, display refill,
# derived resource gains, UI timers, running stat snapshots) is dropped.
NONTRIVIAL = {
    "chooseActionCard", "buyBuilding", "buyAnimal", "playSponsor",
    "moveProjects", "takeBonus", "snapCard", "markCard", "gainMarked",
    "releaseAnimal", "cutDown", "upgradeCard", "advanceBreak",
    "slideMeeples", "getBonuses",
    "pDrawCards", "pDiscardCards", "updateBreakDiscardSelection",
    "updateInitialActionCardSelection", "updateInitialActionCardsKeep",
    "updateInitialSelection",
}


def card_ids(lst):
    out = []
    for c in lst or []:
        if isinstance(c, dict):
            out.append(c.get("id"))
        else:
            out.append(c)
    return out


def encode(ev, chan_pid=None):
    """Return a compact record for a non-trivial event, or None to skip."""
    t = ev.get("type")
    a = ev.get("args", {}) or {}
    if not isinstance(a, dict):
        a = {}
    pid = a.get("player_id") or chan_pid
    # selection events nest payload under args.args._private
    priv = a.get("_private")
    if not isinstance(priv, dict):
        inner = a.get("args")
        if isinstance(inner, dict) and isinstance(inner.get("_private"), dict):
            priv = inner["_private"]
    if not isinstance(priv, dict):
        priv = {}

    if t == "chooseActionCard":
        ac = a.get("actionCard", {}) or {}
        return {"v": "ACT", "p": pid, "card": ac.get("type"),
                "strength": a.get("strength"), "level": ac.get("level")}

    if t == "buyBuilding":
        b = a.get("building", {}) or {}
        return {"v": "BUILD", "p": pid, "building": b.get("type"),
                "size": b.get("size"), "at": [b.get("x"), b.get("y")],
                "rot": b.get("rotation"), "pay": a.get("amount_money")}

    if t == "buyAnimal":
        return {"v": "ANIMAL", "p": pid, "card": a.get("card_id"),
                "pay": a.get("amount"), "fromDisplay": a.get("fromDisplay"),
                "into": card_ids(a.get("buildings"))}

    if t == "playSponsor":
        return {"v": "SPONSOR", "p": pid, "card": a.get("card_id"),
                "fromDisplay": a.get("fromDisplay")}

    if t == "moveProjects":
        return {"v": "PROJECT", "p": pid, "cards": card_ids(a.get("cards")),
                "fromDisplay": a.get("fromDisplay")}

    if t == "takeBonus":
        bd = a.get("bonus_desc", {})
        raw = bd.get("args", {}).get("bonus_raw_desc") if isinstance(bd, dict) else None
        return {"v": "ASSOC", "p": pid, "bonus": raw}

    if t == "snapCard":
        return {"v": "SNAP", "p": pid, "cards": card_ids(a.get("cards"))}

    if t == "markCard":
        cards = a.get("cards")
        ids = list(cards.keys()) if isinstance(cards, dict) else card_ids(cards)
        return {"v": "MARK", "p": pid, "cards": ids}

    if t == "gainMarked":
        return {"v": "GAINMARK", "p": pid, "card": a.get("card_id"),
                "gain": a.get("bonuses")}

    if t == "releaseAnimal":
        return {"v": "RELEASE", "p": pid, "card": a.get("card_id"),
                "gain": a.get("bonuses")}

    if t == "cutDown":
        return {"v": "CUT", "p": pid, "size": a.get("size"),
                "building": a.get("buildingId"), "gain": a.get("bonuses")}

    if t == "upgradeCard":
        ac = a.get("actionCard", {}) or {}
        return {"v": "UPGRADE", "p": pid, "card": ac.get("type")}

    if t == "advanceBreak":
        return {"v": "BREAK", "p": pid, "n": a.get("n"),
                "at": a.get("break"), "max": a.get("maxBreak")}

    if t == "slideMeeples":
        meeples = [{"kind": m.get("type"), "at": m.get("location")}
                   for m in (a.get("meeples") or [])]
        return {"v": "WORKER", "p": pid, "strength": a.get("strength"),
                "meeples": meeples}

    if t == "getBonuses":
        return {"v": "GAIN", "p": pid, "src": a.get("source"),
                "get": a.get("bonuses")}

    if t == "pDrawCards":
        return {"v": "DRAW", "p": pid, "cards": card_ids(a.get("cards"))}

    if t == "pDiscardCards":
        return {"v": "DISCARD", "p": pid, "cards": card_ids(a.get("cards"))}

    if t == "updateBreakDiscardSelection":
        return {"v": "BREAK_DISCARD", "p": pid,
                "keep": priv.get("selection"), "n": priv.get("n")}

    if t == "updateInitialActionCardSelection":
        return {"v": "DRAFT_ACTION", "p": pid, "pick": priv.get("selection")}

    if t == "updateInitialActionCardsKeep":
        return {"v": "DRAFT_ACTION_KEEP", "p": pid, "pick": priv.get("selection")}

    if t == "updateInitialSelection":
        return {"v": "DRAFT_HAND", "p": pid, "keep": priv.get("selection")}

    return None


# ---- collect player names ----
players = {}
for pkt in logs:
    for ev in pkt.get("data", []):
        a = ev.get("args", {})
        if isinstance(a, dict) and a.get("player_id") and a.get("player_name"):
            players[str(a["player_id"])] = a["player_name"]

# ---- group non-trivial events by move_id, dedupe by uid ----
moves = OrderedDict()
seen_uids = set()
for pkt in logs:
    if pkt.get("move_id") is None:
        continue
    mid = int(pkt.get("move_id"))
    t = pkt.get("time") or 0
    m = re.search(r"/player/p(\d+)", pkt.get("channel", "") or "")
    chan_pid = int(m.group(1)) if m else None
    for ev in pkt.get("data", []):
        if ev.get("type") not in NONTRIVIAL:
            continue
        uid = ev.get("uid")
        if uid in seen_uids:
            continue
        rec = encode(ev, chan_pid)
        if rec is None:
            continue
        # drop null fields for compactness
        rec = {k: v for k, v in rec.items() if v is not None}
        seen_uids.add(uid)
        if mid not in moves:
            moves[mid] = {"move": mid, "t": int(t), "actions": []}
        moves[mid]["actions"].append(rec)

out = {
    "table_id": logs[0]["table_id"] if logs else None,
    "game": "Ark Nova",
    "players": players,
    "moves": list(moves.values()),
}

with open("tobiko_translated.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)

# summary
import os
n_actions = sum(len(m["actions"]) for m in out["moves"])
print(f"moves with content : {len(out['moves'])}")
print(f"total actions      : {n_actions}")
print(f"players            : {players}")
print(f"src size  : {os.path.getsize('tobiko.json'):>10,} bytes")
print(f"out size  : {os.path.getsize('tobiko_translated.json'):>10,} bytes")
