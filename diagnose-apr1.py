#!/usr/bin/env python3
"""
Diagnose Apr 1 drift: compare stored dailyPnL vs closing-price derivation.
Also shows Mar 31 vs Apr 1 totalPnL delta (unrealizedPnL + realizedPnL)
to see which figure the patch-april-dailypnl.py approach would give.
"""
import os, firebase_admin
from firebase_admin import credentials, firestore

CRED = os.path.join(os.path.dirname(__file__), "hk-portfolio-v2",
                    "hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json")
USER_ID = "cNcZwUx3nQMV96TbB1kSkQ62u8U2"

firebase_admin.initialize_app(credentials.Certificate(CRED))
data = firestore.client().document(f"portfolios/{USER_ID}").get().to_dict()
snaps = sorted(data["snapshots"], key=lambda s: s["date"])
ct = data.get("closedTrades", [])

mar31 = next(s for s in snaps if s["date"] == "2026-03-31")
apr1  = next(s for s in snaps if s["date"] == "2026-04-01")

print("=== Mar 31 snapshot ===")
print(f"  portfolioValue : {mar31.get('portfolioValue'):,.0f}")
print(f"  unrealizedPnL  : {mar31.get('unrealizedPnL'):,.0f}")
print(f"  realizedPnL    : {mar31.get('realizedPnL'):,.0f}")
print(f"  totalPnL       : {(mar31.get('unrealizedPnL') or 0)+(mar31.get('realizedPnL') or 0):,.0f}")

print("\n=== Apr 1 snapshot ===")
print(f"  portfolioValue : {apr1.get('portfolioValue'):,.0f}")
print(f"  unrealizedPnL  : {apr1.get('unrealizedPnL'):,.0f}")
print(f"  realizedPnL    : {apr1.get('realizedPnL'):,.0f}")
print(f"  totalPnL       : {(apr1.get('unrealizedPnL') or 0)+(apr1.get('realizedPnL') or 0):,.0f}")
print(f"  stored dailyPnL: {apr1.get('dailyPnL'):,.0f}")

total_pnl_delta = ((apr1.get('unrealizedPnL') or 0)+(apr1.get('realizedPnL') or 0)) - \
                  ((mar31.get('unrealizedPnL') or 0)+(mar31.get('realizedPnL') or 0))
print(f"\ntotalPnL delta (Apr1 - Mar31) : {total_pnl_delta:+,.0f}")
print(f"closing-price derivation      : +15,762")
print(f"stored dailyPnL               : {apr1.get('dailyPnL'):+,.0f}")

print("\n=== Mar 31 closingPrices ===")
for k, v in sorted((apr1.get("closingPrices") or {}).items()):
    m = (mar31.get("closingPrices") or {}).get(k)
    pac_entry = next((p for p in (apr1.get("positionsAtClose") or [])
                      if p.get("ticker","").replace("b.HK",".HK") == k), None)
    qty = pac_entry.get("quantity", 0) if pac_entry else "?"
    contrib = (v - m) * qty if m and isinstance(qty, int) else "N/A"
    print(f"  {k:<12} mar31={m!s:>8}  apr1={v!s:>8}  qty={qty!s:>6}  contrib={contrib!s:>10}")
