#!/usr/bin/env python3
"""
Patch any snapshot's dailyPnL using the correct formula:
  unrealized = sum((close_target - close_prev) * qty  for open positions)
  realized   = sum((exitPrice   - close_prev) * qty  for positions closed that day)

Usage:
  python3 patch-snapshot-dailypnl.py TARGET_DATE PREV_DATE [--dry-run]

Examples:
  python3 patch-snapshot-dailypnl.py 2026-05-05 2026-05-04 --dry-run
  python3 patch-snapshot-dailypnl.py 2026-05-05 2026-05-04
"""

import json
import os
import sys
import firebase_admin
from firebase_admin import credentials, firestore

if len(sys.argv) < 3:
    print("Usage: patch-snapshot-dailypnl.py TARGET_DATE PREV_DATE [--dry-run]")
    sys.exit(1)

TARGET_DATE = sys.argv[1]
PREV_DATE   = sys.argv[2]
DRY_RUN     = "--dry-run" in sys.argv


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
    snapshots     = data.get("snapshots", [])
    closed_trades = data.get("closedTrades", [])

    snap_target = next((s for s in snapshots if s["date"] == TARGET_DATE), None)
    snap_prev   = next((s for s in snapshots if s["date"] == PREV_DATE), None)

    if not snap_target:
        print(f"  [{user_id}] No {TARGET_DATE} snapshot — skipping")
        return
    if not snap_prev:
        print(f"  [{user_id}] No {PREV_DATE} snapshot (needed for prevClose) — skipping")
        return

    prev_closes        = snap_prev.get("closingPrices", {})
    positions_at_close = snap_target.get("positionsAtClose", [])
    target_closes      = snap_target.get("closingPrices", {})

    unrealized = 0
    for p in positions_at_close:
        clean      = p["ticker"].replace("b.HK", ".HK")
        close_tgt  = target_closes.get(clean)
        close_prev = prev_closes.get(clean)
        if close_tgt is not None and close_prev is not None:
            unrealized += (close_tgt - close_prev) * p["quantity"]

    realized_session = 0
    closed_today = [t for t in closed_trades if t.get("exitDate") == TARGET_DATE]
    for t in closed_today:
        clean      = t["ticker"].replace("b.HK", ".HK")
        prev_close = prev_closes.get(clean)
        if prev_close is not None:
            realized_session += (t.get("exitPrice", 0) - prev_close) * t.get("quantity", 0)
        elif t.get("entryDate") == TARGET_DATE:
            realized_session += (t.get("exitPrice", 0) - t.get("entryPrice", 0)) * t.get("quantity", 0)
        else:
            print(f"  [{user_id}] WARNING: no prevClose for {t['ticker']} — skipped from realized")

    correct_pnl = round(unrealized + realized_session, 2)
    old_pnl     = snap_target.get("dailyPnL")

    print(f"  [{user_id}] {TARGET_DATE} dailyPnL: {old_pnl} → {correct_pnl}")
    print(f"    unrealized component : {round(unrealized, 2)}")
    print(f"    realized (session)   : {round(realized_session, 2)}  ({len(closed_today)} positions closed)")
    if closed_today:
        for t in closed_today:
            clean = t["ticker"].replace("b.HK", ".HK")
            prev  = prev_closes.get(clean, "N/A")
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
    db  = init_firebase()
    col = db.collection("portfolios")
    for doc in col.stream():
        patch_user(doc.reference, doc.id)


if __name__ == "__main__":
    print(f"patch-snapshot-dailypnl.py  TARGET={TARGET_DATE}  PREV={PREV_DATE}  DRY_RUN={DRY_RUN}")
    main()
    print("Done.")
