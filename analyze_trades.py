"""
Analyze real trading performance from trades.csv
"""
import pandas as pd
from datetime import datetime

def analyze_real_trades(filepath: str = "trades.csv"):
    """Analyze actual trading performance."""
    
    df = pd.read_csv(filepath)
    
    print("=" * 60)
    print("📊 REAL TRADING PERFORMANCE ANALYSIS")
    print("=" * 60)
    
    # Basic stats
    total_trades = len(df)
    wins = len(df[df['outcome'] == 'WIN'])
    losses = len(df[df['outcome'] == 'LOSS'])
    win_rate = wins / total_trades * 100 if total_trades > 0 else 0
    
    print(f"\n📈 Trade Statistics:")
    print(f"   Total trades: {total_trades}")
    print(f"   Wins: {wins}")
    print(f"   Losses: {losses}")
    print(f"   Win rate: {win_rate:.1f}%")
    
    # Profit/Loss
    total_pnl = df['profit_loss'].sum()
    avg_win = df[df['outcome'] == 'WIN']['profit_loss'].mean() if wins > 0 else 0
    avg_loss = df[df['outcome'] == 'LOSS']['profit_loss'].mean() if losses > 0 else 0
    
    print(f"\n💰 Profit/Loss:")
    print(f"   Total P&L: ${total_pnl:.2f}")
    print(f"   Avg win: ${avg_win:.2f}")
    print(f"   Avg loss: ${avg_loss:.2f}")
    
    # Edge analysis
    avg_edge = df['edge'].mean() * 100
    avg_entry_odds = df['entry_odds'].mean()
    
    print(f"\n🎯 Edge Analysis:")
    print(f"   Avg claimed edge: {avg_edge:.2f}%")
    print(f"   Avg entry odds: {avg_entry_odds:.2f}")
    
    # Expected vs Actual
    # If edge claims are accurate, expected win rate ≈ fair_probability
    avg_fair_prob = df['fair_probability'].mean()
    expected_win_rate = avg_fair_prob * 100
    
    print(f"\n📉 Expected vs Actual:")
    print(f"   Expected win rate (from fair_prob): {expected_win_rate:.1f}%")
    print(f"   Actual win rate: {win_rate:.1f}%")
    print(f"   Difference: {win_rate - expected_win_rate:+.1f}%")
    
    # Side analysis
    print(f"\n🔄 By Side:")
    for side in ['UP', 'DOWN']:
        side_df = df[df['side'] == side]
        if len(side_df) > 0:
            side_wins = len(side_df[side_df['outcome'] == 'WIN'])
            side_wr = side_wins / len(side_df) * 100
            side_pnl = side_df['profit_loss'].sum()
            print(f"   {side}: {len(side_df)} trades, {side_wr:.1f}% win rate, ${side_pnl:.2f} P&L")
    
    # Streak analysis
    df['is_win'] = df['outcome'] == 'WIN'
    current_streak = 0
    max_win_streak = 0
    max_loss_streak = 0
    current_type = None
    
    for _, row in df.iterrows():
        if current_type == row['is_win']:
            current_streak += 1
        else:
            current_streak = 1
            current_type = row['is_win']
        
        if current_type:
            max_win_streak = max(max_win_streak, current_streak)
        else:
            max_loss_streak = max(max_loss_streak, current_streak)
    
    print(f"\n📊 Streaks:")
    print(f"   Max win streak: {max_win_streak}")
    print(f"   Max loss streak: {max_loss_streak}")
    
    # Drawdown
    df['cumulative_pnl'] = df['profit_loss'].cumsum()
    df['running_max'] = df['cumulative_pnl'].cummax()
    df['drawdown'] = df['running_max'] - df['cumulative_pnl']
    max_drawdown = df['drawdown'].max()
    
    print(f"\n📉 Risk Metrics:")
    print(f"   Max drawdown: ${max_drawdown:.2f}")
    
    # Current status
    final_balance = df['balance_after'].iloc[-1] if len(df) > 0 else 100
    starting_balance = 100.0  # Assumed
    total_return = (final_balance - starting_balance) / starting_balance * 100
    
    print(f"\n💼 Current Status:")
    print(f"   Final balance: ${final_balance:.2f}")
    print(f"   Total return: {total_return:+.1f}%")
    
    print("\n" + "=" * 60)
    
    # Warning if sample size is small
    if total_trades < 50:
        print(f"⚠️  WARNING: Only {total_trades} trades. Need 100+ for statistical significance.")
    
    if total_trades < 30:
        print(f"⚠️  With {total_trades} trades, win rate could easily be ±15% from true rate.")
    
    return df


if __name__ == "__main__":
    analyze_real_trades()