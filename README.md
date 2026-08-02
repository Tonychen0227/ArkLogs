# Ark Nova BGA Logs Downloader

Playwright script that logs into [Board Game Arena](https://en.boardgamearena.com/) using Chrome.

## Setup

1. Install dependencies:

   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```

2. Copy the environment file and fill in your BGA credentials:

   ```bash
   cp .env.example .env
   # Edit .env with your email and password
   ```

3. Run:

   ```bash
   python main.py
   ```

The script will launch Chrome, log in to BGA with your credentials, and exit once login is complete.

## Azure Batch Pool

The scraper pool uses Ubuntu 22.04 on one dedicated `Standard_D2as_v6` node with one task slot.
This x86 SKU provides 2 vCPUs and 8 GiB RAM, giving Chromium and Playwright more headroom than the prior `Standard_A1_v2` (1 vCPU, 2 GiB RAM). `Standard_B2ps_v2` was evaluated but rejected by the Batch service for this pool; `Standard_D2as_v6` is the compatible replacement.

As of 2026-08-02, East US Linux retail pricing is $0.0908 per hour for a dedicated `Standard_D2as_v6` node, approximately $2.18 per day or $66.28 per 730-hour month. Low-priority pricing is $0.0182 per hour, but those nodes can be evicted and are not used until task retry handling is robust.

The pool intentionally remains at one node and one task slot: the scraper uses a random VPN endpoint, and the current reliability work favors a single controlled session over parallel VPN exits. Increase node count only after validating task-level retries and recovery.
