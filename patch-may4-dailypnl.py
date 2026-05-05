#!/usr/bin/env python3
"""
Patch May 4 2026 snapshot: fix overcounted dailyPnL caused by using
(realized_pnl - yesterday_realized) instead of (exitPrice - prevClose) × qty
for positions closed during that session.

The old cron formula added the full entry-to-exit realized gain, which included
all prior sessions' unrealized gains already captured in previous dailyPnL tiles.
Correct formula: sum(tv_change_abs × qty for open positions at cron time)
               + sum((exitPrice - Apr30_close) × qty for positions closed on May 4)

Run: python3 patch-may4-dailypnl.py [--dry-run]
"""

import json
import os
import sys
import firebase_admin
from firebase_admin import credentials, firestore

TARGET_DATE = "2026-05-04"
PREV_DATE   = "2026-04-30"   # last trading day before May 4 (May 1 = HKEX holiday)
DRY_RUN = "--dry-run" in sys.argv

def init_firebase():
    cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if cred_path and os.path.exists(cred_path):
        cred = credentials.Certificate(cred_path)
    elif os.environ.get("FIREBASE_CREDENTIALS_JSON"):
        cred = credentials.Certificate(json.loads(os.environ["FIREBASE_CREDENTIALS_JSON"]))
    else:
        print("ERROR: No Firebase credentials found.")
        sys.exit(1)
    firebase_admin.initialize_app(cred)
    return firestore.client()

def patch_user(doc_ref, user_id):
    data = doc_ref.get().to_dict()
    snapshots    = data.get("snapshots", [])
    closed_trades = data.get("closedTrades", [])

    snap_may4 = next((s for s in snapshots if s["date"] == TARGET_DATE), None)
    snap_prev = next((s for s in snapshots if s["date"] == PREV_DATE), None)

    if not snap_may4:
        print(f"  [{user_id}] No May 4 snapshot — skipping")
        return
    if not snap_prev:
        print(f"  [{user_id}] No Apr 30 snapshot (needed for prevClose) — skipping")
        return

    prev_closes = snap_prev.get("closingPrices", {})
    positions_at_close = snap_may4.get("positionsAtClose", [])

    # Unrealized component: open positions at cron time using their stored closingPrice
    # (the cron stored these correctly via tv_change_abs; use closingPrice - prevClose as proxy)
    unrealized = 0
    for p in positions_at_close:
        clean = p["ticker"].replace("b.HK", ".HK")
        close_may4 = snap_may4.get("closingPrices", {}).get(clean)
        close_prev  = prev_closes.get(clean)
        if close_may4 is not None and close_prev is not None:
            unrealized += (close_may4 - close_prev) * p["quantity"]
        # If either price is missing, skip (no way to compute correctly)

    # Realized component: positions closed on May 4 — session move only
    realized_session = 0
    closed_may4 = [t for t in closed_trades if t.get("exitDate") == TARGET_DATE]
    for t in closed_may4:
        clean = t["ticker"].replace("b.HK", ".HK")
        prev_close = prev_closes.get(clean)
        if prev_close is not None:
            realized_session += (t.get("exitPrice", 0) - prev_close) * t.get("quantity", 0)
        elif t.get("entryDate") == TARGET_DATE:
            realized_session += (t.get("exitPrice", 0) - t.get("entryPrice", 0)) * t.get("quantity", 0)
        else:
            print(f"  [{user_id}] WARNING: no prevClose for closed ticker {t['ticker']} — skipped from realized")

    correct_pnl = round(unrealized + realized_session, 2)
    old_pnl = snap_may4.get("dailyPnL")

    print(f"  [{user_id}] May 4 dailyPnL: {old_pnl} → {correct_pnl}")
    print(f"    unrealized component : {round(unrealized, 2)}")
    print(f"    realized (session)   : {round(realized_session, 2)}  ({len(closed_may4)} positions closed)")
    if closed_may4:
        for t in closed_may4:
            clean = t["ticker"].replace("b.HK", ".HK")
            prev = prev_closes.get(clean, "N/A")
            print(f"      {clean}: exit={t.get('exitPrice')} prevClose={prev} qty={t.get('quantity')}")

    if DRY_RUN:
        print("  [DRY RUN] No changes written.")
        return

    new_snapshots = [
        {**s, "dailyPnL": correct_pnl} if s["date"] == TARGET_DATE else s
        for s in snapshots
    ]
    doc_ref.update({"snapshots": new_snapshots})
    print(f"  [{user_id}] Patched.")

def main():
    db = init_firebase()
    col = db.collection("portfolios")
    for doc in col.stream():
        patch_user(doc.reference, doc.id)

if __name__ == "__main__":
    print(f"patch-may4-dailypnl.py  DRY_RUN={DRY_RUN}")
    main()
    print("Done.")
