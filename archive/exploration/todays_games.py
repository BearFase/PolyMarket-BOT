#!/usr/bin/env python3
"""
Check for value bets on games happening TODAY
Runs more frequently than the daily futures check
"""

import requests
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

# Load .env
env_file = Path(__file__).parent / ".env"
if env_file.exists():
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, val = line.split('=', 1)
                os.environ[key.strip()] = val.strip()

ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")
ODDS_API_BASE = "https://api.the-odds-api.com/v4"

# Sports to check for same-day games
SPORTS = ["baseball_mlb", "basketball_nba", "americanfootball_nfl"]


def get_todays_games():
    """Get games happening in the next 12 hours"""
    if not ODDS_API_KEY:
        print("ERROR: No ODDS_API_KEY")
        return []
    
    now = datetime.now()
    cutoff = now + timedelta(hours=12)
    
    all_games = []
    
    for sport in SPORTS:
        try:
            r = requests.get(
                f"{ODDS_API_BASE}/sports/{sport}/odds",
                params={
                    "apiKey": ODDS_API_KEY,
                    "regions": "us",
                    "markets": "h2h",
                    "oddsFormat": "american"
                },
                timeout=10
            )
            
            if r.status_code != 200:
                continue
            
            games = r.json()
            
            for game in games:
                # Parse game time
                try:
                    game_time = datetime.fromisoformat(game.get("commence_time", "").replace('Z', '+00:00'))
                    
                    # Only include games in next 12 hours
                    if game_time > cutoff:
                        continue
                    
                except:
                    continue
                
                # Calculate consensus odds
                home_team = game.get("home_team", "")
                away_team = game.get("away_team", "")
                
                home_odds = []
                away_odds = []
                
                for book in game.get("bookmakers", []):
                    for market in book.get("markets", []):
                        if market.get("key") == "h2h":
                            for outcome in market.get("outcomes", []):
                                odds = int(outcome.get("price", 0))
                                if outcome.get("name") == home_team:
                                    home_odds.append(odds)
                                elif outcome.get("name") == away_team:
                                    away_odds.append(odds)
                
                if home_odds and away_odds:
                    avg_home = sum(home_odds) / len(home_odds)
                    avg_away = sum(away_odds) / len(away_odds)
                    
                    # Convert American odds to implied probability
                    def american_to_prob(odds):
                        if odds > 0:
                            return 100 / (odds + 100)
                        else:
                            return -odds / (-odds + 100)
                    
                    home_prob = american_to_prob(avg_home)
                    away_prob = american_to_prob(avg_away)
                    
                    all_games.append({
                        "sport": sport,
                        "home_team": home_team,
                        "away_team": away_team,
                        "commence_time": game_time.isoformat(),
                        "home_odds": round(avg_home),
                        "away_odds": round(avg_away),
                        "home_prob": round(home_prob * 100, 1),
                        "away_prob": round(away_prob * 100, 1),
                        "books_count": len(home_odds)
                    })
        
        except Exception as e:
            print(f"Error fetching {sport}: {e}")
            continue
    
    return all_games


def main():
    print(f"\n=== Today's Games Check - {datetime.now():%Y-%m-%d %H:%M} ===\n")
    
    games = get_todays_games()
    
    if not games:
        print("No games in next 12 hours")
        return
    
    print(f"Found {len(games)} game(s):\n")
    
    for g in games:
        game_time = datetime.fromisoformat(g["commence_time"])
        print(f"{g['away_team']} @ {g['home_team']}")
        print(f"  Time: {game_time:%I:%M %p}")
        print(f"  Odds: {g['away_team']} {g['away_odds']:+d} ({g['away_prob']}%) | {g['home_team']} {g['home_odds']:+d} ({g['home_prob']}%)")
        print(f"  Books: {g['books_count']}")
        print()
    
    # Save to JSON
    with open("todays_games.json", "w") as f:
        json.dump({
            "last_updated": datetime.now().isoformat(),
            "games": games
        }, f, indent=2)
    
    print("Saved to todays_games.json")


if __name__ == "__main__":
    main()
