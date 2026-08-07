import json

# Load the position data
with open('real_positions.json', 'r') as f:
    data = json.load(f)

# Fix the Argentina position interpretation
# Bear wants Argentina to WIN - he's told us this 5+ times
# The API labels are confusing but his screenshot + his words = truth

pos = data['positions'][0]
pos['outcome'] = 'YES - Argentina'
pos['side'] = 'LONG'
pos['bet_type'] = 'Betting Argentina WINS/ADVANCES'
pos['notes'] = 'Betting FOR Argentina/Messi to win the World Cup Final'

# If Argentina wins: gets $116.38 (his max profit shown in screenshot)
# If Spain wins: loses the $50 cost basis
pos['max_profit'] = 116.38 - 50.0  # Net profit
pos['max_loss'] = 50.0

# Save corrected data
with open('real_positions.json', 'w') as f:
    json.dump(data, f, indent=2)

print("FIXED: Argentina position - now shows betting FOR Argentina to WIN")
print(f"Cost: ${pos['cost_basis']:.2f}")
print(f"If Argentina wins: +${pos['max_profit']:.2f}")
print(f"If Spain wins: -${pos['max_loss']:.2f}")
