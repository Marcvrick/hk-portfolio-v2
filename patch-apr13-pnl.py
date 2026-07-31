#!/usr/bin/env python3
"""
Patch: Recalculate dailyPnL for April 13 snapshot.

Root cause: 3680.HK and 0113.HK had no priceCache when the cron ran at 16:30 HKT,
so their daily P&L contribution was counted as 0 in the stored snapshot.

Fix: compute delta from their actual changes × quantities at close, add to stored dailyPnL.
Also corrects 1913.HK positionsAtClose back to qty=1000 (market close state).

Usage:
  GOOGLE_APPLICATION_CREDENTIALS=... python3 patch-apr13-pnl.py [--dry-run]
"""

import os
import sys
import firebase_admin
from firebase_admin import credentials, firestore

MARC_UID  = "cNcZwUx3nQMV96TbB1kSkQ62u8U2"
DATE      = "2026-04-13"

# Confirmed correct changes for April 13 (missing from priceCache when cron ran)
MISSING_CHANGES = {
    "3680.HK": -0.10,
    "0113.HK":  0.07,
}

# 1913.HK patch previously set positionsAtClose qty to 2300, but at market close
# only 1000 shares were held (1300 added after close). Revert to correct close state.
PRADA_TICKER        = "1913.HK"
PRADA_QTY_AT_CLOSE  = 1000
PRADA_ENTRY_AT_CLOSE = 50.3   # original entry price (unchanged at close)

DRY_RUN = "--dry-run" in sys.argv

cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
if not cred_path or not os.path.exists(cred_path):
    print("ERROR: Set GOOGLE_APPLICATION_CREDENTIALS")
    sys.exit(1)

firebase_admin.initialize_app(credentials.Certificate(cred_path))
db = firestore.client()

doc_ref = db.document(f"portfolios/{MARC_UID}")
data    = doc_ref.get().to_dict()
snapshots = data.get("snapshots", [])

snap_idx = next((i for i, s in enumerate(snapshots) if s.get("date") == DATE), None)
if snap_idx is None:
    print(f"ERROR: No snapshot found for {DATE}")
    sys.exit(1)

snap = snapshots[snap_idx]
pac  = snap.get("positionsAtClose", [])
old_pnl = snap.get("dailyPnL", 0)

print("=" * 60)
print(f"SNAPSHOT {DATE}")
print("=" * 60)
print(f"  Stored dailyPnL : {old_pnl:,.0f} HKD")
print(f"  portfolioValue  : {snap.get('portfolioValue'):,.0f} HKD")

# ── Delta from 3680.HK and 0113.HK ──────────────────────────────────────────
print(f"\n--- Missing P&L contributions ---")
delta = 0.0
for ticker, change in MISSING_CHANGES.items():
    pos = next((p for p in pac if p.get("ticker") == ticker), None)
    if pos:
        qty = pos.get("quantity", 0)
        contribution = change * qty
        delta += contribution
        print(f"  {ticker}: change={change:+.2f} × qty={qty} = {contribution:+,.2f} HKD")
    else:
        print(f"  {ticker}: NOT FOUND in positionsAtClose — skipping")

# ── Fix 1913.HK positionsAtClose back to market-close state ─────────────────
prada_pac = next((p for p in pac if p.get("ticker") == PRADA_TICKER), None)
prada_correction = 0.0
if prada_pac:
    current_qty = prada_pac.get("quantity")
    if current_qty != PRADA_QTY_AT_CLOSE:
        # Extra qty was added after close — remove its P&L from the snapshot
        # change for 1913.HK on Apr 13: close=37.76, prevClose=38.92 → change=-1.16
        prada_change = -1.16
        extra_qty    = current_qty - PRADA_QTY_AT_CLOSE
        prada_correction = -(prada_change * extra_qty)  # remove extra contribution
        print(f"\n  {PRADA_TICKER}: positionsAtClose qty={current_qty} → {PRADA_QTY_AT_CLOSE}")
        print(f"    (extra {extra_qty} shares added after close — removing {prada_change*extra_qty:+,.2f} HKD from P&L)")
    else:
        print(f"\n  {PRADA_TICKER}: qty already correct at {PRADA_QTY_AT_CLOSE}")

new_pnl = old_pnl + delta + prada_correction

print(f"\n{'=' * 60}")
print(f"RESULT")
print(f"{'=' * 60}")
print(f"  Old dailyPnL : {old_pnl:+,.0f} HKD")
print(f"  Delta (3680+0113) : {delta:+,.2f} HKD")
if prada_correction:
    print(f"  Prada correction  : {prada_correction:+,.2f} HKD")
print(f"  New dailyPnL : {new_pnl:+,.0f} HKD")

# ── Apply ────────────────────────────────────────────────────────────────────
# Fix positionsAtClose for 1913.HK
for j, p in enumerate(pac):
    if p.get("ticker") == PRADA_TICKER:
        pac[j]["quantity"]   = PRADA_QTY_AT_CLOSE
        pac[j]["entryPrice"] = PRADA_ENTRY_AT_CLOSE
        break

snapshots[snap_idx]["dailyPnL"]          = round(new_pnl, 2)
snapshots[snap_idx]["positionsAtClose"]  = pac

if DRY_RUN:
    print(f"\n*** DRY RUN — nothing written ***")
else:
    print(f"\nWriting to Firestore...")
    doc_ref.update({"snapshots": snapshots})
    print("Done. Refresh the portfolio app.")
