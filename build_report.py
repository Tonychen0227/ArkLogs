import json, glob, os, html
from collections import Counter, defaultdict
from datetime import datetime, timezone

FILES = [f for f in glob.glob(r"C:\Users\chentony\Git\arklogs\*.json") if "tobiko" not in os.path.basename(f).lower()]
START = datetime(2026, 4, 14, tzinfo=timezone.utc).timestamp() * 1000
END = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc).timestamp() * 1000

def I(v):
    try: return int(str(v).strip())
    except: return 0
def F(v):
    try: return float(str(v).strip())
    except: return 0.0
def is_win(g): return g["Game result"].strip().startswith("1st")
def day_of(g): return datetime.fromtimestamp(g["epoch_ms"]/1000, tz=timezone.utc).strftime("%Y-%m-%d")

players = []  # dict per player

for f in FILES:
    d = json.load(open(f, encoding="utf-8"))
    main = Counter(g["player_name"] for g in d).most_common(1)[0][0]
    # all in-season arena records for this file (both perspectives), keyed by game_link
    by_link = defaultdict(dict)
    for g in d:
        if not g.get("is_arena"): continue
        e = g["epoch_ms"]
        if e < START or e > END: continue
        by_link[g["game_link"]][g["player_name"]] = g
    # main-perspective games
    games = [recs[main] for recs in by_link.values() if main in recs]
    games.sort(key=lambda x: x["epoch_ms"])
    players.append({"name": main, "games": games, "by_link": by_link})

def pct(n, dparts):
    return f"{100.0*n/dparts:.1f}%" if dparts else "-"
def wr(w, total):
    return f"{w}-{total-w} ({pct(w,total)})" if total else "0-0 (-)"

