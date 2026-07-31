#!/usr/bin/env python3
"""
Patch the May 15 snapshot for 3 retroactive sales (2382, 2013, 1999) that
were originally not recorded in the database during the week of May 11-15.

Also fixes the 2382.HK closedTrades exitDate from 2026-05-09 (Saturday, invalid)
to 2026-05-15 (actual execution date).

Idempotent — re-running after a successful patch is a no-op (will detect the
state is already correct and skip).

Usage:
  python3 patch-may15-retroactive-sales.py            # dry-run (default)
  python3 patch-may15-retroactive-sales.py --apply    # write to Firestore
"""
import json
import os
import sys

import firebase_admin
from firebase_admin import credentials, firestore

MARC_UID = "cNcZwUx3nQMV96TbB1kSkQ62u8U2"
TARGET_DATE = "2026-05-15"
PREV_DATE = "2026-05-14"

SOLD = {
    "2382.HK": {"qty": 1500,  "entryPrice": 66.95, "exitPrice": 64.75, "wrongExitDate": "2026-05-09"},
    "2013.HK": {"qty": 33000, "entryPrice": 1.53,  "exitPrice": 1.42,  "wrongExitDate": None},
    "1999.HK": {"qty": 20000, "entryPrice": 4.96,  "exitPrice": 3.95,  "wrongExitDate": None},
}

APPLY = "--apply" in sys.argv


def init_db():
    cred = credentials.Certificate(os.environ["GOOGLE_APPLICATION_CREDENTIALS"])
    firebase_admin.initialize_app(cred)
    return firestore.client()


def main():
    db = init_db()
    ref = db.document(f"portfolios/{MARC_UID}")
    data = ref.get().to_dict()

    snapshots = list(data.get("snapshots", []))
    closed = list(data.get("closedTrades", []))

    # --- Step 1: fix 2382 closedTrades exitDate (if still wrong) ---
    fixed_closed = False
    for ct in closed:
        if ct.get("ticker") == "2382.HK" and ct.get("exitDate") == SOLD["2382.HK"]["wrongExitDate"]:
            ct["exitDate"] = TARGET_DATE
            fixed_closed = True
    print(f"[closedTrades] 2382.HK exitDate {SOLD['2382.HK']['wrongExitDate']} -> {TARGET_DATE}: "
          f"{'WILL PATCH' if fixed_closed else 'already correct or different'}")

    # --- Step 2: patch May 15 snapshot ---
    snap_t = next((s for s in snapshots if s["date"] == TARGET_DATE), None)
    snap_p = next((s for s in snapshots if s["date"] == PREV_DATE), None)
    if not snap_t or not snap_p:
        print("ERROR: missing target or prev snapshot.")
        sys.exit(1)

    prev_closes = snap_p.get("closingPrices", {})
    tgt_closes  = snap_t.get("closingPrices", {})

    sold_set = set(SOLD.keys())
    pac_old = snap_t.get("positionsAtClose", []) or []
    pac_new = [p for p in pac_old if p["ticker"] not in sold_set]
    removed = [p["ticker"] for p in pac_old if p["ticker"] in sold_set]

    # unrealized leg over kept positions
    unreal = 0.0
    for p in pac_new:
        c_t = tgt_closes.get(p["ticker"])
        c_p = prev_closes.get(p["ticker"])
        if c_t is not None and c_p is not None:
            unreal += (c_t - c_p) * p["quantity"]

    # realized session leg over sold positions
    realized_session = 0.0
    for t, info in SOLD.items():
        c_p = prev_closes.get(t)
        if c_p is None:
            print(f"  WARN: no prevClose for {t} on {PREV_DATE} — realized leg incomplete")
            continue
        realized_session += (info["exitPrice"] - c_p) * info["qty"]

    new_dailyPnL = round(unreal + realized_session, 2)
    new_pv = round(sum(p["quantity"] * tgt_closes.get(p["ticker"], 0) for p in pac_new), 2)
    new_unr = round(sum((tgt_closes.get(p["ticker"], p["entryPrice"]) - p["entryPrice"]) * p["quantity"]
                        for p in pac_new), 2)

    # realized cumulative = realized of May 14 + sum of realized for new closes today
    prev_realized = snap_p.get("realizedPnL", 0) or 0
    realized_total_delta = sum((info["exitPrice"] - info["entryPrice"]) * info["qty"]
                               for info in SOLD.values())
    new_realized = round(prev_realized + realized_total_delta, 2)

    old = {
        "posCount": len(pac_old),
        "dailyPnL": snap_t.get("dailyPnL"),
        "portfolioValue": snap_t.get("portfolioValue"),
        "unrealizedPnL": snap_t.get("unrealizedPnL"),
        "realizedPnL": snap_t.get("realizedPnL"),
    }
    new = {
        "posCount": len(pac_new),
        "dailyPnL": new_dailyPnL,
        "portfolioValue": new_pv,
        "unrealizedPnL": new_unr,
        "realizedPnL": new_realized,
    }

    print(f"\n[snapshot {TARGET_DATE}]")
    print(f"  removed positions: {removed}")
    for k in old:
        print(f"  {k:18s}  {old[k]}  ->  {new[k]}")

    # Idempotency check: if everything already matches, skip write
    snapshot_already_ok = (
        len(pac_old) == len(pac_new)
        and abs((snap_t.get("dailyPnL") or 0) - new_dailyPnL) < 0.5
        and abs((snap_t.get("realizedPnL") or 0) - new_realized) < 0.5
    )

    if not APPLY:
        print("\n[DRY-RUN] No changes written. Re-run with --apply to commit.")
        return

    needs_write = fixed_closed or not snapshot_already_ok
    if not needs_write:
        print("\n[NO-OP] State already correct, nothing to write.")
        return

    # Build new snapshot
    snap_t_new = {
        **snap_t,
        "positionsAtClose": pac_new,
        "dailyPnL": new_dailyPnL,
        "portfolioValue": new_pv,
        "unrealizedPnL": new_unr,
        "realizedPnL": new_realized,
    }
    snapshots_new = [snap_t_new if s["date"] == TARGET_DATE else s for s in snapshots]

    update = {"snapshots": snapshots_new}
    if fixed_closed:
        update["closedTrades"] = closed

    ref.update(update)
    print("\n[APPLIED] Firestore updated.")

    # Verify
    after = ref.get().to_dict()
    snap_after = next((s for s in after["snapshots"] if s["date"] == TARGET_DATE), None)
    ct_after = next((c for c in after["closedTrades"]
                     if c.get("ticker") == "2382.HK" and c.get("exitDate") == TARGET_DATE), None)
    print(f"\n[VERIFY] {TARGET_DATE} posCount={len(snap_after.get('positionsAtClose', []))} "
          f"dailyPnL={snap_after.get('dailyPnL')} "
          f"realizedPnL={snap_after.get('realizedPnL')}")
    print(f"[VERIFY] 2382.HK closedTrades exitDate={ct_after.get('exitDate') if ct_after else 'NOT FOUND'}")


if __name__ == "__main__":
    main()
