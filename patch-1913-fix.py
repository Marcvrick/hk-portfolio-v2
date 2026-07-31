#!/usr/bin/env python3
"""
Patch: Fix 1913.HK (Prada) position — added multiple times by error on 2026-04-13.

Problem:
  - User added 1913.HK several times → quantity/entryPrice corrupted by
    repeated weighted-average accumulation
  - addedTodayDate / addedTodayQty / addedTodayPrice fields also corrupted

Correct final state:
  - Pre-existing: 2300 shares @ 43.587 HKD
  - Added today:  1300 shares @ 38.92 HKD
  - Total:        3600 shares @ 41.902 HKD (weighted avg)
  - addedTodayQty=1300 / addedTodayPrice=38.92 preserved for correct intraday P&L

What this script does:
  1. Shows current state of 1913.HK in positions + today's snapshot
  2. Replaces all 1913.HK entries with ONE correct position (3600 @ 41.902)
  3. Restores correct addedToday* tracking fields
  4. If today's snapshot already exists (cron ran), fixes positionsAtClose qty/entryPrice
  5. Leaves priceCache and closingPrices untouched (TradingView official data)

Usage:
  GOOGLE_APPLICATION_CREDENTIALS=firebase-credentials.json python patch-1913-fix.py [--dry-run]
"""

import os
import sys
import json
import firebase_admin
from firebase_admin import credentials, firestore

# === CONFIG ===
MARC_UID  = "cNcZwUx3nQMV96TbB1kSkQ62u8U2"
TODAY     = "2026-04-13"
TICKER    = "1913.HK"
CORRECT_QTY         = 2300
CORRECT_ENTRY_PRICE = 43.597   # confirmed avg from broker (2300 shares total)
CORRECT_ENTRY_DATE  = "2026-04-13"   # will be replaced by original entryDate from Firestore

# Intraday addition tracking (for accurate daily P&L on the 1300 new shares only)
ADDED_TODAY_QTY   = 1300
ADDED_TODAY_PRICE = 38.92
ADDED_TODAY_DATE  = "2026-04-13"
QTY_BEFORE_TODAY  = 1000

DRY_RUN = "--dry-run" in sys.argv

# === INIT FIREBASE ===
cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
if not cred_path or not os.path.exists(cred_path):
    print("ERROR: Set GOOGLE_APPLICATION_CREDENTIALS to the path of your service account JSON")
    sys.exit(1)

cred = credentials.Certificate(cred_path)
firebase_admin.initialize_app(cred)
db = firestore.client()

doc_ref = db.document(f"portfolios/{MARC_UID}")
doc     = doc_ref.get()
data    = doc.to_dict()

positions    = data.get("positions", [])
closed_trades = data.get("closedTrades", [])
snapshots    = data.get("priceCache", {})  # just for display
price_cache  = data.get("priceCache", {})
all_snapshots = data.get("snapshots", [])

# ─── 1. INSPECT ──────────────────────────────────────────────────────────────
print("=" * 60)
print("CURRENT STATE")
print("=" * 60)

positions_1913 = [p for p in positions if p.get("ticker") == TICKER]
print(f"\n--- Positions for {TICKER} ({len(positions_1913)} entry/entries) ---")
for p in positions_1913:
    print(f"  id={p.get('id')}  qty={p.get('quantity')}  entry={p.get('entryPrice')}  "
          f"date={p.get('entryDate')}")
    for key in ("addedTodayDate", "addedTodayQty", "addedTodayPrice", "qtyBeforeToday"):
        if key in p:
            print(f"    {key}={p[key]}")

today_snap = next((s for s in all_snapshots if s.get("date") == TODAY), None)
print(f"\n--- Today's snapshot ({TODAY}) ---")
if today_snap:
    print(f"  portfolioValue = {today_snap.get('portfolioValue'):,.0f} HKD")
    print(f"  dailyPnL       = {today_snap.get('dailyPnL'):,.0f} HKD")
    cp_1913 = today_snap.get("closingPrices", {}).get(TICKER, "N/A")
    print(f"  closingPrices[{TICKER}] = {cp_1913}")
    pac_1913 = [p for p in today_snap.get("positionsAtClose", []) if p.get("ticker") == TICKER]
    if pac_1913:
        p = pac_1913[0]
        print(f"  positionsAtClose: qty={p.get('quantity')}  entry={p.get('entryPrice')}  "
              f"close={p.get('closingPrice')}")
else:
    print("  (no snapshot yet — cron hasn't run today)")

