#!/usr/bin/env python3
"""
Fix 3680.HK entryDate: "2026-04-14" → "2026-04-13"

Root cause: position was bought April 13 HKT but added to the app after
midnight UTC, so JavaScript stored entryDate as "2026-04-14" (UTC date).
Today IS April 14, so isNewToday=true → the Performance tab uses
entryPrice as previousClose instead of TradingView's official previous
session close → shows yesterday's manual patch values, not today's move.

Fix: set entryDate = "2026-04-13" so isNewToday=false → useTvDirect=true
→ TradingView's live changePercent/change used correctly.

Usage:
  GOOGLE_APPLICATION_CREDENTIALS=... python3 patch-3680-entrydate.py [--dry-run]
"""

import os, sys
import firebase_admin
from firebase_admin import credentials, firestore

MARC_UID = "cNcZwUx3nQMV96TbB1kSkQ62u8U2"
TICKER   = "3680.HK"
OLD_DATE = "2026-04-14"
NEW_DATE = "2026-04-13"

DRY_RUN = "--dry-run" in sys.argv

cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
if not cred_path or not os.path.exists(cred_path):
    print("ERROR: Set GOOGLE_APPLICATION_CREDENTIALS"); sys.exit(1)

firebase_admin.initialize_app(credentials.Certificate(cred_path))
doc_ref  = firestore.client().document(f"portfolios/{MARC_UID}")
data     = doc_ref.get().to_dict()
positions = list(data.get("positions", []))

found = False
for i, p in enumerate(positions):
    if p.get("ticker") == TICKER:
        found = True
        current_date = p.get("entryDate")
        print(f"Found {TICKER}: entryDate = {current_date}")
        if current_date == OLD_DATE:
            positions[i]["entryDate"] = NEW_DATE
            print(f"  → entryDate: {OLD_DATE} → {NEW_DATE}")
        else:
            print(f"  → entryDate is already '{current_date}', no change needed")
        break

if not found:
    print(f"ERROR: {TICKER} not found in positions"); sys.exit(1)

if DRY_RUN:
    print("\n*** DRY RUN — nothing written ***")
else:
    print("\nWriting to Firestore...")
    doc_ref.update({"positions": positions})
    print("Done. Hard refresh the portfolio app.")
