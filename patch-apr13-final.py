#!/usr/bin/env python3
"""
Final patch for April 13 snapshot consistency.

Problems:
  1. dailyPnL=-14,821 missing 113.HK contribution (+0.07 × 20,000 = +1,400)
     → 113.HK added during Apr 13 but after cron ran, so not captured
  2. 3680.HK was added to Apr13+Apr10 snapshots by previous patch,
     but the position was added on Apr 14 (after midnight HKT) → should not
     appear in Apr 13 performance at all (showing -2,400 in movers table incorrectly)
  3. 1913.HK positionsAtClose shows qty=2300 but market close was qty=1000

Fixes:
  - dailyPnL: -14,821 + 1,400 = -13,421
  - Remove 3680.HK from closingPrices in Apr13 and Apr10 snapshots
  - Revert 1913.HK positionsAtClose to qty=1000, entry=50.3

Usage:
  GOOGLE_APPLICATION_CREDENTIALS=... python3 patch-apr13-final.py [--dry-run]
"""

import os, sys
import firebase_admin
from firebase_admin import credentials, firestore

MARC_UID = "cNcZwUx3nQMV96TbB1kSkQ62u8U2"
APR13    = "2026-04-13"
APR10    = "2026-04-10"

CORRECT_DAILY_PNL    = -13421.0   # -14,821 + 1,400 (113.HK: +0.07 × 20,000)
PRADA_QTY_AT_CLOSE   = 1000
PRADA_ENTRY_AT_CLOSE = 50.3

DRY_RUN = "--dry-run" in sys.argv

cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
if not cred_path or not os.path.exists(cred_path):
    print("ERROR: Set GOOGLE_APPLICATION_CREDENTIALS"); sys.exit(1)

firebase_admin.initialize_app(credentials.Certificate(cred_path))
doc_ref   = firestore.client().document(f"portfolios/{MARC_UID}")
data      = doc_ref.get().to_dict()
snapshots = list(data.get("snapshots", []))

def find_snap(date):
    for i, s in enumerate(snapshots):
        if s.get("date") == date:
            return i, s
    return None, None

i13, s13 = find_snap(APR13)
i10, s10 = find_snap(APR10)

print("=" * 60)
print("CURRENT STATE")
print("=" * 60)

if s13:
    print(f"\nApr 13 snapshot:")
    print(f"  dailyPnL       = {s13.get('dailyPnL'):,.0f}")
    print(f"  portfolioValue = {s13.get('portfolioValue'):,.0f}")
    cp13 = s13.get("closingPrices", {})
    print(f"  closingPrices[113.HK]  = {cp13.get('113.HK', 'MISSING')}")
    print(f"  closingPrices[3680.HK] = {cp13.get('3680.HK', 'MISSING')}")
    pac13 = s13.get("positionsAtClose", [])
    prada = next((p for p in pac13 if p.get("ticker") == "1913.HK"), None)
    if prada:
        print(f"  positionsAtClose[1913.HK]: qty={prada.get('quantity')} entry={prada.get('entryPrice')}")
else:
    print("No Apr 13 snapshot found")

if s10:
    cp10 = s10.get("closingPrices", {})
    print(f"\nApr 10 snapshot:")
    print(f"  closingPrices[113.HK]  = {cp10.get('113.HK', 'MISSING')}")
    print(f"  closingPrices[3680.HK] = {cp10.get('3680.HK', 'MISSING')}")

print("\n" + "=" * 60)
print("APPLYING FIXES")
print("=" * 60)

# ── Fix 1: dailyPnL ──────────────────────────────────────────────────────────
if s13:
    old_pnl = s13.get("dailyPnL", 0)
    print(f"\n[FIX 1] dailyPnL: {old_pnl:,.0f} → {CORRECT_DAILY_PNL:,.0f}")
    print(f"         (+1,400 from 113.HK: +0.07 × 20,000 shares)")
    snapshots[i13]["dailyPnL"] = CORRECT_DAILY_PNL

# ── Fix 2: Remove 3680.HK from Apr13 closingPrices ──────────────────────────
if s13:
    cp = dict(s13.get("closingPrices", {}))
    if "3680.HK" in cp:
        del cp["3680.HK"]
        snapshots[i13]["closingPrices"] = cp
        print(f"\n[FIX 2] Apr 13 closingPrices[3680.HK]: removed (position added Apr 14, not Apr 13)")
    else:
        print(f"\n[FIX 2] Apr 13 closingPrices[3680.HK]: already absent")

# ── Fix 3: Remove 3680.HK from Apr10 closingPrices ──────────────────────────
if s10:
    cpp = dict(s10.get("closingPrices", {}))
    if "3680.HK" in cpp:
        del cpp["3680.HK"]
        snapshots[i10]["closingPrices"] = cpp
        print(f"[FIX 3] Apr 10 closingPrices[3680.HK]: removed")
    else:
        print(f"[FIX 3] Apr 10 closingPrices[3680.HK]: already absent")

# ── Fix 4: Revert 1913.HK positionsAtClose to market-close state ─────────────
if s13:
    pac = list(snapshots[i13].get("positionsAtClose", []))
    for j, p in enumerate(pac):
        if p.get("ticker") == "1913.HK":
            old_qty   = p.get("quantity")
            old_entry = p.get("entryPrice")
            pac[j]["quantity"]   = PRADA_QTY_AT_CLOSE
            pac[j]["entryPrice"] = PRADA_ENTRY_AT_CLOSE
            print(f"\n[FIX 4] 1913.HK positionsAtClose: qty {old_qty}→{PRADA_QTY_AT_CLOSE}, "
                  f"entry {old_entry}→{PRADA_ENTRY_AT_CLOSE}")
            break
    snapshots[i13]["positionsAtClose"] = pac

print(f"\n{'=' * 60}")
print(f"RESULT")
print(f"{'=' * 60}")
print(f"  Apr 13 dailyPnL   : {CORRECT_DAILY_PNL:,.0f} HKD")
print(f"  3680.HK            : removed from Apr13+Apr10 snapshots (0% in pre-market = correct)")
print(f"  1913.HK posAtClose : qty=1000, entry=50.3 (market close state)")

if DRY_RUN:
    print(f"\n*** DRY RUN — nothing written ***")
else:
    print(f"\nWriting to Firestore...")
    doc_ref.update({"snapshots": snapshots})
    print("Done. Hard refresh the portfolio app.")
