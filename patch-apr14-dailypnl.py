#!/usr/bin/env python3
"""
Patch Apr 14 dailyPnL: +10,559 → +12,444.

Drift of -1,885. Correct value derived from:
  - Open positions (closing price deltas): +4,971
  - 1167.HK closed Apr 14 session move: (7.58 exit - 7.05 prevClose) × 14,100 = +7,473
  Total: +12,444

The stored +10,559 was computed by the cron before the 1167.HK exit's full
session contribution was correctly captured.

Usage: python3 patch-apr14-dailypnl.py [--dry-run]
"""
import os, sys, firebase_admin
from firebase_admin import credentials, firestore

CRED = os.path.join(os.path.dirname(__file__), "hk-portfolio-v2",
                    "hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json")
USER_ID    = "cNcZwUx3nQMV96TbB1kSkQ62u8U2"
DATE       = "2026-04-14"
OLD_PNL    = 10559
NEW_PNL    = 12444
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
if stored is None or abs((stored or 0) - OLD_PNL) > 5:
    print(f"WARNING: expected ~{OLD_PNL}, got {stored} — check before patching")
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
