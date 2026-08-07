"""Archived MLB odds example; reads its key from the environment."""

import os

import requests
from dotenv import load_dotenv

load_dotenv()

ODDS_API_BASE = "https://api.the-odds-api.com/v4"
ODDS_API_KEY = os.getenv("ODDS_API_KEY")


def fetch_games():
    if not ODDS_API_KEY:
        raise RuntimeError("ODDS_API_KEY is not configured")
    response = requests.get(
        f"{ODDS_API_BASE}/sports/baseball_mlb/odds",
        params={"apiKey": ODDS_API_KEY, "regions": "us", "markets": "h2h"},
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


if __name__ == "__main__":
    print(f"Fetched {len(fetch_games())} archived MLB odds records.")
