#!/usr/bin/env python3
"""
Final correction: April 13 dailyPnL = -17,329.

Both 3680.HK and the full 2300 shares of 1913.HK belong to April 13:
  - 3680.HK: bought April 13 (HKT midnight bug stored entryDate as Apr 14)
  - 1913.HK: 1300 extra shares added April 13 in the app

Correct April 13 daily P&L breakdown:
  13 original positions (recalcul base): -14,821
  + 113.HK (+0.07 × 20,000):            +1,400
  + 3680.HK (-0.10 × 24,000):           -2,400
  + 1913.HK extra 1300 shares (-1.16):  -1,508
  = TOTAL:                              -17,329

Fixes:
  1. Apr13 snapshot dailyPnL → -17,329
  2. Apr13 positionsAtClose[1913.HK] qty → 2300, entry → 43.597
  3. Apr10 closingPrices[3680.HK] → 2.20 (for consistent recalcul)

Usage:
  GOOGLE_APPLICATION_CREDENTIALS=... python3 patch-apr13-correct.py [--dry-run]
"""

import os, sys
import firebase_admin
from firebase_admin import credentials, firestore

MARC_UID = "cNcZwUx3nQMV96TbB1kSkQ62u8U2"
APR13    = "2026-04-13"
APR10    = "2026-04-10"

CORRECT_PNL          = -17329.0
PRADA_QTY            = 2300
PRADA_ENTRY          = 43.597
PRADA_CLOSE          = 37.76

DRY_RUN = "--dry-run" in sys.argv

cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
if not cred_path or not os.path.exists(cred_path):
    print("ERROR: Set GOOGLE_APPLICATION_CREDENTIALS"); sys.exit(1)

firebase_admin.initialize_app(credentials.Certificate(cred_path))
doc_ref   = firestore.client().document(f"portfolios/{MARC_UID}")
data      = doc_ref.get().to_dict()
snapshots = list(data.get("snapshots", []))

def find(date):
    for i, s in enumerate(snapshots):
        if s.get("date") == date:
            return i, s
    return None, None

i13, s13 = find(APR13)
i10, s10 = find(APR10)

print("=" * 60)
print("CURRENT STATE")
print("=" * 60)
print(f"  Apr13 dailyPnL = {s13.get('dailyPnL'):,.0f}" if s13 else "  No Apr13 snapshot")
prada = next((p for p in (s13 or {}).get("positionsAtClose", []) if p.get("ticker") == "1913.HK"), None)
if prada:
    print(f"  1913.HK posAtClose: qty={prada.get('quantity')} entry={prada.get('entryPrice')}")
print(f"  Apr10 closingPrices[3680.HK] = {(s10 or {}).get('closingPrices', {}).get('3680.HK', 'MISSING')}")

print("\n" + "=" * 60)
print("APPLYING FIXES")
print("=" * 60)

# Fix 1: dailyPnL
old_pnl = s13.get("dailyPnL", 0)
snapshots[i13]["dailyPnL"] = CORRECT_PNL
print(f"\n[FIX 1] Apr13 dailyPnL: {old_pnl:,.0f} → {CORRECT_PNL:,.0f}")

# Fix 2: 1913.HK positionsAtClose → qty=2300
pac = list(snapshots[i13].get("positionsAtClose", []))
for j, p in enumerate(pac):
    if p.get("ticker") == "1913.HK":
        old_qty   = p.get("quantity")
        old_entry = p.get("entryPrice")
        pac[j]["quantity"]    = PRADA_QTY
        pac[j]["entryPrice"]  = PRADA_ENTRY
        pac[j]["closingPrice"] = PRADA_CLOSE
        pac[j]["marketValue"] = round(PRADA_CLOSE * PRADA_QTY, 2)
        pac[j]["pnl"]         = round((PRADA_CLOSE - PRADA_ENTRY) * PRADA_QTY, 2)
        pac[j]["pnlPercent"]  = round((PRADA_CLOSE - PRADA_ENTRY) / PRADA_ENTRY * 100, 2)
        print(f"[FIX 2] 1913.HK posAtClose: qty {old_qty}→{PRADA_QTY}, entry {old_entry}→{PRADA_ENTRY}")
        break
snapshots[i13]["positionsAtClose"] = pac

# Fix 3: Apr10 closingPrices[3680.HK] = 2.20
if s10:
    cp10 = dict(s10.get("closingPrices", {}))
    old = cp10.get("3680.HK", "MISSING")
    cp10["3680.HK"] = 2.20
    snapshots[i10]["closingPrices"] = cp10
    print(f"[FIX 3] Apr10 closingPrices[3680.HK]: {old} → 2.20")

print(f"\n  Correct Apr13 dailyPnL: {CORRECT_PNL:,.0f} HKD")

if DRY_RUN:
    print(f"\n*** DRY RUN — nothing written ***")
else:
    print(f"\nWriting to Firestore...")
    doc_ref.update({"snapshots": snapshots})
    print("Done. Hard refresh the portfolio app.")
