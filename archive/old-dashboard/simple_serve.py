#!/usr/bin/env python3
"""Simple Flask-style server for dashboard"""

from http.server import HTTPServer, SimpleHTTPRequestHandler
import json
import os

def load_paper_state():
    """Load paper trading state"""
    state_file = os.path.join(os.path.dirname(__file__), '..', 'paper_state.json')
    if os.path.exists(state_file):
        with open(state_file, 'r') as f:
            return json.load(f)
    return {"positions": [], "history": [], "total_pnl": 0}

def load_whale_data():
    """Load whale data"""
    whale_file = os.path.join(os.path.dirname(__file__), '..', 'whale_data.json')
    if os.path.exists(whale_file):
        with open(whale_file, 'r') as f:
            return json.load(f)
    return {"active_whales": [], "consensus": {"found": False}}

def load_sports_edges():
    """Load sports edges"""
    sports_file = os.path.join(os.path.dirname(__file__), '..', 'sports_edges.json')
    if os.path.exists(sports_file):
        with open(sports_file, 'r') as f:
            return json.load(f)
    return {"edges": []}

class DashboardHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/api/data':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            
            # Return minimal data for main dashboard  
            try:
                whale_data = load_whale_data()
            except:
                whale_data = {'active_whales': []}
                
            data = {
                'total_pnl': 0,
                'positions': [],
                'live_game': None,
                'whale_signals': whale_data,
                'hot_markets': []
            }
            self.wfile.write(json.dumps(data).encode())
            
        elif self.path == '/api/paper-trading':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            
            state = load_paper_state()
            
            # Format for dashboard HTML
            positions = state.get('positions', [])
            history = state.get('history', [])
            total_pnl = state.get('total_pnl', 0)
            total_exposure = state.get('total_exposure', 0)
            
            # Calculate stats
            open_pnl = sum(p.get('unrealized_pnl', 0) for p in positions)
            wins = sum(1 for t in history if t.get('realized_pnl', 0) > 0)
            win_rate = (wins / len(history) * 100) if history else 0
            
            data = {
                'enabled': False,
                'stats': {
                    'total_pnl': total_pnl,
                    'open_pnl': open_pnl,
                    'total_trades': len(history),
                    'open_positions': len(positions),
                    'win_rate': win_rate,
                    'exposure': total_exposure,
                    'max_exposure': 500
                },
                'positions': positions,
                'recent_history': history[-5:] if history else []
            }
            
            self.wfile.write(json.dumps(data).encode())
            
        elif self.path == '/api/whale-signals':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            
            data = load_whale_data()
            self.wfile.write(json.dumps(data).encode())
            
        elif self.path == '/api/sports-edges':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            
            data = load_sports_edges()
            self.wfile.write(json.dumps(data).encode())
            
        elif self.path == '/api/todays-games':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            
            games_file = os.path.join(os.path.dirname(__file__), '..', 'todays_games.json')
            if os.path.exists(games_file):
                with open(games_file, 'r') as f:
                    data = json.load(f)
            else:
                data = {'games': []}
            self.wfile.write(json.dumps(data).encode())
            
        elif self.path == '/' or self.path == '/index.html':
            self.path = '/index.html'
            return SimpleHTTPRequestHandler.do_GET(self)
            
        else:
            return SimpleHTTPRequestHandler.do_GET(self)
    
    def log_message(self, format, *args):
        # Suppress log spam
        pass

if __name__ == '__main__':
    os.chdir(os.path.dirname(__file__))
    server = HTTPServer(('localhost', 8081), DashboardHandler)
    print(f"\nPolymarket Dashboard: http://localhost:8081\n")
    server.serve_forever()
