import asyncio
import json
from datetime import datetime


async def login_to_bga(page, email: str, password: str):
    """Log in to Board Game Arena with email and password."""
    print("Navigating to BGA...")
    await page.goto("https://en.boardgamearena.com/account")
    await page.wait_for_load_state("networkidle")

    # Dismiss cookie banner via Didomi API (clicking the button is unreliable)
    await page.evaluate("() => { try { Didomi.setUserAgreeToAll() } catch(e) {} }")
    await page.wait_for_timeout(500)
    print("Dismissed cookie banner.")

    # If already logged in, we get redirected to /welcome — skip login
    if "/welcome" in page.url:
        print("Already logged in!")
        return

    await page.screenshot(path="debug_login_1_before_email.png")

    # The login form (form[name='login']) may be behind the signup form.
    # Target it specifically and use force=True to bypass overlay issues.
    login_form = page.locator('form[name="login"]').first

    # Step 1: Enter email and click Next
    print("Entering email...")
    email_input = login_form.locator('input[placeholder="Email or username"]')
    await email_input.fill(email, force=True)
    await page.wait_for_timeout(500)

    next_btn = login_form.locator('a:has-text("Next")')
    await next_btn.click(force=True)
    print("Clicked Next, waiting for password step...")
    await page.wait_for_timeout(3000)

    await page.screenshot(path="debug_login_2_before_password.png")

    # Step 2: Enter password and click Login
    print("Entering password...")
    password_form = page.locator('form[name="login"]').filter(has=page.locator('a:has-text("Login")'))
    password_input = password_form.locator('input[type="password"]')
    await password_input.fill(password, force=True)
    await page.wait_for_timeout(500)

    # Check "Stay connected" to maintain login status
    stay_connected = password_form.locator('text=Stay connected')
    try:
        await stay_connected.click(force=True)
        print("Checked 'Stay connected'.")
    except Exception:
        pass
    await page.wait_for_timeout(500)

    login_btn = password_form.locator('a:has-text("Login")')
    await login_btn.click(force=True)

    # Wait for navigation after login
    await page.wait_for_load_state("networkidle")
    print("Login submitted. Waiting for redirect...")
    await page.wait_for_timeout(3000)

    await page.screenshot(path="debug_login_3_after_login.png")


async def navigate_to_history(page, player_id: str):
    """Navigate to a player's Ark Nova game history page."""
    print("Navigating to game history...")
    await page.goto(
        f"https://boardgamearena.com/gamestats?player={player_id}&opponent_id=0&finished=0&updateStats=1&game_id=1741"
    )
    await page.wait_for_load_state("networkidle")