print(f"\n--- priceCache[{TICKER}] ---")
cache_1913 = price_cache.get(TICKER, {})
print(f"  {json.dumps(cache_1913, indent=2, default=str)}")

# ─── 2. FIX POSITIONS ────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("APPLYING FIXES")
print("=" * 60)

first = positions_1913[0] if positions_1913 else {}

correct_position = {
    "id":              first.get("id", int(__import__("time").time() * 1000)),
    "ticker":          TICKER,
    "name":            first.get("name", "Prada"),
    "quantity":        CORRECT_QTY,
    "entryPrice":      CORRECT_ENTRY_PRICE,
    "currentPrice":    cache_1913.get("price", CORRECT_ENTRY_PRICE),
    "entryDate":       first.get("entryDate", CORRECT_ENTRY_DATE),  # keep original entry date
    # Intraday addition tracking — needed for accurate daily P&L on the 1300 new shares
    "addedTodayDate":  ADDED_TODAY_DATE,
    "addedTodayQty":   ADDED_TODAY_QTY,
    "addedTodayPrice": ADDED_TODAY_PRICE,
    "qtyBeforeToday":  QTY_BEFORE_TODAY,
}

# Replace all 1913.HK entries with single correct one
new_positions = [p for p in positions if p.get("ticker") != TICKER]
new_positions.append(correct_position)

removed = len(positions_1913)
print(f"\n[FIX 1] Positions: removed {removed} corrupted entry/entries for {TICKER}")
print(f"        Added 1 correct: qty={CORRECT_QTY}, entry={CORRECT_ENTRY_PRICE} HKD (weighted avg)")
print(f"        Original entryDate preserved: {correct_position['entryDate']}")
print(f"        addedTodayQty={ADDED_TODAY_QTY} @ {ADDED_TODAY_PRICE} / qtyBeforeToday={QTY_BEFORE_TODAY}")

# ─── 3. FIX TODAY'S SNAPSHOT (if cron already ran) ───────────────────────────
new_snapshots = list(all_snapshots)

if today_snap:
    snap_idx = next(i for i, s in enumerate(all_snapshots) if s.get("date") == TODAY)
    pac = today_snap.get("positionsAtClose", [])
    pac_1913 = [p for p in pac if p.get("ticker") == TICKER]

    if pac_1913:
        old_qty   = pac_1913[0].get("quantity")
        old_entry = pac_1913[0].get("entryPrice")
        for j, entry in enumerate(pac):
            if entry.get("ticker") == TICKER:
                pac[j]["quantity"]   = CORRECT_QTY
                pac[j]["entryPrice"] = CORRECT_ENTRY_PRICE
                break
        print(f"\n[FIX 2] positionsAtClose[{TICKER}]: qty {old_qty}→{CORRECT_QTY}, "
              f"entry {old_entry}→{CORRECT_ENTRY_PRICE}")
    else:
        print(f"\n[FIX 2] positionsAtClose[{TICKER}]: not found in snapshot (cron may not have run yet)")

    new_snapshots[snap_idx]["positionsAtClose"] = pac
    # portfolioValue and dailyPnL use TradingView closingPrices — not affected by qty/entry fix
    # No recalculation needed unless quantity itself changed
    print(f"        portfolioValue and dailyPnL unchanged (closingPrices from TradingView are correct)")
else:
    print(f"\n[FIX 2] No snapshot for {TODAY} — nothing to patch in snapshots")

# ─── 4. SUMMARY ──────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)
print(f"  Positions before: {len(positions)} (including {removed} bad 1913.HK entry/entries)")
print(f"  Positions after:  {len(new_positions)} (1 clean 1913.HK entry)")
print(f"  1913.HK: qty={CORRECT_QTY} ({QTY_BEFORE_TODAY} + {ADDED_TODAY_QTY} today), "
      f"avg entry={CORRECT_ENTRY_PRICE} HKD")
print(f"  addedTodayQty={ADDED_TODAY_QTY} @ {ADDED_TODAY_PRICE} — daily P&L correct for today")
print(f"  priceCache: untouched (TradingView official prices preserved)")

if DRY_RUN:
    print(f"\n*** DRY RUN — no changes written to Firestore ***")
    print(f"Run without --dry-run to apply.")
else:
    print(f"\nWriting to Firestore...")
    doc_ref.update({
        "positions": new_positions,
        "snapshots": new_snapshots,
    })
    print(f"Done. Refresh the portfolio app to see corrected data.")
