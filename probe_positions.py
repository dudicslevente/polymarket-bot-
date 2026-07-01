#!/usr/bin/env python3
"""
READ-ONLY diagnostic. Dumps raw position data from the Polymarket data-api
so we can see exactly how winning/redeemable positions are represented —
especially for neg-risk (BTC Up/Down) markets.

No private keys, no transactions, no writes. Safe to run anytime.
"""
import os
import sys
import json
from dotenv import load_dotenv
import requests

load_dotenv()

WALLET_ADDRESS = os.getenv("WALLET_ADDRESS")
if not WALLET_ADDRESS:
    print("❌ WALLET_ADDRESS not set in .env")
    sys.exit(1)

# Some accounts trade via a proxy/safe address funded by Polymarket.
# Add POLYMARKET_FUNDER_ADDRESS to .env if your trades settle there.
ADDRESSES = [WALLET_ADDRESS]
funder = os.getenv("POLYMARKET_FUNDER_ADDRESS")
if funder:
    ADDRESSES.append(funder)

URL = "https://data-api.polymarket.com/positions"

all_positions = []
for addr in ADDRESSES:
    try:
        r = requests.get(URL, params={"user": addr.lower()}, timeout=30)
        r.raise_for_status()
        data = r.json()
        items = data if isinstance(data, list) else data.get("positions", [])
        all_positions.extend(items)
        print(f"📡 {addr[:10]}...: {len(items)} positions")
    except Exception as e:
        print(f"❌ {addr[:10]}...: {e}")

print(f"\nTotal raw positions: {len(all_positions)}")

# Classify using EVERY plausible signal so we can see which one matches reality
def classify(p):
    cur = float(p.get("curPrice") or 0)
    size = float(p.get("size") or 0)
    redeemable = bool(p.get("redeemable"))
    neg_risk = bool(p.get("negativeRisk"))
    cash_pnl = float(p.get("cashPnl") or 0)
    return cur, size, redeemable, neg_risk, cash_pnl

# Buckets: try multiple definitions of "winning/redeemable"
redeemable_flag = []        # redeemable == True
cur_price_one = []          # curPrice == 1.0
cur_price_high = []         # curPrice >= 0.99
positive_pnl = []           # cashPnl > 0
neg_risk_any = []           # negativeRisk == True (regardless of state)

for p in all_positions:
    cur, size, redeemable, neg_risk, cash_pnl = classify(p)
    if redeemable: redeemable_flag.append(p)
    if cur == 1.0: cur_price_one.append(p)
    if cur >= 0.99: cur_price_high.append(p)
    if cash_pnl > 0: positive_pnl.append(p)
    if neg_risk: neg_risk_any.append(p)

print("\n" + "="*60)
print("CLASSIFICATION (how many positions match each predicate)")
print("="*60)
print(f"  redeemable == True        : {len(redeemable_flag)}")
print(f"  curPrice == 1.0           : {len(cur_price_one)}")
print(f"  curPrice >= 0.99          : {len(cur_price_high)}")
print(f"  cashPnl > 0               : {len(positive_pnl)}")
print(f"  negativeRisk == True      : {len(neg_risk_any)}")

# The intersection that matters: redeemable AND has value
candidates = [p for p in all_positions
              if bool(p.get("redeemable")) and float(p.get("size") or 0) > 0]
print(f"\n  redeemable AND size > 0   : {len(candidates)}  ← likely the real target set")

# Dump full detail for the candidates
print("\n" + "="*60)
print(f"DETAIL: {len(candidates)} redeemable position(s) with size > 0")
print("="*60)
for i, p in enumerate(candidates, 1):
    print(f"\n--- #{i} ---")
    print(json.dumps(p, indent=2, default=str))

# Also dump a sample neg-risk position (winning or not) so we can see the field shape
print("\n" + "="*60)
print("SAMPLE neg-risk positions (first 3, any state)")
print("="*60)
for p in neg_risk_any[:3]:
    print(json.dumps(p, indent=2, default=str))
    print("---")

# Save everything to a file for reference
with open("positions_dump.json", "w") as f:
    json.dump(all_positions, f, indent=2, default=str)
print(f"\n💾 Full raw dump saved to positions_dump.json ({len(all_positions)} positions)")