async def scrape_games(page):
    """Scrape ranked games from the stats table, clicking 'see more' until done."""
    # Last arena season ended April 14, 2026 8PM GMT+8 (local)
    cutoff = datetime(2026, 4, 14, 20, 0, 0)
    all_games = []
    seen_count = 0
    no_new_rows_clicks = 0

    while True:
        # Extract only NEW games from table rows (skip already-processed ones)
        games = await page.evaluate("""
            (skipCount) => {
                const rows = document.querySelectorAll('table.statstable tr');
                const results = [];
                const now = new Date();
                const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
                const yesterday = new Date(today.getTime() - 86400000);

                let validIdx = 0;
                for (const row of rows) {
                    // Get game link
                    const link = row.querySelector('a[href*="/table"]');
                    if (!link) continue;

                    validIdx++;
                    if (validIdx <= skipCount) continue;

                    const href = link.href;

                    // Check if game has ELO data (4th td with rankdetails/gamerank)
                    const tdsAll = row.querySelectorAll('td');
                    if (tdsAll.length < 4) continue;
                    const eloTd = tdsAll[3];
                    const hasElo = eloTd && eloTd.querySelector('.gamerank_value, .gamerank');
                    if (!hasElo) continue;

                    // Check if this is an arena game
                    const isArena = !!row.querySelector('[class*="myarena_league"]');

                    // Get timestamp from the second td, first div.smalltext
                    const tds = row.querySelectorAll('td');
                    let timestamp = '';
                    let epochMs = 0;
                    if (tds.length >= 2) {
                        const dateDiv = tds[1].querySelector('div.smalltext');
                        if (dateDiv) {
                            timestamp = dateDiv.textContent.trim();
                            // Parse to epoch ms using browser timezone
                            const atParts = timestamp.split(' at ');
                            if (atParts.length === 2) {
                                const [timePart] = atParts[1].split(' ');
                                const [hours, minutes] = timePart.split(':').map(Number);
                                let baseDate = null;
                                if (atParts[0].toLowerCase() === 'today') {
                                    baseDate = new Date(today);
                                } else if (atParts[0].toLowerCase() === 'yesterday') {
                                    baseDate = new Date(yesterday);
                                } else if (atParts[0].includes('/')) {
                                    // "07/08/2026 at 23:20" - MM/DD/YYYY
                                    const [m, d, y] = atParts[0].split('/').map(Number);
                                    baseDate = new Date(y, m - 1, d);
                                }
                                if (baseDate && !isNaN(hours) && !isNaN(minutes)) {
                                    baseDate.setHours(hours, minutes, 0, 0);
                                    epochMs = baseDate.getTime();
                                }
                            }
                        }
                    }

                    // Check if conceded or abandoned
                    const rowText = row.textContent;
                    const conceded = rowText.includes('Game conceded');
                    const abandoned = rowText.includes('Table abandoned');

                    if (abandoned) continue;

                    results.push({ href, timestamp, epochMs, conceded, isArena });
                }
                return results;
            }
        """, seen_count)

        # Check if we've gone past the cutoff
        cutoff_ms = int(cutoff.timestamp() * 1000)
        stop = False
        new_count = 0
        for game in games:
            if game["epochMs"] and game["epochMs"] < cutoff_ms:
                stop = True
                break
            all_games.append(game)
            seen_count += 1
            new_count += 1

        if stop:
            break

        # Stop if 3 consecutive "see more" clicks yielded no new rows
        if new_count == 0:
            no_new_rows_clicks += 1
            if no_new_rows_clicks >= 3:
                break
        else:
            no_new_rows_clicks = 0

        # Click "see more" button located after the stats table
        clicked = await page.evaluate("""
            () => {
                const table = document.querySelector('table.statstable');
                if (!table) return false;
                // Walk siblings after the table to find the see more link
                let el = table.nextElementSibling;
                while (el) {
                    const link = el.matches && el.matches('a') ? el : el.querySelector('a');
                    if (link && link.textContent.toLowerCase().includes('see more')) {
                        link.click();
                        return true;
                    }
                    el = el.nextElementSibling;
                }
                return false;
            }
        """)
        if clicked:
            await page.wait_for_timeout(2000)
        else:
            break

    return all_games


async def scrape_game_details(page, game_url):
    """Navigate to a game page and extract stats for both players."""
    # Capture tableinfos API response
    table_infos = {}

    async def capture_tableinfos(response):
        nonlocal table_infos
        if "table/table/tableinfos.html" in response.url:
            try:
                table_infos = await response.json()
            except Exception:
                pass

    page.on("response", capture_tableinfos)

    await page.goto(game_url)
    await page.wait_for_load_state("networkidle")
    await page.wait_for_selector("#player_stats_table", timeout=15000)
    await page.wait_for_timeout(1000)

    page.remove_listener("response", capture_tableinfos)

    data = await page.evaluate("""
        () => {
            // Extract player IDs and names from score_entry divs
            const scoreEntries = document.querySelectorAll('[id^="score_entry_"]');
            const players = [];
            for (const entry of scoreEntries) {
                const id = entry.id.replace('score_entry_', '');
                const nameEl = entry.querySelector('.playername');
                const name = nameEl ? nameEl.textContent.trim() : '';
                const profile_link = nameEl ? nameEl.href : '';
                players.push({ id, name, profile_link });
            }

            // Extract ELO before game and delta for each player
            for (const player of players) {
                // Regular ELO
                const deltaEl = document.querySelector(`#winpoints_value_${player.id}`);
                const newRankEl = document.querySelector(`#newrank_${player.id} .gamerank_value`);
                const delta = deltaEl ? parseInt(deltaEl.textContent.trim()) : 0;
                const newElo = newRankEl ? parseInt(newRankEl.textContent.trim()) : 0;
                player.elo_before = newElo - delta;
                player.elo_delta = delta;

                // Arena ELO (may not exist for non-arena games)
                const arenaDeltaEl = document.querySelector(`#winpointsarena_value_${player.id}`);
                const arenaNewEl = document.querySelector(`#newrankarena_${player.id}`);
                if (arenaDeltaEl && arenaNewEl) {
                    const arenaDelta = parseInt(arenaDeltaEl.textContent.trim()) || 0;
                    const arenaNewText = arenaNewEl.textContent.trim();
                    const arenaNew = parseInt(arenaNewText) || 0;
                    player.arena_elo_before = arenaNew - arenaDelta;
                    player.arena_elo_delta = arenaDelta;
                } else {
                    player.arena_elo_before = null;
                    player.arena_elo_delta = null;
                }
            }

            // Extract stats table
            const table = document.querySelector('#player_stats_table');
            const stats = [];
            if (table) {
                const rows = table.querySelectorAll('tr');
                for (let i = 1; i < rows.length; i++) { // skip header row
                    const cells = rows[i].querySelectorAll('th, td');
                    if (cells.length < 3) continue;
                    const statName = cells[0].textContent.trim();
                    if (statName === 'All stats') continue; // skip link row
                    const values = [];
                    for (let c = 1; c < cells.length; c++) {
                        values.push(cells[c].textContent.trim());
                    }
                    stats.push({ name: statName, values });
                }
            }

            return { players, stats };
        }
    """)
    data["table_infos"] = table_infos
    return data


