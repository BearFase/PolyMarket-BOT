# Telegram setup

Telegram is optional. The NFL research workflow continues when Telegram is
unconfigured or temporarily unavailable.

1. Create a bot with `@BotFather` and place the token in local `.env`:

   ```text
   TELEGRAM_BOT_TOKEN=your-token
   ```

2. Send the bot a message, then discover the chat without printing the token:

   ```powershell
   python telegram_setup.py discover-chat
   ```

3. Add the selected ID to `.env`:

   ```text
   TELEGRAM_CHAT_ID=your-chat-id
   ```

4. Preview messages without sending or journaling:

   ```powershell
   python telegram_notification_center.py morning --preview
   python telegram_notification_center.py pregame --due --preview
   python telegram_notification_center.py finals --due --preview
   python telegram_notification_center.py warnings --preview
   ```

Production sends are performed by `nfl_daily_update.py`. Delivery attempts are
append-only in the production registry and deduplicated by report date, game,
research revision, or warning cooldown. Credentials stay only in `.env`.
