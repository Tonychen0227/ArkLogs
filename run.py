import asyncio
import os
import sys
from datetime import datetime

from dotenv import load_dotenv
from playwright.async_api import async_playwright

from scraper import (
    login_to_bga,
    scrape_details_concurrent,
    build_rows,
    save_rows,
)


BGA_TABLE_URL = "https://boardgamearena.com/table?table={table_id}"


async def main():
    load_dotenv()

    bga_email = os.environ.get("BGA_EMAIL")
    bga_password = os.environ.get("BGA_PASSWORD")

    if not bga_email or not bga_password:
        print("Error: BGA_EMAIL and BGA_PASSWORD environment variables are required.")
        print("Copy .env.example to .env and fill in your credentials.")
        return

    if len(sys.argv) < 2:
        print("Usage: py run.py <table_id1,table_id2,...>")
        print("Example: py run.py 881267262,881234567")
        return

    raw = sys.argv[1]
    table_ids = [tid.strip() for tid in raw.split(",") if tid.strip()]

    if not table_ids:
        print("Error: No valid table IDs provided.")
        return

    # Validate that all IDs are numeric
    for tid in table_ids:
        if not tid.isdigit():
            print(f"Error: '{tid}' is not a valid numeric table ID.")
            return

    games = [{"href": BGA_TABLE_URL.format(table_id=tid)} for tid in table_ids]

    print(f"Scraping {len(games)} table(s): {', '.join(table_ids)}")

    start_time = datetime.now().strftime("%Y%m%d_%H%M%S")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, channel="chrome")
        context = await browser.new_context()
        page = await context.new_page()

        await login_to_bga(page, bga_email, bga_password)

        print(f"\nScraping game details for {len(games)} table(s) (5 tabs)...")
        all_details = await scrape_details_concurrent(context, games)
        rows = build_rows(all_details)

        if rows:
            output_path = f"tables_{start_time}.json"
            save_rows(rows, output_path)
        else:
            print("No data scraped.")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
