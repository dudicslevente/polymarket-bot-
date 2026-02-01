import csv

# Read the trades
with open('trades.csv', 'r') as f:
    reader = csv.DictReader(f)
    trades = list(reader)
    fieldnames = reader.fieldnames

# Starting balance
balance = 100.0

# Fix each trade sequentially
for trade in trades:
    bet_size = float(trade['bet_size'])
    outcome = trade['outcome']
    entry_odds = float(trade['entry_odds'])
    
    # Set balance_before to current balance
    trade['balance_before'] = f'{balance:.2f}'
    
    # Calculate balance_after based on outcome
    if outcome == 'WIN':
        payout = (bet_size / entry_odds) * (1 - 0.01)
        new_balance = balance - bet_size + payout
        profit = payout - bet_size
        trade['payout'] = f'{payout:.2f}'
        trade['profit_loss'] = f'{profit:.2f}'
    else:
        new_balance = balance - bet_size
        trade['payout'] = '0.00'
        trade['profit_loss'] = f'{-bet_size:.2f}'
    
    trade['balance_after'] = f'{new_balance:.2f}'
    balance = new_balance

print(f'Final balance: ${balance:.2f}')
print(f'Total trades processed: {len(trades)}')

# Write the corrected CSV
with open('trades.csv', 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(trades)

print('trades.csv has been corrected!')
print()
print('Last 5 trades:')
for i, t in enumerate(trades[-5:], len(trades)-4):
    print(f'  #{i}: {t["outcome"]}: before={t["balance_before"]}, after={t["balance_after"]}, bet={t["bet_size"]}')