async def scrape_details_concurrent(context, games, concurrency=5):
    """Scrape game details for a list of games using concurrent tabs.

    Each item in `games` must have at minimum:
      - "href": the full game URL
    And optionally:
      - "epochMs", "conceded", "isArena" (from scrape_games)
      - or "table_id" (from run.py)

    Returns a list of detail dicts (failed games are excluded).
    """
    all_details = [None] * len(games)
    sem = asyncio.Semaphore(concurrency)

    async def scrape_one(i, game):
        async with sem:
            for attempt in range(5):
                tab = await context.new_page()
                try:
                    details = await scrape_game_details(tab, game["href"])
                    details["game_link"] = game["href"]
                    details["epoch_ms"] = game.get("epochMs", game.get("epoch_ms", 0))
                    details["conceded"] = game.get("conceded", False)
                    details["is_arena"] = game.get("isArena", game.get("is_arena", False))
                    all_details[i] = details
                    print(f"  Game {i+1}/{len(games)}: done")
                    return
                except Exception as e:
                    if attempt < 4:
                        print(f"  Game {i+1}/{len(games)}: retry {attempt+1} ({type(e).__name__})")
                        await asyncio.sleep(2 ** attempt)  # 1s, 2s, 4s, 8s backoff
                    else:
                        print(f"  Game {i+1}/{len(games)}: FAILED ({type(e).__name__})")
                finally:
                    await tab.close()

    await asyncio.gather(*(scrape_one(i, g) for i, g in enumerate(games)))
    return [d for d in all_details if d is not None]


def build_rows(all_details):
    """Convert scraped game details into flat JSON rows (one per player per game)."""
    if not all_details:
        return []

    stat_names = [s["name"] for s in all_details[0]["stats"]]
    rows = []

    for detail in all_details:
        players = detail["players"]
        if len(players) < 2:
            continue
        stats_dict = {s["name"]: s["values"] for s in detail["stats"]}

        for idx in range(2):
            player = players[idx]
            opponent = players[1 - idx]
            is_arena = detail.get("is_arena", False)
            record = {
                "game_link": detail["game_link"],
                "epoch_ms": detail["epoch_ms"],
                "conceded": detail["conceded"],
                "is_arena": is_arena,
                "table_infos": detail.get("table_infos", {}),
                "player_name": player.get("name", ""),
                "player_profile_link": player.get("profile_link", ""),
                "player_elo_before": player.get("elo_before", ""),
                "player_elo_delta": player.get("elo_delta", ""),
                "player_arena_elo_before": player.get("arena_elo_before") if is_arena and player.get("arena_elo_before") is not None else None,
                "player_arena_elo_delta": player.get("arena_elo_delta") if is_arena and player.get("arena_elo_delta") is not None else None,
                "opponent_name": opponent.get("name", ""),
                "opponent_profile_link": opponent.get("profile_link", ""),
                "opponent_elo_before": opponent.get("elo_before", ""),
                "opponent_elo_delta": opponent.get("elo_delta", ""),
                "opponent_arena_elo_before": opponent.get("arena_elo_before") if is_arena and opponent.get("arena_elo_before") is not None else None,
                "opponent_arena_elo_delta": opponent.get("arena_elo_delta") if is_arena and opponent.get("arena_elo_delta") is not None else None,
            }
            for stat in stat_names:
                vals = stats_dict.get(stat, ["", ""])
                record[stat] = vals[idx] if len(vals) > idx else ""
            rows.append(record)

    return rows


def save_rows(rows, output_path):
    """Write rows to a JSON file."""
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)
    print(f"\n{len(rows)} rows saved to {output_path}")
