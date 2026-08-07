#!/usr/bin/env python3
"""Quick debug script to see what we're comparing"""

from sports_edge_finder import get_polymarket_futures, get_bookmaker_futures

pm = get_polymarket_futures()
wc_pm = [m for m in pm if "world cup" in m["question"].lower()]

print(f"\n=== Polymarket World Cup Markets ({len(wc_pm)}) ===\n")
for m in wc_pm[:5]:
    print(f"{m['question']}")
    if m['outcomePrices']:
        print(f"  Yes: {m['outcomePrices'][0]*100:.1f}%")
    print()

bm = get_bookmaker_futures("soccer_fifa_world_cup_winner")
print(f"\n=== Bookmaker Consensus ({len(bm)}) ===\n")
for b in bm[:10]:
    print(f"{b['team']}: {b['consensus_prob']*100:.1f}% (from {b['book_count']} books)")
