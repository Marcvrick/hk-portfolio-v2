#!/usr/bin/env python3
"""
Full April 2026 audit for the HK portfolio calendar.

For every April 2026 trading-day snapshot:
  - Checks dailyPnL vs. (closingPrices delta × qty + realizedPnL delta)
  - Reports any DRIFT > 50 HKD
  - Prints per-day summary table
  - Also checks portfolioValue and unrealizedPnL for sanity

Usage:
    python3 audit-april.py
"""

import os
import sys
import firebase_admin
from firebase_admin import credentials, firestore

CRED = os.path.join(
    os.path.dirname(__file__),
    "hk-portfolio-v2",
    "hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json",
)
PNL_DRIFT = 50.0

APRIL_TRADING_DAYS = [
    "2026-04-01", "2026-04-02", "2026-04-07", "2026-04-08", "2026-04-09",
    "2026-04-10", "2026-04-13", "2026-04-14", "2026-04-15", "2026-04-16",
    "2026-04-17", "2026-04-22", "2026-04-23", "2026-04-24", "2026-04-28",
    "2026-04-29", "2026-04-30",
]


def init_firebase():
    if not os.path.exists(CRED):
        print(f"ERROR: credentials not found at {CRED}")
        sys.exit(1)
    firebase_admin.initialize_app(credentials.Certificate(CRED))
    return firestore.client()


def find_snap(snapshots, date):
    return next((s for s in snapshots if s.get("date") == date), None)


def prior_snap(snapshots, date):
    past = [s for s in snapshots if s.get("date") < date]
    return max(past, key=lambda s: s["date"]) if past else None


def audit_day(snapshots, date):
    snap = find_snap(snapshots, date)
    if snap is None:
        return {"date": date, "status": "MISSING", "stored": None, "derived": None, "diff": None}

    prev = prior_snap(snapshots, date)
    if prev is None:
        return {"date": date, "status": "NO_PRIOR", "stored": snap.get("dailyPnL"), "derived": None, "diff": None}

    stored_pnl = snap.get("dailyPnL", 0) or 0
    target_closes = snap.get("closingPrices") or {}
    prior_closes  = prev.get("closingPrices") or {}
    pac = snap.get("positionsAtClose") or []

    derived_unrealized = 0.0
    missing_tickers = []
    for p in pac:
        ticker = p.get("ticker", "").replace("b.HK", ".HK")
        tc = target_closes.get(ticker)
        pc = prior_closes.get(ticker)
        if tc is None or pc is None:
            missing_tickers.append(ticker)
            continue
        derived_unrealized += (tc - pc) * p.get("quantity", 0)

    realized_delta = (snap.get("realizedPnL") or 0) - (prev.get("realizedPnL") or 0)
    derived_total = round(derived_unrealized + realized_delta, 2)
    diff = round(stored_pnl - derived_total, 2)
    status = "DRIFT" if abs(diff) > PNL_DRIFT else "ok"
    if missing_tickers:
        status += f" (missing: {','.join(missing_tickers)})"

    return {
        "date": date,
        "status": status,
        "stored": stored_pnl,
        "derived": derived_total,
        "diff": diff,
        "portfolio_value": snap.get("portfolioValue"),
        "unrealized": snap.get("unrealizedPnL"),
        "realized": snap.get("realizedPnL"),
        "prior_date": prev["date"],
    }


def main():
    db = init_firebase()
    col = db.collection("portfolios")
    docs = list(col.stream())
    print(f"Found {len(docs)} portfolio document(s)\n")

    for doc in docs:
        data = doc.to_dict() or {}
        snapshots = sorted(data.get("snapshots", []), key=lambda s: s["date"])
        if not snapshots:
            print(f"[{doc.id}] no snapshots — skip")
            continue

        print(f"=== Portfolio: {doc.id} ===")
        print(f"{'Date':<14} {'Prior':<14} {'Stored':>10} {'Derived':>10} {'Diff':>10}  {'PortVal':>12}  Status")
        print("-" * 90)

        april_snaps = [s for s in snapshots if s.get("date", "").startswith("2026-04")]
        if not april_snaps:
            print("  No April 2026 snapshots found.")
            continue

        drift_count = 0
        sum_stored  = 0.0
        sum_derived = 0.0
        for s in april_snaps:
            r = audit_day(snapshots, s["date"])
            stored_str  = f"{r['stored']:>+10,.0f}" if r['stored'] is not None else "       N/A"
            derived_str = f"{r['derived']:>+10,.0f}" if r['derived'] is not None else "       N/A"
            diff_str    = f"{r['diff']:>+10,.0f}" if r['diff'] is not None else "       N/A"
            pv_str      = f"{r['portfolio_value']:>12,.0f}" if r.get('portfolio_value') else "           N/A"
            prior_str   = r.get("prior_date", "N/A")
            print(f"{r['date']:<14} {prior_str:<14} {stored_str} {derived_str} {diff_str}  {pv_str}  {r['status']}")
            if "DRIFT" in r["status"]:
                drift_count += 1
            if r["stored"] is not None:
                sum_stored  += r["stored"]
            if r["derived"] is not None:
                sum_derived += r["derived"]

        print("-" * 90)
        print(f"{'APRIL TOTAL':<14} {'':14} {sum_stored:>+10,.0f} {sum_derived:>+10,.0f} {sum_stored-sum_derived:>+10,.0f}")
        print(f"\nResult: {drift_count} day(s) with drift > {PNL_DRIFT} HKD out of {len(april_snaps)} snapshots")

        # Also check which April trading days have NO snapshot
        snap_dates = {s["date"] for s in snapshots}
        missing = [d for d in APRIL_TRADING_DAYS if d not in snap_dates]
        if missing:
            print(f"Missing snapshots for expected trading days: {', '.join(missing)}")
        else:
            print("All expected April trading day snapshots present.")

        print()


if __name__ == "__main__":
    main()