# ---------- build stats per player ----------
for p in players:
    games = p["games"]
    n = len(games)
    wins = sum(1 for g in games if is_win(g))
    p["n"] = n; p["wins"] = wins
    # max arena
    p["max_arena"] = max((g["player_arena_elo_before"] + g["player_arena_elo_delta"]) for g in games)
    # avg opponent real elo
    p["avg_opp_elo"] = sum(g["opponent_elo_before"] for g in games) / n
    # performance rating (real elo): avg opp + 400*(W-L)/N
    losses = n - wins
    p["perf"] = p["avg_opp_elo"] + 400.0 * (wins - losses) / n
    # non-concession sets
    nc = [g for g in games if not g["conceded"]]
    p["nc"] = nc
    p["avg_turns_nc"] = (sum(I(g["Number of turns"]) for g in nc) / len(nc)) if nc else 0
    ppt = [I(g["Score"]) / I(g["Number of turns"]) for g in nc if I(g["Number of turns"]) > 0]
    p["ppt_nc"] = sum(ppt) / len(ppt) if ppt else 0
    # first/second
    firsts = [g for g in games if g["Starting position in first round"] == "First player"]
    seconds = [g for g in games if g["Starting position in first round"] == "Second player"]
    p["first"] = (sum(1 for g in firsts if is_win(g)), len(firsts))
    p["second"] = (sum(1 for g in seconds if is_win(g)), len(seconds))

    # ---- Table 2 daily swings ----
    daily = defaultdict(int)
    for g in games:
        daily[day_of(g)] += g["player_arena_elo_delta"]
    gain_day = max(daily.items(), key=lambda kv: kv[1])
    loss_day = min(daily.items(), key=lambda kv: kv[1])
    p["gain_day"] = gain_day; p["loss_day"] = loss_day
    won = [g for g in games if is_win(g)]
    lost = [g for g in games if not is_win(g)]
    sb = max(won, key=lambda g: g["opponent_elo_before"]) if won else None
    wl = min(lost, key=lambda g: g["opponent_elo_before"]) if lost else None
    p["strong_beat"] = sb; p["weak_loss"] = wl

    # ---- Table 3 map winrates ----
    maps = defaultdict(lambda: [0, 0])  # map -> [w, l]
    for g in games:
        m = g["Map"]
        if is_win(g): maps[m][0] += 1
        else: maps[m][1] += 1
    p["maps"] = maps

    # ---- Table 4 misc (needs both sides) ----
    caused = 0; noncaused = 0; nc_rounds = 0
    for g in games:
        recs = p["by_link"][g["game_link"]]
        others = [r for name, r in recs.items() if r is not g]
        opp = others[0] if others else None
        mb = I(g["Number of breaks triggered"])
        ob = I(opp["Number of breaks triggered"]) if opp else 0
        caused += mb; noncaused += ob
        if not g["conceded"]:
            nc_rounds += 1 + mb + ob
    p["caused"] = caused; p["noncaused"] = noncaused
    p["avg_rounds"] = nc_rounds / len(nc) if nc else 0
    trig_nc = sum(1 for g in nc if g["Triggered end of game"] == "Yes")
    p["trig_nc"] = (trig_nc, len(nc))

    # ---- Table 5 actions (non-conceded for parity with turns) ----
    act_keys = {"Animals": "Animals actions", "Association": "Association actions",
                "Sponsors": "Sponsors actions", "Cards": "Cards actions", "Build": "Build actions"}
    base = nc if nc else games
    act_avg = {}
    for label, key in act_keys.items():
        act_avg[label] = sum(I(g[key]) for g in base) / len(base)
    xback = sum(I(g["X-Tokens gained instead of action"]) for g in base) / len(base)
    p["act_avg"] = act_avg; p["xback"] = xback
    p["avg_actions"] = sum(act_avg.values())
    p["avg_turns_all_nc"] = p["avg_turns_nc"]

    # ---- Table 6 upgrades (proportion of non-conceded games) ----
    up_keys = {"Animals": "Upgraded Animals action card", "Build": "Upgraded Build action card",
               "Cards": "Upgraded Cards action card", "Sponsors": "Upgraded Sponsors action card",
               "Association": "Upgraded Association action card"}
    up_prop = {label: (sum(1 for g in base if g[key] == "Yes") / len(base)) for label, key in up_keys.items()}
    p["up_prop"] = up_prop
    p["avg_up_nc"] = (sum(I(g["Upgraded action cards"]) for g in nc) / len(nc)) if nc else 0

    # ---- Scoring details (non-conceded only) ----
    sc_keys = {"Score": "Score", "Sponsors Played": "Played sponsors", "Appeal": "Appeal",
               "Conservation": "Conservation", "Released Animals": "Released animals"}
    p["scoring"] = {label: (sum(I(g[key]) for g in nc) / len(nc)) if nc else 0
                    for label, key in sc_keys.items()}

    # ---- Score margins (non-conceded; margin = own score - opponent score) ----
    win_margins = []; loss_margins = []
    for g in nc:
        recs = p["by_link"][g["game_link"]]
        others = [r for name, r in recs.items() if r is not g]
        opp = others[0] if others else None
        if opp is None: continue
        margin = I(g["Score"]) - I(opp["Score"])
        if is_win(g): win_margins.append(margin)
        else: loss_margins.append(margin)
    p["win_margin"] = (sum(win_margins) / len(win_margins)) if win_margins else None
    p["loss_margin"] = (sum(loss_margins) / len(loss_margins)) if loss_margins else None

    # ---- Concession rates (of all wins / all losses) ----
    win_games = [g for g in games if is_win(g)]
    loss_games = [g for g in games if not is_win(g)]
    p["win_conc"] = (sum(1 for g in win_games if g["conceded"]), len(win_games))
    p["loss_conc"] = (sum(1 for g in loss_games if g["conceded"]), len(loss_games))

# order players by max arena desc
players.sort(key=lambda p: p["max_arena"], reverse=True)

# ---------- HTML ----------
def esc(s): return html.escape(str(s))
out = []
out.append("""<!DOCTYPE html><html><head><meta charset='utf-8'><title>Ark Nova Arena Season Stats</title>
<style>
:root{--ink:#1a2733;--head:#2c3e50;--line:#c8d0d8;--zebra:#eef2f6;}
*{box-sizing:border-box;}
body{font-family:'Segoe UI',Arial,sans-serif;margin:24px;background:#fff;color:var(--ink);}
h1{margin:0 0 2px;font-size:24px;}
h2{margin:34px 0 4px;font-size:18px;border-bottom:2px solid var(--head);padding-bottom:4px;color:var(--head);}
h3{margin:0 0 4px;font-size:13px;color:var(--head);}
table{border-collapse:collapse;margin:10px 0 4px;background:#fff;width:100%;font-variant-numeric:tabular-nums;}
th,td{border:1px solid var(--line);padding:5px 9px;text-align:right;font-size:12.5px;white-space:nowrap;}
th{background:var(--head);color:#fff;text-align:center;font-weight:600;}
td.l,th.l{text-align:left;}
tbody tr:nth-child(even),tr:nth-child(even){background:var(--zebra);}
.sub{color:#5a6b7a;font-size:11.5px;margin:2px 0 0;}
.maps{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px 20px;margin-top:12px;}
.maps table{margin:4px 0;}
.mapcard{break-inside:avoid;page-break-inside:avoid;}
table,tr,thead{break-inside:avoid;page-break-inside:avoid;}
h2,h3{break-after:avoid;page-break-after:avoid;}
@page{size:A4 landscape;margin:12mm;}
@media print{
  body{margin:0;-webkit-print-color-adjust:exact;print-color-adjust:exact;}
  th{background:var(--head)!important;color:#fff!important;}
  tbody tr:nth-child(even),tr:nth-child(even){background:var(--zebra)!important;}
  h2{page-break-before:auto;}
  table{box-shadow:none;font-size:11px;}
  th,td{padding:4px 7px;font-size:11px;}
  .maps{grid-template-columns:repeat(3,1fr);gap:8px 12px;}
}
</style></head><body>""")
out.append("<h1>Ark Nova Arena Season Stats</h1>")
out.append(f"<div class='sub'>Season: 2026-04-14 00:00 UTC &ndash; 2026-07-15 12:00 UTC &middot; Arena games only &middot; {len(players)} players</div>")

