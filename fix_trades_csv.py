"""
Script to fix the balance_before/balance_after columns in trades.csv

The issue was that balance tracking was inconsistent when trades overlapped.
This script recalculates the correct sequential balance chain based on
resolution order (which is the CSV row order).
"""

import csv
import os
import shutil
from datetime import datetime

# Configuration
TRADES_FILE = "trades.csv"
BACKUP_FILE = "trades_backup.csv"

def fix_trades_csv():
    """Fix the balance columns in trades.csv"""
    
    # Check if file exists
    if not os.path.exists(TRADES_FILE):
        print(f"❌ File not found: {TRADES_FILE}")
        return
    
    # Create backup
    shutil.copy(TRADES_FILE, BACKUP_FILE)
    print(f"📦 Created backup: {BACKUP_FILE}")
    
    # Read all trades
    trades = []
    with open(TRADES_FILE, 'r') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            trades.append(row)
    
    if not trades:
        print("❌ No trades found in file")
        return
    
    print(f"📊 Found {len(trades)} trades")
    
    # Get starting balance from first trade's balance_before
    # (This is the best estimate we have of the starting balance)
    starting_balance = float(trades[0]['balance_before'])
    print(f"💰 Starting balance: ${starting_balance:.2f}")
    
    # Recalculate balances sequentially
    current_balance = starting_balance
    
    for i, trade in enumerate(trades):
        # Set balance_before
        trade['balance_before'] = f"{current_balance:.2f}"
        
        # Calculate profit/loss
        outcome = trade['outcome']
        bet_size = float(trade['bet_size'])
        payout = float(trade['payout'])
        
        if outcome == "WIN":
            profit = payout - bet_size
        else:  # LOSS or UNKNOWN
            profit = -bet_size
        
        # Update profit_loss column to ensure consistency
        trade['profit_loss'] = f"{profit:.2f}"
        
        # Update balance
        current_balance += profit
        trade['balance_after'] = f"{current_balance:.2f}"
        
        print(f"  Trade {i+1}: {outcome} | Bet: ${bet_size:.2f} | P/L: ${profit:+.2f} | Balance: ${current_balance:.2f}")
    
    # Write fixed trades back
    with open(TRADES_FILE, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(trades)
    
    print(f"\n✅ Fixed {TRADES_FILE}")
    print(f"   Final balance: ${current_balance:.2f}")
    
    # Calculate summary stats
    wins = sum(1 for t in trades if t['outcome'] == 'WIN')
    losses = sum(1 for t in trades if t['outcome'] == 'LOSS')
    total_pnl = current_balance - starting_balance
    
    print(f"\n📈 Summary:")
    print(f"   Total trades: {len(trades)}")
    print(f"   Wins: {wins} ({100*wins/len(trades):.1f}%)")
    print(f"   Losses: {losses} ({100*losses/len(trades):.1f}%)")
    print(f"   Total P&L: ${total_pnl:+.2f}")


if __name__ == "__main__":
    fix_trades_csv()
