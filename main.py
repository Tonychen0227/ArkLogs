import asyncio
import os
import sys
from datetime import datetime

from dotenv import load_dotenv
from playwright.async_api import async_playwright

from scraper import (
    login_to_bga,
    navigate_to_history,
    scrape_games,
    scrape_details_concurrent,
    build_rows,
    save_rows,
)


async def main():
    load_dotenv()

    bga_email = os.environ.get("BGA_EMAIL")
    bga_password = os.environ.get("BGA_PASSWORD")

    if not bga_email or not bga_password:
        print("Error: BGA_EMAIL and BGA_PASSWORD environment variables are required.")
        print("Copy .env.example to .env and fill in your credentials.")
        return

    # Player ID from command line
    if len(sys.argv) < 2:
        print("Usage: py main.py <player_id>")
        print("Example: py main.py 98142396")
        return
    player_id = sys.argv[1]
    start_time = datetime.now().strftime("%Y%m%d_%H%M%S")

    print(f"Launching Chrome for player {player_id}...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, channel="chrome")
        context = await browser.new_context()
        page = await context.new_page()

        await login_to_bga(page, bga_email, bga_password)
        await navigate_to_history(page, player_id)

        print("Scraping games...")
        games = await scrape_games(page)

        print(f"Found {len(games)} ranked games.")

        if games:
            print(f"\nScraping game details for {len(games)} games (5 tabs)...")
            all_details = await scrape_details_concurrent(context, games)
            rows = build_rows(all_details)
            if rows:
                output_path = f"{player_id}_{start_time}.json"
                save_rows(rows, output_path)

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
