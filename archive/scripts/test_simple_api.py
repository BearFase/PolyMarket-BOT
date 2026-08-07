"""Archived public API probe with optional wallet from the environment."""

import os

import requests
from dotenv import load_dotenv

load_dotenv()

response = requests.get(
    "https://gamma-api.polymarket.com/markets", params={"limit": 5}, timeout=15
)
response.raise_for_status()
print(f"Public API returned {len(response.json())} markets.")

wallet = os.getenv("POLYMARKET_WALLET")
if wallet:
    positions = requests.get(
        "https://gamma-api.polymarket.com/positions",
        params={"user": wallet},
        timeout=15,
    )
    print(f"Wallet-position request status: {positions.status_code}")
else:
    print("POLYMARKET_WALLET is not configured; wallet probe skipped.")
