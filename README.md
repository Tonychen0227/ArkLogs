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
