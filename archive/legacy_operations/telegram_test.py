#!/usr/bin/env python3
"""
Test Telegram bot setup.

Usage: python telegram_test.py
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

if not TOKEN:
    print("❌ Error: TELEGRAM_BOT_TOKEN not found in .env")
    exit(1)

if not CHAT_ID:
    print("❌ Error: TELEGRAM_CHAT_ID not found in .env")
    exit(1)

print(f"Sending test message to chat {CHAT_ID}...\n")

url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
data = {
    "chat_id": CHAT_ID,
    "text": "🤖 Polymarket Bot is online!\n\nYour Telegram notifications are working.",
    "parse_mode": "Markdown"
}

response = requests.post(url, json=data)

if response.status_code == 200:
    print("✅ Success! Check your Telegram for the test message.")
else:
    print(f"❌ Error: {response.status_code}")
    print(response.text)