# Table 1
out.append("<h2>Table 1 &mdash; Summary</h2><table>")
out.append("<tr><th class='l'>Player</th><th>Games</th><th>Winrate</th><th>Max Arena</th>"
           "<th>Avg Opp Elo</th><th>Perf Rating</th><th>Avg Turns (non-conc)</th>"
           "<th>Pts/Turn (non-conc)</th><th>Winrate 1st</th><th>Winrate 2nd</th></tr>")
for p in players:
    fw, fn = p["first"]; sw, sn = p["second"]
    out.append("<tr>"
        f"<td class='l'>{esc(p['name'])}</td>"
        f"<td>{p['n']}</td>"
        f"<td>{wr(p['wins'],p['n'])}</td>"
        f"<td>{p['max_arena']}</td>"
        f"<td>{p['avg_opp_elo']:.0f}</td>"
        f"<td>{p['perf']:.0f}</td>"
        f"<td>{p['avg_turns_nc']:.1f}</td>"
        f"<td>{p['ppt_nc']:.2f}</td>"
        f"<td>{wr(fw,fn)}</td>"
        f"<td>{wr(sw,sn)}</td>"
        "</tr>")
out.append("</table>")

# Table 2
out.append("<h2>Table 2 &mdash; Daily Swings &amp; Opponents</h2>"
           "<div class='sub'>Arena-elo based. Strongest/weakest opponents by real Elo (before game).</div><table>")
out.append("<tr><th class='l'>Player</th><th>Most Arena Gained (1 day)</th>"
           "<th>Most Arena Lost (1 day)</th>"
           "<th>Strongest Beaten (opp Elo)</th><th>Weakest Lost To (opp Elo)</th></tr>")
for p in players:
    gd, gv = p["gain_day"]; ld, lv = p["loss_day"]
    sb = p["strong_beat"]; wl = p["weak_loss"]
    sbs = f"{sb['opponent_elo_before']} ({esc(sb['opponent_name'])})" if sb else "-"
    wls = f"{wl['opponent_elo_before']} ({esc(wl['opponent_name'])})" if wl else "-"
    out.append("<tr>"
        f"<td class='l'>{esc(p['name'])}</td>"
        f"<td>{gv:+d} ({gd})</td>"
        f"<td>{lv:+d} ({ld})</td>"
        f"<td>{sbs}</td><td>{wls}</td>"
        "</tr>")
out.append("</table>")

# Table 3 (per player)
out.append("<h2>Table 3 &mdash; Map Winrates (per player)</h2><div class='maps'>")
for p in players:
    out.append(f"<div class='mapcard'><h3>{esc(p['name'])}</h3><table>")
    out.append("<tr><th class='l'>Map</th><th>Games</th><th>W-L (%)</th></tr>")
    for m in sorted(p["maps"].keys()):
        w, l = p["maps"][m]; tot = w + l
        out.append(f"<tr><td class='l'>{esc(m)}</td><td>{tot}</td><td>{wr(w,tot)}</td></tr>")
    out.append("</table></div>")
out.append("</div>")

# Table 4
out.append("<h2>Table 4 &mdash; Miscellaneous</h2>"
           "<div class='sub'>Break share uses both players' data. Rounds = 1 + total breaks by both. "
           "Endgame trigger rate is non-conceded only.</div><table>")
out.append("<tr><th class='l'>Player</th><th>Breaks Caused</th><th>Breaks (opp)</th>"
           "<th>Break Share % (caused/total)</th><th>Avg Rounds/Game (non-conc)</th><th>Endgame Trigger Rate (non-conc)</th></tr>")
