#!/usr/bin/env python3
"""
Patch Apr 13 dailyPnL: -14,821 → -17,329.

All Apr 13 closingPrices are present and correct. The drift (+2,508) means
the stored value is less negative than what market data implies. Root cause:
closing prices were patched after the original cron write, but dailyPnL was
not realigned. The audit-april-v2.py formula confirms: sum of
(close - prior_close) × qty for all positions = -17,329.

Usage: python3 patch-apr13-dailypnl.py [--dry-run]
"""
import os, sys, firebase_admin
from firebase_admin import credentials, firestore

CRED = os.path.join(os.path.dirname(__file__), "hk-portfolio-v2",
                    "hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json")
USER_ID    = "cNcZwUx3nQMV96TbB1kSkQ62u8U2"
DATE       = "2026-04-13"
OLD_PNL    = -14821
NEW_PNL    = -17329
DRY_RUN    = "--dry-run" in sys.argv

firebase_admin.initialize_app(credentials.Certificate(CRED))
doc_ref = firestore.client().document(f"portfolios/{USER_ID}")
data = doc_ref.get().to_dict() or {}
snaps = data.get("snapshots", [])

idx = next((i for i, s in enumerate(snaps) if s.get("date") == DATE), None)
if idx is None:
    print(f"ERROR: no snapshot for {DATE}"); sys.exit(1)

stored = snaps[idx].get("dailyPnL")
print(f"{DATE}: stored dailyPnL = {stored}")
if stored != OLD_PNL:
    print(f"WARNING: expected {OLD_PNL}, got {stored} — check before patching")
    if not DRY_RUN:
        resp = input("Proceed anyway? [y/N] ")
        if resp.lower() != "y":
            sys.exit(0)

print(f"  → patching to {NEW_PNL}")
snaps[idx]["dailyPnL"] = NEW_PNL
if DRY_RUN:
    print("DRY RUN — no write"); sys.exit(0)

doc_ref.update({"snapshots": snaps})
print(f"Updated {DATE} dailyPnL in portfolios/{USER_ID}")
