"""Batch task script: scrape BGA tables and publish directly to BigQuery.

Usage:
    python run_batch.py <table_id1,table_id2,...>

Requires:
    - BGA_EMAIL / BGA_PASSWORD env vars (or .env file)
    - GOOGLE_APPLICATION_CREDENTIALS env var pointing to SA key JSON
"""

import asyncio
import json
import os
import sys
from datetime import datetime

from dotenv import load_dotenv
from google.cloud import bigquery
from playwright.async_api import async_playwright

from scraper import (
    login_to_bga,
    scrape_details_concurrent,
    build_rows,
)
from transform import transform_row


BGA_TABLE_URL = "https://boardgamearena.com/table?table={table_id}"
BQ_PROJECT = "fut-macro"
BQ_TABLE = "fut-macro.ark_nova.games"


def upload_to_bigquery(rows):
    """Upload transformed rows to BigQuery via a load job."""
    client = bigquery.Client(project=BQ_PROJECT)

    # Write NDJSON
    tmp_path = f"_upload_{os.getpid()}.jsonl"
    with open(tmp_path, "w") as f:
        for r in rows:
            clean = {}
            for k, v in r.items():
                if isinstance(v, float) and (v != v):  # NaN
                    clean[k] = None
                else:
                    clean[k] = v
            f.write(json.dumps(clean, default=str) + "\n")

    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
    )

    with open(tmp_path, "rb") as f:
        job = client.load_table_from_file(f, BQ_TABLE, job_config=job_config)

    job.result()
    os.remove(tmp_path)
    return job.output_rows


async def main():
    load_dotenv()

    bga_email = os.environ.get("BGA_EMAIL")
    bga_password = os.environ.get("BGA_PASSWORD")

    if not bga_email or not bga_password:
        print("Error: BGA_EMAIL and BGA_PASSWORD environment variables are required.")
        return

    if len(sys.argv) < 2:
        print("Usage: python run_batch.py <table_id1,table_id2,...>")
        return

    raw = sys.argv[1]
    table_ids = [tid.strip() for tid in raw.split(",") if tid.strip()]

    if not table_ids:
        print("Error: No valid table IDs provided.")
        return

    for tid in table_ids:
        if not tid.isdigit():
            print(f"Error: '{tid}' is not a valid numeric table ID.")
            return

    games = [{"href": BGA_TABLE_URL.format(table_id=tid)} for tid in table_ids]

    print(f"Scraping {len(games)} table(s)")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        await login_to_bga(page, bga_email, bga_password)

        # Warmup: load first game sequentially to prime the connection
        print("Warming up connection...")
        await page.goto(games[0]["href"], wait_until="domcontentloaded", timeout=30000)
        await page.close()

        print(f"Scraping game details ({len(games)} tables, 5 concurrent tabs)...")
        all_details = await scrape_details_concurrent(context, games)
        raw_rows = build_rows(all_details)

        await browser.close()

    if not raw_rows:
        print("No data scraped.")
        return

    print(f"Scraped {len(raw_rows)} rows, transforming...")
    transformed = []
    for r in raw_rows:
        t = transform_row(r)
        if t is not None:
            transformed.append(t)

    print(f"Transformed {len(transformed)} rows, uploading to BigQuery...")
    count = upload_to_bigquery(transformed)
    print(f"Uploaded {count} rows to {BQ_TABLE}")


if __name__ == "__main__":
    asyncio.run(main())
