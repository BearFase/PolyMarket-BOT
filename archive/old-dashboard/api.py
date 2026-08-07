#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Polymarket Dashboard API

Simple HTTP server that provides data to the dashboard.
"""

import json
import os
import sys
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import requests

# Add parent dir to path to import our modules
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from polymarket_consensus_v2 import get_alltime_top, last_trade_ts, open_positions as get_open_positions

GAMMA_API = "https://gamma-api.polymarket.com"
DATA_API = "https://data-api.polymarket.com"

# TODO: Set your Polymarket wallet address here
USER_WALLET = None  # "0xYourWalletAddressHere"


class DashboardAPI(BaseHTTPRequestHandler):
    def do_GET(self):
        """Handle GET requests"""
        parsed = urlparse(self.path)
        
        # CORS headers
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        
        if parsed.path == '/api/data':
            data = self.get_dashboard_data()
            self.wfile.write(json.dumps(data).encode())
        
        elif parsed.path == '/api/whale-signals':
            signals = self.get_whale_signals()
            self.wfile.write(json.dumps(signals).encode())
        
        elif parsed.path == '/api/paper-trading':
            paper = self.get_paper_trading_data()
            self.wfile.write(json.dumps(paper).encode())
        
        else:
            self.wfile.write(json.dumps({"error": "Not found"}).encode())
    
    def get_dashboard_data(self):
        """Get all dashboard data"""
        try:
            positions = self.get_user_positions()
            live_game = self.get_live_game(positions)
            whale_signals = self.get_whale_signals()
            hot_markets = self.get_hot_markets()
            
            total_pnl = sum(p.get('pnl_dollars', 0) for p in positions)
            
            return {
                'total_pnl': total_pnl,
                'positions': positions,
                'live_game': live_game,
                'whale_signals': whale_signals,
                'hot_markets': hot_markets,
                'timestamp': time.time()
            }
        except Exception as e:
            print(f"Error fetching dashboard data: {e}")
            return {
                'total_pnl': 0,
                'positions': [],
                'live_game': None,
                'whale_signals': [],
                'hot_markets': [],
                'error': str(e)
            }
    
    def get_user_positions(self):
        """Get user's open positions"""
        if not USER_WALLET:
            # Return mock data for demo
            return [{
                'market': 'England vs Argentina - World Cup Semifinal',
                'outcome': 'Argentina Win',
                'size': 10,
                'entry_price': 0.55,
                'current_price': 0.99,
                'pnl': 80,
                'pnl_dollars': 8,
                'condition_id': 'mock',
                'url': 'https://polymarket.com'
            }]
        
        try:
            r = requests.get(
                f"{DATA_API}/positions",
                params={'user': USER_WALLET, 'sortBy': 'CURRENT', 'limit': 50},
                timeout=10
            )
            
            if r.status_code != 200:
                return []
            
            positions = r.json()
            formatted = []
            
            for p in positions:
                if p.get('redeemable'):
                    continue
                
                entry = float(p.get('avgPrice') or 0)
                current = float(p.get('curPrice') or 0)
                value = float(p.get('currentValue') or 0)
                
                if value < 1:
                    continue
                
                pnl_pct = ((current - entry) / entry * 100) if entry > 0 else 0
                pnl_dollars = value * (current - entry) / current if current > 0 else 0
                
                formatted.append({
                    'market': p.get('title', '?'),
                    'outcome': p.get('outcome', '?'),
                    'size': value / current if current > 0 else value,
                    'entry_price': entry,
                    'current_price': current,
                    'pnl': pnl_pct,
                    'pnl_dollars': pnl_dollars,
                    'condition_id': p.get('conditionId'),
                    'url': f"https://polymarket.com/event/{p.get('eventSlug', '')}"
                })
            
            return formatted
        
        except Exception as e:
            print(f"Error fetching positions: {e}")
            return []
    
    def get_live_game(self, positions):
        """Get most recent/active position as 'live game'"""
        if not positions:
            return None
        
        # For now, just return the first position
        # TODO: Add logic to detect truly "live" games (e.g., ending soon)
        p = positions[0]
        
        return {
            'title': p['market'],
            'status': 'LIVE' if p['current_price'] < 0.95 else 'FINAL',
            'your_outcome': p['outcome'],
            'size': p['size'],
            'entry_price': p['entry_price'],
            'current_value': p['size'] * p['current_price'],
            'pnl': p['pnl'],
            'url': p['url'],
            'odds': [
                {
                    'outcome': p['outcome'],
                    'price': p['current_price'],
                    'change': (p['current_price'] - p['entry_price']) * 100
                },
                {
                    'outcome': 'Other',
                    'price': 1 - p['current_price'],
                    'change': -(p['current_price'] - p['entry_price']) * 100
                }
            ]
        }
    
    def get_whale_signals(self):
        """Get whale consensus signals and active whale data"""
        try:
            # Read whale data file
            whale_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'whale_data.json')
            
            whale_data = {}
            if os.path.exists(whale_file):
                with open(whale_file, 'r') as f:
                    whale_data = json.load(f)
            
            # Also read sports edges
            sports_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'sports_edges.json')
            if os.path.exists(sports_file):
                with open(sports_file, 'r') as f:
                    sports_data = json.load(f)
                    whale_data['sports_edges'] = sports_data.get('edges', [])
                    whale_data['sports_last_updated'] = sports_data.get('last_updated', '')
            
            return whale_data if whale_data else {'active_whales': [], 'consensus': {'found': False}, 'sports_edges': []}
        
        except Exception as e:
            print(f"Error fetching whale signals: {e}")
            return {'active_whales': [], 'consensus': {'found': False}, 'error': str(e)}
    
    def get_hot_markets(self):
        """Get trending markets by volume"""
        try:
            r = requests.get(
                f"{GAMMA_API}/markets",
                params={'limit': 10, 'closed': 'false'},
                timeout=10
            )
            
            if r.status_code != 200:
                return []
            
            markets = r.json()
            hot = []
            
            for m in markets[:10]:
                volume = float(m.get('volume', 0))
                if volume < 100000:  # Skip low-volume markets
                    continue
                
                # Get Yes price
                tokens = m.get('tokens', [])
                yes_price = 0.5
                if tokens:
                    for token in tokens:
                        if token.get('outcome') == 'Yes':
                            yes_price = float(token.get('price', 0.5))
                            break
                
                hot.append({
                    'question': m.get('question', '?'),
                    'yes_price': yes_price,
                    'volume': volume,
                    'url': f"https://polymarket.com/event/{m.get('slug', '')}"
                })
            
            # Sort by volume
            hot.sort(key=lambda x: -x['volume'])
            
            return hot[:5]
        
        except Exception as e:
            print(f"Error fetching hot markets: {e}")
            return []
    
    def get_paper_trading_data(self):
        """Get paper trading stats and positions"""
        try:
            paper_state_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'paper_state.json')
            paper_config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'paper_config.json')
            
            if not os.path.exists(paper_state_path):
                return {
                    'enabled': False,
                    'positions': [],
                    'stats': {}
                }
            
            with open(paper_state_path, 'r') as f:
                state = json.load(f)
            
            config = {}
            if os.path.exists(paper_config_path):
                with open(paper_config_path, 'r') as f:
                    config = json.load(f)
            
            # Calculate stats
            total_pnl = state.get('total_pnl', 0)
            positions = state.get('positions', [])
            history = state.get('history', [])
            
            open_pnl = sum(p.get('unrealized_pnl', 0) for p in positions)
            
            wins = sum(1 for t in history if t.get('realized_pnl', 0) > 0)
            win_rate = (wins / len(history) * 100) if history else 0
            
            return {
                'enabled': config.get('auto_trade', False),
                'last_check': state.get('last_check'),
                'stats': {
                    'total_pnl': total_pnl,
                    'open_pnl': open_pnl,
                    'total_trades': len(history),
                    'open_positions': len(positions),
                    'win_rate': win_rate,
                    'exposure': sum(p.get('size', 0) for p in positions),
                    'max_exposure': config.get('max_total_exposure', 500)
                },
                'positions': positions,
                'recent_history': history[-5:] if history else []
            }
        
        except Exception as e:
            print(f"Error fetching paper trading data: {e}")
            return {'enabled': False, 'positions': [], 'stats': {}, 'error': str(e)}
    
    def log_message(self, format, *args):
        """Suppress default logging"""
        pass


def run_server(port=8080):
    """Start the API server"""
    server = HTTPServer(('localhost', port), DashboardAPI)
    print(f"\n🚀 Dashboard API running on http://localhost:{port}")
    print(f"📊 Open dashboard: http://localhost:{port}/index.html")
    print(f"\nPress Ctrl+C to stop\n")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n\nShutting down...")
        server.shutdown()


if __name__ == '__main__':
    import argparse
    
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=8080, help='Port to run server on')
    ap.add_argument('--wallet', type=str, help='Your Polymarket wallet address')
    args = ap.parse_args()
    
    if args.wallet:
        USER_WALLET = args.wallet
        print(f"Tracking wallet: {USER_WALLET}")
    else:
        print("⚠️  No wallet set - using demo data")
        print("   Run with --wallet 0xYourAddress to track real positions\n")
    
    run_server(args.port)
