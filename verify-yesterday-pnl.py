#!/usr/bin/env python3
"""
Audit a past snapshot's stored dailyPnL against the value implied by its own
closingPrices vs. the prior snapshot's closingPrices.

Why this exists: the React app and update.py both write snapshots, and update.py
uses TradingView's change_abs (not yesterday's stored closingPrices) as the
source of truth for dailyPnL. So a snapshot's stored dailyPnL can drift from
what its closingPrices alone would imply. This script makes that drift visible.

Usage:
    python verify-yesterday-pnl.py [hk|us] [YYYY-MM-DD] [--user EMAIL]

Defaults:
    market = hk
    date   = most recent snapshot strictly before today (HKT for hk, ET for us)
    user   = all portfolios in the collection

Exits 0 on clean run, prints a per-portfolio breakdown either way.
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta

import firebase_admin
from firebase_admin import credentials, firestore

PNL_DRIFT = 50.0

MARKETS = {
    "hk": {
        "collection": "portfolios",
        "tz": timezone(timedelta(hours=8)),
        "currency": "HKD",
    },
    "us": {
        "collection": "us-portfolios",
        "tz": timezone(timedelta(hours=-5)),
        "currency": "USD",
    },
}


def init_firebase():
    cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if cred_path and os.path.exists(cred_path):
        cred = credentials.Certificate(cred_path)
    elif os.environ.get("FIREBASE_CREDENTIALS_JSON"):
        cred = credentials.Certificate(json.loads(os.environ["FIREBASE_CREDENTIALS_JSON"]))
    else:
        sibling = os.path.join(
            os.path.dirname(__file__),
            "hk-portfolio-v2",
            "hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json",
        )
        if os.path.exists(sibling):
            cred = credentials.Certificate(sibling)
        else:
            print("ERROR: no Firebase credentials in env (GOOGLE_APPLICATION_CREDENTIALS or FIREBASE_CREDENTIALS_JSON)")
            sys.exit(2)
    firebase_admin.initialize_app(cred)
    return firestore.client()


def pick_snapshots(snapshots, target_date):
    """Return (target_snap, prior_snap) where prior_snap is the most recent
    snapshot strictly before target_date. Either may be None."""
    by_date = sorted(snapshots, key=lambda s: s["date"])
    target = next((s for s in by_date if s["date"] == target_date), None)
    prior = None
    for s in reversed(by_date):
        if s["date"] < target_date:
            prior = s
            break
    return target, prior


def audit_portfolio(user_id, data, target_date, currency):
    snapshots = data.get("snapshots", [])
    target, prior = pick_snapshots(snapshots, target_date)
    if not target:
        print(f"\n[{user_id}] no snapshot for {target_date} — skip")
        return False
    if not prior:
        print(f"\n[{user_id}] {target_date}: no prior snapshot to diff against")
        return False

    stored_pnl = target.get("dailyPnL")
    target_closes = target.get("closingPrices") or {}
    prior_closes = prior.get("closingPrices") or {}
    positions_at_close = target.get("positionsAtClose") or []
    closed_trades = data.get("closedTrades") or []

    # Use positionsAtClose for quantities at end-of-target-day (correct for
    # the day being audited; current `positions` array reflects today's state).
    if not positions_at_close:
        print(f"\n[{user_id}] {target_date}: no positionsAtClose array — skip")
        return False

    print(f"\n[{user_id}] auditing {target_date} (prior: {prior['date']})")
    print(f"  stored dailyPnL : {stored_pnl:>12,.2f} {currency}" if stored_pnl is not None else "  stored dailyPnL : MISSING")

    rows = []
    derived_pnl = 0.0
    missing = []
    for p in positions_at_close:
        ticker = p.get("ticker", "").replace("b.HK", ".HK")
        qty = p.get("quantity", 0)
        target_close = target_closes.get(ticker) or target_closes.get(p.get("ticker"))
        prior_close = prior_closes.get(ticker) or prior_closes.get(p.get("ticker"))
        if target_close is None or prior_close is None:
            missing.append((ticker, target_close, prior_close, qty))
            continue
        contrib = (target_close - prior_close) * qty
        derived_pnl += contrib
        rows.append((ticker, prior_close, target_close, qty, contrib))

    # Closed-today: session move only (exitPrice - prior_close) * qty.
    # Matches the cron formula in update.py and the snapshot useEffect in index.html.
    # This is NOT the same as realizedPnL delta — total realized can drift from
    # patches that retroactively clean phantom trades, which is bookkeeping noise,
    # not session P&L.
    closed_pnl = 0.0
    closed_rows = []
    for t in closed_trades:
        if t.get("exitDate") != target_date:
            continue
        ticker = (t.get("ticker") or "").replace("b.HK", ".HK")
        qty = t.get("quantity", 0)
        exit_price = t.get("exitPrice")
        prior_close = prior_closes.get(ticker) or prior_closes.get(t.get("ticker"))
        # Fallback to entry price for same-day trades (no prior close)
        baseline = prior_close if prior_close is not None else t.get("entryPrice")
        if exit_price is None or baseline is None:
            continue
        contrib = (exit_price - baseline) * qty
        closed_pnl += contrib
        closed_rows.append((ticker, baseline, exit_price, qty, contrib, prior_close is None))

    derived_total = derived_pnl + closed_pnl

    print(f"  closingPrices Δ : {derived_pnl:>12,.2f} {currency}  (open positions session move)")
    if closed_pnl or closed_rows:
        print(f"  closed-today Δ  : {closed_pnl:>12,.2f} {currency}  ({len(closed_rows)} trade(s))")
        for t, b, ex, q, c, intraday in closed_rows:
            tag = " (intraday — no prior close)" if intraday else ""
            print(f"    closed {t:<10} {b:>8.4f} → {ex:>8.4f} × {q:>6} = {c:>+12,.2f}{tag}")
    print(f"  derived total   : {derived_total:>12,.2f} {currency}")

    diff = (stored_pnl or 0) - derived_total
    flag = "  >>> DRIFT" if abs(diff) > PNL_DRIFT else "  ok"
    print(f"  diff (stored - derived): {diff:>+12,.2f} {currency} {flag}")

    # Also surface realizedPnL drift (book-keeping integrity check, separate from session P&L)
    realized_target = target.get("realizedPnL", 0) or 0
    realized_prior = prior.get("realizedPnL", 0) or 0
    realized_delta = realized_target - realized_prior
    if abs(realized_delta - closed_pnl) > 1 and closed_rows:
        # realized delta should match (exitPrice - entryPrice) * qty for closed-today trades
        expected_realized = sum((t.get("exitPrice", 0) - t.get("entryPrice", 0)) * t.get("quantity", 0)
                                for t in closed_trades if t.get("exitDate") == target_date)
        gap = realized_delta - expected_realized
        if abs(gap) > 1:
            print(f"  ⚠ realizedPnL Δ ({realized_delta:+,.2f}) ≠ expected ({expected_realized:+,.2f}); gap={gap:+,.2f} — likely phantom-trade cleanup, not a session error")

    if missing:
        print(f"  missing closingPrices for {len(missing)} ticker(s):")
        for t, tc, pc, q in missing:
            print(f"    - {t}: target={tc} prior={pc} qty={q}")

    rows.sort(key=lambda r: abs(r[4]), reverse=True)
    print(f"  per-ticker (top 10 by |contribution|):")
    print(f"    {'ticker':<12} {'prior':>10} {'target':>10} {'qty':>10} {'contrib':>14}")
    for t, pc, tc, q, c in rows[:10]:
        print(f"    {t:<12} {pc:>10.4f} {tc:>10.4f} {q:>10} {c:>+14,.2f}")
    if len(rows) > 10:
        rest = sum(r[4] for r in rows[10:])
        print(f"    {'...':<12} {'':>10} {'':>10} {'':>10} {rest:>+14,.2f}  ({len(rows)-10} more)")

    return abs(diff) > PNL_DRIFT


def main():
    args = sys.argv[1:]
    market = "hk"
    date_arg = None
    user_filter = None
    i = 0
    while i < len(args):
        a = args[i]
        if a in MARKETS:
            market = a
        elif a == "--user":
            user_filter = args[i + 1]
            i += 1
        elif a.count("-") == 2 and len(a) == 10:
            date_arg = a
        else:
            print(f"Usage: verify-yesterday-pnl.py [hk|us] [YYYY-MM-DD] [--user EMAIL]")
            sys.exit(2)
        i += 1

    cfg = MARKETS[market]
    today = datetime.now(cfg["tz"]).strftime("%Y-%m-%d")

    db = init_firebase()
    drifts = 0
    for doc in db.collection(cfg["collection"]).stream():
        if user_filter and doc.id != user_filter:
            continue
        data = doc.to_dict() or {}
        if not data.get("snapshots"):
            continue

        target_date = date_arg
        if target_date is None:
            # Most recent snapshot strictly before today
            past = [s["date"] for s in data["snapshots"] if s["date"] < today]
            if not past:
                continue
            target_date = max(past)

        if audit_portfolio(doc.id, data, target_date, cfg["currency"]):
            drifts += 1

    print(f"\nDone. Portfolios with drift > {PNL_DRIFT} {cfg['currency']}: {drifts}")
    sys.exit(0 if drifts == 0 else 1)


if __name__ == "__main__":
    main()
