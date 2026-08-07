"""Archived API-configuration diagnostic with no embedded credentials."""

import os

from dotenv import load_dotenv

load_dotenv()

required = ("POLYMARKET_API_KEY", "POLYMARKET_API_SECRET", "POLYMARKET_WALLET")
missing = [name for name in required if not os.getenv(name)]

if missing:
    print("Missing required environment variables: " + ", ".join(missing))
else:
    print("Polymarket environment variables are configured.")
    print("Values are intentionally not displayed by this archived diagnostic.")
