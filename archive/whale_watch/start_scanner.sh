#!/bin/bash
# Start Polymarket Trader Scanner (indexer + dashboard)
# Usage: bash start_scanner.sh

cd ~/.openclaw/workspace/projects/polymarket-bot

echo "Starting Trader Scanner System..."
echo ""

# Start indexer in background
echo "[1] Starting trader indexer (background)..."
nohup python trader_scanner.py > scanner_indexer.log 2>&1 &
INDEXER_PID=$!
echo "   ✓ Indexer PID: $INDEXER_PID"

sleep 2

# Start dashboard in background
echo "[2] Starting trader dashboard (background)..."
nohup python trader_dashboard.py > scanner_dashboard.log 2>&1 &
DASHBOARD_PID=$!
echo "   ✓ Dashboard PID: $DASHBOARD_PID"

echo ""
echo "========================================="
echo "✓ Trader Scanner is running!"
echo "========================================="
echo ""
echo "📊 Web Dashboard: http://127.0.0.1:5001/"
echo "   (Access from phone: http://<your-ip>:5001/)"
echo ""
echo "📝 Logs:"
echo "   Indexer:  tail -f scanner_indexer.log"
echo "   Dashboard: tail -f scanner_dashboard.log"
echo ""
echo "🛑 To stop: kill $INDEXER_PID $DASHBOARD_PID"
echo ""
