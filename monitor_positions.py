"""
Position Monitor - Alerts for significant P&L changes
Runs periodically to check for major movements in positions
"""

import os
import json
import time
import base64
import requests
from datetime import datetime
from dotenv import load_dotenv
from cryptography.hazmat.primitives.asymmetric import ed25519

load_dotenv()

API_KEY_ID = os.getenv("POLYMARKET_API_KEY")
API_SECRET = os.getenv("POLYMARKET_API_SECRET")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

MONITOR_LOG = "monitor_log.txt"
STATE_FILE = "monitor_state.json"
ALERT_THRESHOLD = 5.0  # Alert if P&L changes by more than 5%

def log_event(message):
    """Log monitoring events"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(MONITOR_LOG, 'a', encoding='utf-8') as f:
        f.write(f"[{timestamp}] {message}\n")
    print(f"[{timestamp}] {message}")

def create_auth_headers(method, path):
    """Create authenticated headers for Polymarket US API"""
    private_key_bytes = base64.b64decode(API_SECRET)[:32]
    private_key = ed25519.Ed25519PrivateKey.from_private_bytes(private_key_bytes)
    timestamp = str(int(time.time() * 1000))
    message = f"{timestamp}{method}{path}"
    signature = base64.b64encode(private_key.sign(message.encode())).decode()
    return {
        "X-PM-Access-Key": API_KEY_ID,
        "X-PM-Timestamp": timestamp,
        "X-PM-Signature": signature
    }

def fetch_positions_from_api():
    """Fetch current positions from Polymarket US API"""
    path = "/v1/portfolio/positions"
    url = f"https://api.polymarket.us{path}"
    headers = create_auth_headers("GET", path)
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"API error: {response.status_code} - {response.text[:200]}")

def load_previous_state():
    """Load previous monitoring state"""
    if not os.path.exists(STATE_FILE):
        return {}
    
    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {}

def save_state(state):
    """Save current monitoring state"""
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)

def send_telegram_alert(message):
    """Send alert to Telegram"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log_event("ALERT (Telegram not configured): " + message)
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": f"⚠️ POSITION ALERT\n\n{message}",
        "parse_mode": "HTML"
    }
    
    try:
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            log_event(f"Alert sent to Telegram: {message}")
        else:
            log_event(f"Failed to send Telegram alert: {response.status_code}")
    except Exception as e:
        log_event(f"Error sending Telegram alert: {e}")

def monitor_positions():
    """Main monitoring function"""
    log_event("=== Position Monitor Check ===")
    
    try:
        # Fetch current positions
        api_data = fetch_positions_from_api()
        positions_dict = api_data.get("positions", {})
        
        if not positions_dict:
            log_event("No open positions to monitor")
            return
        
        # Load previous state
        prev_state = load_previous_state()
        current_state = {}
        alerts = []
        
        for slug, pos in positions_dict.items():
            meta = pos.get("marketMetadata", {})
            market_title = meta.get("title", slug)
            net_pos = float(pos.get("netPositionDecimal", "0"))
            cost = float(pos.get("cost", {}).get("value", "0"))
            cash_value = float(pos.get("cashValue", {}).get("value", "0"))
            # cashValue is the stake valued at your team's current price, so this
            # holds for every position regardless of netPosition sign (see
            # sync_positions_api.parse_position for the exchange semantics).
            unrealized_pnl = cash_value - cost
            
            # Calculate P&L percentage
            pnl_percent = (unrealized_pnl / cost * 100) if cost > 0 else 0
            
            # Store current state
            current_state[slug] = {
                "market": market_title,
                "pnl": unrealized_pnl,
                "pnl_percent": pnl_percent,
                "cost": cost,
                "value": cash_value,
                "timestamp": datetime.now().isoformat()
            }
            
            # Check for significant changes
            if slug in prev_state:
                prev_pnl_percent = prev_state[slug].get("pnl_percent", 0)
                change = abs(pnl_percent - prev_pnl_percent)
                
                if change >= ALERT_THRESHOLD:
                    direction = "UP" if pnl_percent > prev_pnl_percent else "DOWN"
                    alerts.append({
                        "market": market_title,
                        "prev_pnl": prev_pnl_percent,
                        "current_pnl": pnl_percent,
                        "change": change,
                        "direction": direction,
                        "current_value": cash_value,
                        "unrealized_pnl": unrealized_pnl
                    })
            
            log_event(f"Position: {market_title} | P&L: ${unrealized_pnl:.2f} ({pnl_percent:+.2f}%)")
        
        # Send alerts if any
        if alerts:
            for alert in alerts:
                message = (
                    f"<b>{alert['market']}</b>\n"
                    f"P&L moved {alert['direction']}: {alert['prev_pnl']:+.2f}% → {alert['current_pnl']:+.2f}%\n"
                    f"Change: {alert['change']:.2f}%\n"
                    f"Current Value: ${alert['current_value']:.2f}\n"
                    f"Unrealized P&L: ${alert['unrealized_pnl']:+.2f}"
                )
                send_telegram_alert(message)
        else:
            log_event("No significant changes detected")
        
        # Save current state for next check
        save_state(current_state)
        log_event("=== Monitor Check Complete ===\n")
        
    except Exception as e:
        log_event(f"ERROR in monitoring: {e}")
        import traceback
        log_event(traceback.format_exc())

if __name__ == "__main__":
    monitor_positions()
