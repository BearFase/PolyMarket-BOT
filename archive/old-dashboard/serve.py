#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Combined server: Serves both static HTML and API endpoints
"""

import os
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse

# Add parent to path
sys.path.insert(0, '..')

# Import API handler
from api import DashboardAPI


class CombinedHandler(SimpleHTTPRequestHandler):
    """Serves static files AND API endpoints"""
    
    def __init__(self, *args, **kwargs):
        # Serve from dashboard directory
        super().__init__(*args, directory=os.path.dirname(__file__), **kwargs)
    
    def do_GET(self):
        """Route to API or static files"""
        parsed = urlparse(self.path)
        
        # API routes
        if parsed.path.startswith('/api/'):
            # Handle API inline
            from api import DashboardAPI
            api = DashboardAPI(self.request, self.client_address, self.server)
            api.path = self.path
            api.wfile = self.wfile
            api.send_response = self.send_response
            api.send_header = self.send_header
            api.end_headers = self.end_headers
            api.do_GET()
            return
        
        # Root -> index.html
        elif parsed.path == '/':
            self.path = '/index.html'
            return super().do_GET()
        
        # Static files
        else:
            return super().do_GET()
    
    def log_message(self, format, *args):
        """Custom logging"""
        if not self.path.startswith('/api/'):
            return  # Suppress static file logs
        print(f"[API] {self.path}")


def main():
    import argparse
    
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=8080, help='Port to run on')
    ap.add_argument('--wallet', type=str, help='Your Polymarket wallet address')
    args = ap.parse_args()
    
    # Set wallet in API module
    if args.wallet:
        import api
        api.USER_WALLET = args.wallet
        print(f"Tracking wallet: {args.wallet}\n")
    else:
        print("WARNING: No wallet provided - using demo data")
        print("   Run with --wallet 0xYourAddress to track real positions\n")
    
    server = HTTPServer(('localhost', args.port), CombinedHandler)
    
    print("="*60)
    print(f"POLYMARKET COMMAND CENTER")
    print("="*60)
    print(f"\nDashboard: http://localhost:{args.port}")
    print(f"API:       http://localhost:{args.port}/api/data")
    print(f"\nPress Ctrl+C to stop\n")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n\n👋 Shutting down...\n")
        server.shutdown()


if __name__ == '__main__':
    main()
