"""
System Integration Test - Verify all components are working
Run this to check that everything is properly configured
"""

import os
import sys
import json
from dotenv import load_dotenv

print("=" * 70)
print("POLYMARKET BOT - SYSTEM CHECK")
print("=" * 70)
print()

# Test 1: Environment variables
print("[Test 1] Checking environment variables...")
load_dotenv()

required_vars = ["POLYMARKET_API_KEY", "POLYMARKET_API_SECRET"]
optional_vars = ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]

all_good = True
for var in required_vars:
    value = os.getenv(var)
    if value:
        print(f"  [OK] {var}: {'*' * 20} (set)")
    else:
        print(f"  [FAIL] {var}: NOT SET")
        all_good = False

for var in optional_vars:
    value = os.getenv(var)
    if value:
        print(f"  [OK] {var}: {'*' * 20} (set)")
    else:
        print(f"  [-] {var}: Not set (optional)")

if not all_good:
    print("\n[FAILED] Missing required environment variables")
    print("Please check your .env file")
    sys.exit(1)

print()

# Test 2: File existence
print("[Test 2] Checking required files...")
required_files = [
    "sync_positions_api.py",
    "get_positions.py",
    "monitor_positions.py",
    "dashboard_live.html",
    "dashboard_server.py",
    "trader_dashboard.py",
    ".env"
]

for file in required_files:
    if os.path.exists(file):
        print(f"  [OK] {file}: Found")
    else:
        print(f"  [FAIL] {file}: NOT FOUND")
        all_good = False

if not all_good:
    print("\n[FAILED] Missing required files")
    sys.exit(1)

print()

# Test 3: Dependencies
print("[Test 3] Checking Python dependencies...")
try:
    import requests
    print("  [OK] requests: Installed")
except ImportError:
    print("  [FAIL] requests: NOT INSTALLED (pip install requests)")
    all_good = False

try:
    from cryptography.hazmat.primitives.asymmetric import ed25519
    print("  [OK] cryptography: Installed")
except ImportError:
    print("  [FAIL] cryptography: NOT INSTALLED (pip install cryptography)")
    all_good = False

try:
    from dotenv import load_dotenv
    print("  [OK] python-dotenv: Installed")
except ImportError:
    print("  [FAIL] python-dotenv: NOT INSTALLED (pip install python-dotenv)")
    all_good = False

try:
    import flask
    print("  [OK] Flask: Installed")
except ImportError:
    print("  [FAIL] Flask: NOT INSTALLED (pip install Flask)")
    all_good = False

if not all_good:
    print("\n[FAILED] Missing Python dependencies")
    print("Run: pip install -r requirements.txt")
    sys.exit(1)

print()

# Test 4: API Connection
print("[Test 4] Testing Polymarket API connection...")
try:
    import sync_positions_api
    api_data = sync_positions_api.fetch_positions_from_api()
    if api_data:
        positions_count = len(api_data.get("positions", {}))
        print(f"  [OK] API Connection: SUCCESS")
        print(f"  [OK] Open Positions: {positions_count}")
    else:
        print("  [FAIL] API Connection: No data returned")
        all_good = False
except Exception as e:
    print(f"  [FAIL] API Connection: FAILED")
    print(f"    Error: {str(e)[:100]}")
    all_good = False

print()

# Test 5: Position sync
print("[Test 5] Testing position sync...")
try:
    result = sync_positions_api.sync_positions()
    if result and os.path.exists("real_positions.json"):
        with open("real_positions.json", 'r', encoding='utf-8-sig') as f:
            data = json.load(f)
            print(f"  [OK] Sync: SUCCESS")
            print(f"  [OK] Positions synced: {len(data.get('positions', []))}")
            print(f"  [OK] Total P&L: ${data.get('total_pnl', 0):.2f}")
    else:
        print("  [FAIL] Sync: FAILED")
        all_good = False
except Exception as e:
    print(f"  [FAIL] Sync: FAILED")
    print(f"    Error: {str(e)[:100]}")
    all_good = False

print()

# Test 6: Monitor
print("[Test 6] Testing position monitor...")
try:
    import monitor_positions
    monitor_positions.monitor_positions()
    if os.path.exists("monitor_log.txt"):
        print(f"  [OK] Monitor: SUCCESS")
        print(f"  [OK] Log file: monitor_log.txt created")
    else:
        print("  [FAIL] Monitor: Log file not created")
        all_good = False
except Exception as e:
    print(f"  [FAIL] Monitor: FAILED")
    print(f"    Error: {str(e)[:100]}")
    all_good = False

print()

# Final summary
print("=" * 70)
if all_good:
    print("[SUCCESS] ALL SYSTEMS OPERATIONAL")
    print()
    print("Next steps:")
    print("  1. Open dashboard: .\\Open Dashboard.cmd")
    print("  2. View positions: python get_positions.py")
    print("  3. Set up monitoring: See DEPLOYMENT_CHECKLIST.md")
else:
    print("[FAILED] SOME TESTS FAILED")
    print()
    print("Please fix the issues above and run this test again")

print("=" * 70)
