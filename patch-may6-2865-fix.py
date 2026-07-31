#!/usr/bin/env python3
"""
Patch: fix erroneous 2865.HK closed trade created on 2026-05-06.

What happened: user entered qty 1800 instead of 900 when adding to position.
After correcting to 900, the app generated a fake "sold 900 shares" closed trade.
This patch:
  1. Deletes the erroneous closed trade (id 1778053810746, qty 900 at entryPrice 33.1)
  2. Fixes the open position quantity from 900 → 1800 (900 original + 900 added today)

Usage:
  python3 patch-may6-2865-fix.py [--dry-run]
"""

import os, sys, json
import firebase_admin
from firebase_admin import credentials, firestore

MARC_UID          = "cNcZwUx3nQMV96TbB1kSkQ62u8U2"
BAD_TRADE_ID      = 1778053810746
OPEN_POSITION_ID  = 1777881665140
CORRECT_QTY       = 1800

DRY_RUN = "--dry-run" in sys.argv

cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
if cred_path and os.path.exists(cred_path):
    cred = credentials.Certificate(cred_path)
else:
    sibling = os.path.join(
        os.path.dirname(__file__),
        "hk-portfolio-v2",
        "hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json",
    )
    if not os.path.exists(sibling):
        print("ERROR: no credentials found"); sys.exit(1)
    cred = credentials.Certificate(sibling)

firebase_admin.initialize_app(cred)
doc_ref = firestore.client().document(f"portfolios/{MARC_UID}")
data    = doc_ref.get().to_dict() or {}

# --- 1. Remove erroneous closed trade ---
closed = data.get("closedTrades", [])
before = len(closed)
new_closed = [t for t in closed if t.get("id") != BAD_TRADE_ID]
removed = before - len(new_closed)

if removed == 0:
    print(f"WARNING: closed trade id={BAD_TRADE_ID} not found — already deleted?")
else:
    print(f"Removing closed trade id={BAD_TRADE_ID} (qty 900, 2865.HK, fake sale)")

# --- 2. Fix open position quantity ---
positions = data.get("positions", [])
fixed_qty = False
for p in positions:
    if p.get("id") == OPEN_POSITION_ID:
        old_qty = p.get("quantity")
        if old_qty == CORRECT_QTY:
            print(f"Open position already has quantity={CORRECT_QTY} — no change needed")
        else:
            p["quantity"] = CORRECT_QTY
            print(f"Open position 2865.HK: quantity {old_qty} → {CORRECT_QTY}")
        fixed_qty = True
        break

if not fixed_qty:
    print(f"WARNING: open position id={OPEN_POSITION_ID} not found")

# --- Summary ---
print(f"\nSummary:")
print(f"  Closed trades: {before} → {len(new_closed)} (removed {removed})")
print(f"  2865.HK open qty: → {CORRECT_QTY}")

if DRY_RUN:
    print("\nDRY RUN — no write performed")
    sys.exit(0)

doc_ref.update({
    "closedTrades": new_closed,
    "positions":    positions,
})
print(f"\nFirebase updated: portfolios/{MARC_UID}")
