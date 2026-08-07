"""Safe Telegram setup helpers. The bot token is never printed."""

import argparse
import os
from pathlib import Path

import requests
from dotenv import load_dotenv


def discover_chat(session=requests):
    load_dotenv(Path(__file__).parent / ".env")
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("TELEGRAM_BOT_TOKEN is not configured.")
        return 1
    response = session.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=15)
    response.raise_for_status()
    chats = {}
    for update in response.json().get("result", []):
        message = update.get("message") or update.get("channel_post") or {}
        chat = message.get("chat") or {}
        if chat.get("id") is not None:
            chats[str(chat["id"])] = chat.get("title") or chat.get("username") or chat.get("first_name") or "private chat"
    if not chats:
        print("No chat found. Send the configured bot a message, then run this command again.")
        return 2
    print("Candidate chat IDs (copy the intended one into TELEGRAM_CHAT_ID in .env):")
    for chat_id, label in chats.items():
        print(f"  {chat_id}  {label}")
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["discover-chat"])
    args = parser.parse_args()
    return discover_chat() if args.command == "discover-chat" else 1


if __name__ == "__main__":
    raise SystemExit(main())
