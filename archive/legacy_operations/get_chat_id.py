#!/usr/bin/env python3
"""
Get your Telegram chat ID for bot setup.

Usage:
1. Send a message to your bot first (e.g., /start)
2. Run: python get_chat_id.py
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

if not TOKEN:
    print("❌ Error: TELEGRAM_BOT_TOKEN not found in .env file")
    print("\nAdd it like this:")
    print("TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11")
    exit(1)

print("Fetching updates from your bot...\n")

url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
response = requests.get(url)

if response.status_code != 200:
    print(f"❌ Error: {response.status_code}")
    print(response.text)
    exit(1)

data = response.json()

if not data.get('ok'):
    print("❌ Error getting updates")
    print(data)
    exit(1)

results = data.get('result', [])

if not results:
    print("⚠️ No messages found!")
    print("\nMake sure you:")
    print("1. Started a chat with your bot")
    print("2. Sent at least one message (e.g., /start)")
    exit(1)

# Get unique chat IDs
chat_ids = set()
for update in results:
    if 'message' in update:
        chat_id = update['message']['chat']['id']
        username = update['message']['chat'].get('username', 'unknown')
        first_name = update['message']['chat'].get('first_name', '')
        chat_ids.add((chat_id, username, first_name))

print("✅ Found chat(s):\n")
for chat_id, username, first_name in chat_ids:
    print(f"Chat ID: {chat_id}")
    print(f"Username: @{username}" if username != 'unknown' else "Username: (none)")
    print(f"Name: {first_name}")
    print()

print("Add this to your .env file:")
print(f"TELEGRAM_CHAT_ID={list(chat_ids)[0][0]}")
