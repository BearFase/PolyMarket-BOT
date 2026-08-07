"""Probe #4: signature variants for query-string endpoints."""
import requests
from sync_positions_api import create_auth_headers

def us_get(sign_path, req_path, label):
    try:
        r = requests.get(f"https://api.polymarket.us{req_path}",
                         headers=create_auth_headers("GET", sign_path), timeout=12)
        print(f"\n=== {label} ===\nStatus: {r.status_code}")
        print(r.text[:300].encode('ascii','replace').decode())
    except Exception as e:
        print(f"\n=== {label} ===\nERROR: {e}")

# sign WITHOUT query, request WITH query
us_get("/v1/users/search", "/v1/users/search?q=Panthers3698", "users/search - sign bare path")
us_get("/v1/comments", "/v1/comments?limit=3", "comments - sign bare path")
us_get("/v1/social/users", "/v1/social/users?username=Panthers3698", "social/users - sign bare path")
