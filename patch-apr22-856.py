#!/usr/bin/env python3
"""
Patch: add missing 856.HK closingPrice to the April 22 2026 snapshot.

Source: FinMC dataset
  Data/hkex stocks/collected/856.HK_collected.txt
  856.HK,1d,20260422,1600,9.74,10.03,9.58,9.7,5426012,0  → close 9.7

The cron computed dailyPnL correctly via TV change_abs, so dailyPnL is unchanged.
Adding the closingPrice ensures prior-close lookups for Apr 23 derivation work.

Usage: python3 patch-apr22-856.py [--dry-run]
"""
import os, sys, firebase_admin
from firebase_admin import credentials, firestore

CRED = os.path.join(os.path.dirname(__file__), "hk-portfolio-v2",
                    "hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json")
USER_ID = "cNcZwUx3nQMV96TbB1kSkQ62u8U2"
SNAP_DATE   = "2026-04-22"
TICKER      = "856.HK"
CLOSE_PRICE = 9.7
DRY_RUN = "--dry-run" in sys.argv

firebase_admin.initialize_app(credentials.Certificate(CRED))
doc_ref = firestore.client().document(f"portfolios/{USER_ID}")
data    = doc_ref.get().to_dict() or {}
snaps   = data.get("snapshots", [])

idx = next((i for i, s in enumerate(snaps) if s.get("date") == SNAP_DATE), None)
if idx is None:
    print(f"ERROR: no snapshot for {SNAP_DATE}"); sys.exit(1)

snap   = snaps[idx]
closes = dict(snap.get("closingPrices") or {})
existing = closes.get(TICKER)
if existing is not None:
    print(f"{SNAP_DATE} already has {TICKER} = {existing} — nothing to do"); sys.exit(0)

print(f"{SNAP_DATE} snapshot — adding {TICKER}: {CLOSE_PRICE}")
closes[TICKER] = CLOSE_PRICE
snap["closingPrices"] = closes

pac = snap.get("positionsAtClose") or []
for p in pac:
    t = (p.get("ticker") or "").replace("b.HK", ".HK")
    if t == TICKER and not p.get("closingPrice"):
        qty   = p.get("quantity", 0)
        entry = p.get("entryPrice", 0)
        p["closingPrice"] = CLOSE_PRICE
        p["marketValue"]  = round(CLOSE_PRICE * qty, 2)
        p["pnl"]          = round((CLOSE_PRICE - entry) * qty, 2)
        if entry:
            p["pnlPercent"] = round((CLOSE_PRICE - entry) / entry * 100, 4)
        print(f"  also patched positionsAtClose entry for {TICKER}")

snaps[idx] = snap
if DRY_RUN:
    print("DRY RUN — no write"); sys.exit(0)

doc_ref.update({"snapshots": snaps})
print(f"Updated {SNAP_DATE} in portfolios/{USER_ID}")