for p in players:
    total_breaks = p["caused"] + p["noncaused"]
    share = pct(p["caused"], total_breaks)
    tw, tn = p["trig_nc"]
    out.append("<tr>"
        f"<td class='l'>{esc(p['name'])}</td>"
        f"<td>{p['caused']}</td><td>{p['noncaused']}</td>"
        f"<td>{share}</td>"
        f"<td>{p['avg_rounds']:.2f}</td>"
        f"<td>{pct(tw,tn)} ({tw}/{tn})</td>"
        "</tr>")
out.append("</table>")

# Table 5
out.append("<h2>Table 5 &mdash; Action Utilization (avg per non-conceded game)</h2>"
           "<div class='sub'>All averages over non-conceded games (concessions truncate action counts). "
           "'X back' = X-Tokens gained instead of an action. Total actions &asymp; turns since each turn is one action or an X-back.</div><table>")
out.append("<tr><th class='l'>Player</th><th>Animals</th><th>Association</th><th>Sponsors</th>"
           "<th>Cards</th><th>Build</th><th>X back</th><th>Avg Actions/Game</th><th>Avg Turns/Game</th></tr>")
for p in players:
    a = p["act_avg"]
    out.append("<tr>"
        f"<td class='l'>{esc(p['name'])}</td>"
        f"<td>{a['Animals']:.2f}</td><td>{a['Association']:.2f}</td><td>{a['Sponsors']:.2f}</td>"
        f"<td>{a['Cards']:.2f}</td><td>{a['Build']:.2f}</td><td>{p['xback']:.2f}</td>"
        f"<td>{p['avg_actions']:.2f}</td><td>{p['avg_turns_nc']:.1f}</td>"
        "</tr>")
out.append("</table>")

# Table 6
out.append("<h2>Table 6 &mdash; Upgrade Rates</h2>"
           "<div class='sub'>Values = proportion of non-conceded games in which each action card was upgraded. "
           "Avg upgrades/game is non-conceded only.</div><table>")
out.append("<tr><th class='l'>Player</th><th>Animals</th><th>Build</th><th>Cards</th>"
           "<th>Sponsors</th><th>Association</th><th>Avg Upgrades/Game (non-conc)</th></tr>")
for p in players:
    u = p["up_prop"]
    out.append("<tr>"
        f"<td class='l'>{esc(p['name'])}</td>"
        f"<td>{u['Animals']*100:.1f}%</td><td>{u['Build']*100:.1f}%</td><td>{u['Cards']*100:.1f}%</td>"
        f"<td>{u['Sponsors']*100:.1f}%</td><td>{u['Association']*100:.1f}%</td>"
        f"<td>{p['avg_up_nc']:.2f}</td>"
        "</tr>")
out.append("</table>")

# Table 7 - Scoring details
out.append("<h2>Table 7 &mdash; Scoring Details</h2>"
           "<div class='sub'>Averages per non-conceded arena game. Margin = own score &minus; opponent score.</div><table>")
out.append("<tr><th class='l'>Player</th><th>Avg Score</th><th>Avg Sponsors Played</th><th>Avg Appeal</th>"
           "<th>Avg Conservation</th><th>Avg Released Animals</th>"
           "<th>Avg Margin (won)</th><th>Avg Margin (lost)</th>"
           "<th>% Won by Concession</th><th>% Lost by Concession</th></tr>")
for p in players:
    s = p["scoring"]
    wm = f"{p['win_margin']:+.1f}" if p['win_margin'] is not None else "-"
    lm = f"{p['loss_margin']:+.1f}" if p['loss_margin'] is not None else "-"
    wc, wct = p["win_conc"]; lc, lct = p["loss_conc"]
    out.append("<tr>"
        f"<td class='l'>{esc(p['name'])}</td>"
        f"<td>{s['Score']:.1f}</td>"
        f"<td>{s['Sponsors Played']:.2f}</td>"
        f"<td>{s['Appeal']:.1f}</td>"
        f"<td>{s['Conservation']:.1f}</td>"
        f"<td>{s['Released Animals']:.2f}</td>"
        f"<td>{wm}</td>"
        f"<td>{lm}</td>"
        f"<td>{pct(wc,wct)} ({wc}/{wct})</td>"
        f"<td>{pct(lc,lct)} ({lc}/{lct})</td>"
        "</tr>")
out.append("</table>")

out.append("</body></html>")

open(r"C:\Users\chentony\Git\arklogs\arena_report.html", "w", encoding="utf-8").write("\n".join(out))
print("Wrote arena_report.html")
for p in players:
    print(f"{p['name']:22s} games={p['n']:4d} wr={pct(p['wins'],p['n']):>6s} maxArena={p['max_arena']} perf={p['perf']:.0f}")
