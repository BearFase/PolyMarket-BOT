#!/usr/bin/env python3
"""Test the matching logic"""

from sports_edge_finder import get_polymarket_futures, get_bookmaker_futures, match_and_compare

pm = get_polymarket_futures()
wc_pm = [m for m in pm if "world cup" in m["question"].lower()]

bm = get_bookmaker_futures("soccer_fifa_world_cup_winner")

print("\n=== Testing Match Logic ===\n")

for pm_market in wc_pm:
    print(f"PM: {pm_market['question']}")
    print(f"    Outcomes: {pm_market['outcomes']}")
    print(f"    Prices: {pm_market['outcomePrices']}")
    
    question = pm_market["question"].lower()
    
    for cons in bm:
        team = cons["team"].lower()
        if team in question:
            print(f"    MATCH FOUND: {cons['team']}")
            print(f"      PM prob: {pm_market['outcomePrices'][0]*100:.1f}%")
            print(f"      BM prob: {cons['consensus_prob']*100:.1f}%")
            
            pm_prob = pm_market['outcomePrices'][0]
            bm_prob = cons['consensus_prob']
            edge = bm_prob - pm_prob
            edge_pct = (edge / pm_prob * 100) if pm_prob > 0 else 0
            print(f"      Edge: {edge_pct:+.1f}%")
    
    print()
