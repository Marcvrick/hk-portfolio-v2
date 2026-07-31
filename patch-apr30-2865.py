#!/usr/bin/env python3
"""
Patch: add missing 2865.HK closingPrice to the April 30 2026 snapshot.

Why: verify-yesterday-pnl.py flagged a +1,114 HKD drift on the May 4 snapshot
because 2865.HK had no entry in April 30's `closingPrices` map. The cron
(update.py) used TradingView's change_abs to compute dailyPnL, so the stored
figure is fine, but per-ticker historical math (and any UI that reads
closingPrices directly) was missing the prior close.

Source: FinMC dataset
  Data /hkex stocks/collected/2865.HK_collected.txt
  20260430,1600,33.2,34.34,31.98,33.74,9725700,0  → close 33.74

Usage:
  python3 patch-apr30-2865.py [--dry-run]
"""

import os, sys
import firebase_admin
from firebase_admin import credentials, firestore

MARC_UID    = "cNcZwUx3nQMV96TbB1kSkQ62u8U2"
SNAP_DATE   = "2026-04-30"
TICKER      = "2865.HK"
CLOSE_PRICE = 33.74

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
        print("ERROR: no credentials"); sys.exit(1)
    cred = credentials.Certificate(sibling)

firebase_admin.initialize_app(cred)
doc_ref = firestore.client().document(f"portfolios/{MARC_UID}")
data    = doc_ref.get().to_dict() or {}
snaps   = data.get("snapshots", [])

idx = next((i for i, s in enumerate(snaps) if s.get("date") == SNAP_DATE), None)
if idx is None:
    print(f"ERROR: no snapshot for {SNAP_DATE}"); sys.exit(1)

snap = snaps[idx]
closes = dict(snap.get("closingPrices") or {})

existing = closes.get(TICKER)
if existing is not None:
    print(f"{SNAP_DATE} already has {TICKER} = {existing} — nothing to do")
    sys.exit(0)

print(f"{SNAP_DATE} snapshot — adding {TICKER}: {CLOSE_PRICE}")
closes[TICKER] = CLOSE_PRICE
snap["closingPrices"] = closes

# If positionsAtClose has a 2865.HK entry without closingPrice, fill that too
pac = snap.get("positionsAtClose") or []
for p in pac:
    t = (p.get("ticker") or "").replace("b.HK", ".HK")
    if t == TICKER and not p.get("closingPrice"):
        qty = p.get("quantity", 0)
        entry = p.get("entryPrice", 0)
        p["closingPrice"] = CLOSE_PRICE
        p["marketValue"]  = round(CLOSE_PRICE * qty, 2)
        p["pnl"]          = round((CLOSE_PRICE - entry) * qty, 2)
        if entry:
            p["pnlPercent"] = round((CLOSE_PRICE - entry) / entry * 100, 4)
        print(f"  also patched positionsAtClose entry for {TICKER}")

snaps[idx] = snap

if DRY_RUN:
    print("DRY RUN — no write")
    sys.exit(0)

doc_ref.update({"snapshots": snaps})
print(f"Updated snapshot {SNAP_DATE} in portfolios/{MARC_UID}")
