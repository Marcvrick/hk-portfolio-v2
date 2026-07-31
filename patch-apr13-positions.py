#!/usr/bin/env python3
"""
Patch: Add 113.HK and 3680.HK to April 13 snapshot positionsAtClose.

Both positions were added after the cron ran at 16:30 HKT on April 13,
so they're absent from positionsAtClose and don't appear when clicking the tile.

Fixes:
  - positionsAtClose: add 113.HK (qty=20000, entry=6.10, close=6.17)
  - positionsAtClose: add 3680.HK (qty=24000, entry=2.20, close=2.10)
  - closingPrices: add 3680.HK=2.10 (113.HK=6.17 already present)
  - dailyPnL: -13,421 + (-2,400) = -15,821 (add 3680.HK contribution)
  - portfolioValue: add market values of both positions

Usage:
  GOOGLE_APPLICATION_CREDENTIALS=... python3 patch-apr13-positions.py [--dry-run]
"""

import os, sys
import firebase_admin
from firebase_admin import credentials, firestore

MARC_UID = "cNcZwUx3nQMV96TbB1kSkQ62u8U2"
DATE     = "2026-04-13"

NEW_POSITIONS = [
    {
        "ticker":       "113.HK",
        "name":         "Dickson Concept",
        "quantity":     20000,
        "entryPrice":   6.10,
        "entryDate":    "2026-04-13",
        "closingPrice": 6.17,
        "marketValue":  round(6.17 * 20000, 2),
        "pnl":          round((6.17 - 6.10) * 20000, 2),
        "pnlPercent":   round((6.17 - 6.10) / 6.10 * 100, 2),
    },
    {
        "ticker":       "3680.HK",
        "name":         "Ruihe Data",
        "quantity":     24000,
        "entryPrice":   2.20,
        "entryDate":    "2026-04-14",
        "closingPrice": 2.10,
        "marketValue":  round(2.10 * 24000, 2),
        "pnl":          round((2.10 - 2.20) * 24000, 2),
        "pnlPercent":   round((2.10 - 2.20) / 2.20 * 100, 2),
    },
]

DRY_RUN = "--dry-run" in sys.argv

cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
if not cred_path or not os.path.exists(cred_path):
    print("ERROR: Set GOOGLE_APPLICATION_CREDENTIALS"); sys.exit(1)

firebase_admin.initialize_app(credentials.Certificate(cred_path))
doc_ref   = firestore.client().document(f"portfolios/{MARC_UID}")
data      = doc_ref.get().to_dict()
snapshots = list(data.get("snapshots", []))

snap_idx = next((i for i, s in enumerate(snapshots) if s.get("date") == DATE), None)
if snap_idx is None:
    print(f"ERROR: No snapshot for {DATE}"); sys.exit(1)

snap = snapshots[snap_idx]
pac  = list(snap.get("positionsAtClose", []))
cp   = dict(snap.get("closingPrices", {}))
old_pnl = snap.get("dailyPnL", 0)
old_val = snap.get("portfolioValue", 0)

print("=" * 60)
print(f"CURRENT STATE — {DATE}")
print("=" * 60)
print(f"  positionCount  = {snap.get('positionCount')}")
print(f"  portfolioValue = {old_val:,.0f}")
print(f"  dailyPnL       = {old_pnl:,.0f}")
print(f"  positionsAtClose tickers: {[p.get('ticker') for p in pac]}")

print("\n" + "=" * 60)
print("APPLYING FIXES")
print("=" * 60)

existing_tickers = {p.get("ticker") for p in pac}
added_pnl   = 0
added_value = 0

for pos in NEW_POSITIONS:
    t = pos["ticker"]
    if t in existing_tickers:
        print(f"\n  {t}: already in positionsAtClose — skipping")
        continue
    pac.append(pos)
    cp[t] = pos["closingPrice"]
    added_pnl   += pos["pnl"]
    added_value += pos["marketValue"]
    print(f"\n  Added {t} ({pos['name']}):")
    print(f"    qty={pos['quantity']}  entry={pos['entryPrice']}  close={pos['closingPrice']}")
    print(f"    marketValue={pos['marketValue']:,.0f}  pnl={pos['pnl']:+,.0f} ({pos['pnlPercent']:+.2f}%)")

new_pnl = old_pnl + added_pnl
new_val = old_val + added_value

print(f"\n  dailyPnL      : {old_pnl:+,.0f} + {added_pnl:+,.0f} = {new_pnl:+,.0f} HKD")
print(f"  portfolioValue: {old_val:,.0f} + {added_value:,.0f} = {new_val:,.0f} HKD")
print(f"  positionCount : {snap.get('positionCount')} → {len(pac)}")

snapshots[snap_idx]["positionsAtClose"] = pac
snapshots[snap_idx]["closingPrices"]    = cp
snapshots[snap_idx]["dailyPnL"]         = round(new_pnl, 2)
snapshots[snap_idx]["portfolioValue"]   = round(new_val, 2)
snapshots[snap_idx]["positionCount"]    = len(pac)

if DRY_RUN:
    print(f"\n*** DRY RUN — nothing written ***")
else:
    print(f"\nWriting to Firestore...")
    doc_ref.update({"snapshots": snapshots})
    print("Done. Hard refresh the portfolio app.")
