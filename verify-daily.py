#!/usr/bin/env python3
"""
Post-cron self-check.

Runs immediately after update.py / update-us.py finishes its daily snapshot.
For every portfolio it just touched, it re-pulls TradingView's settlement
values and verifies that today's snapshot agrees with TV.

Usage:
    python verify-daily.py hk    # checks the `portfolios` collection
    python verify-daily.py us    # checks the `us-portfolios` collection

Three checks, with their thresholds:

  1. Per-ticker closingPrice drift  > 0.02 in market currency
  2. Per-ticker changePercent drift > 0.05 percentage points
  3. dailyPnL drift                 > 50 in market currency vs sum(TV change_abs * qty)

If anything trips, prints a structured FAIL block and exits 1 so the GitHub
Actions run is marked red. Clean run prints a one-line PASS and exits 0.
"""

import json
import os
import ssl
import sys
import urllib.request
from datetime import datetime, timezone, timedelta

import firebase_admin
from firebase_admin import credentials, firestore

CLOSE_DRIFT = 0.02
PCT_DRIFT = 0.05
PNL_DRIFT = 50.0

MARKETS = {
    "hk": {
        "scanner_url": "https://scanner.tradingview.com/hongkong/scan",
        "collection": "portfolios",
        "tz": timezone(timedelta(hours=8)),
        "currency": "HKD",
        # HK tickers come back from TV without zero-padding ("1913", "285").
        # Positions can be stored either way, so mirror under both keys.
        "pad": True,
        "ticker_suffix": ".HK",
    },
    "us": {
        "scanner_url": "https://scanner.tradingview.com/america/scan",
        "collection": "us-portfolios",
        "tz": timezone(timedelta(hours=-5)),  # ET (DST handled approximately; weekday check is what matters)
        "currency": "USD",
        "pad": False,
        "ticker_suffix": "",
    },
}


def init_firebase():
    cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if cred_path and os.path.exists(cred_path):
        cred = credentials.Certificate(cred_path)
    elif os.environ.get("FIREBASE_CREDENTIALS_JSON"):
        cred = credentials.Certificate(json.loads(os.environ["FIREBASE_CREDENTIALS_JSON"]))
    else:
        print("ERROR: no Firebase credentials in env")
        sys.exit(2)
    firebase_admin.initialize_app(cred)
    return firestore.client()


def fetch_tv(market_cfg):
    payload = {
        "columns": ["name", "close", "change", "change_abs"],
        "range": [0, 25000],
        "sort": {"sortBy": "name", "sortOrder": "asc"},
    }
    req = urllib.request.Request(
        market_cfg["scanner_url"],
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=60, context=ctx) as r:
        data = json.loads(r.read())

    out = {}
    suffix = market_cfg["ticker_suffix"]
    for item in data.get("data", []):
        code = item["s"].split(":")[1]
        d = item["d"]
        close, chg_pct, chg_abs = d[1], d[2], d[3]
        if close is None or chg_abs is None:
            continue
        entry = {"close": close, "changeAbs": chg_abs, "changePct": chg_pct}
        out[f"{code}{suffix}"] = entry
        if market_cfg["pad"]:
            out[f"{code.zfill(4)}{suffix}"] = entry
    return out


def verify_portfolio(user_id, data, tv, today):
    snapshots = data.get("snapshots", [])
    snap = next((s for s in snapshots if s["date"] == today), None)
    if not snap:
        return [f"[{user_id}] no snapshot for {today} — cron may have skipped"]

    positions = data.get("positions", [])
    if not positions:
        return []

    issues = []
    closing_prices = snap.get("closingPrices", {})
    price_cache = data.get("priceCache", {})

    # Check 1 + 2: per-ticker closingPrice and changePercent drift
    for p in positions:
        ticker = p["ticker"].replace("b.HK", ".HK")
        tv_e = tv.get(ticker)
        if tv_e is None:
            continue
        stored_close = closing_prices.get(ticker)
        if stored_close is not None and abs(stored_close - tv_e["close"]) > CLOSE_DRIFT:
            issues.append(
                f"[{user_id}] {ticker} closingPrice drift: stored={stored_close} TV={tv_e['close']} "
                f"diff={stored_close - tv_e['close']:+.4f}"
            )
        cached = price_cache.get(ticker, {})
        stored_pct = cached.get("changePercent")
        if stored_pct is not None and abs(stored_pct - tv_e["changePct"]) > PCT_DRIFT:
            issues.append(
                f"[{user_id}] {ticker} priceCache.changePercent drift: stored={stored_pct:.4f}% "
                f"TV={tv_e['changePct']:.4f}% diff={stored_pct - tv_e['changePct']:+.4f}pp"
            )

    # Check 3: dailyPnL vs correct formula
    # Open positions: TV change_abs * qty
    # Closed today:   (exitPrice - yesterday_close) * qty  [session move only]
    # NOT: realized_pnl - yesterday_realized (that overcounts prior sessions' unrealized gains)
    yesterday_snap = next(
        (s for s in sorted(snapshots, key=lambda x: x["date"], reverse=True) if s["date"] < today),
        None,
    )
    yesterday_closing = yesterday_snap.get("closingPrices", {}) if yesterday_snap else {}

    expected_pnl = 0.0
    for p in positions:
        ticker = p["ticker"].replace("b.HK", ".HK")
        tv_e = tv.get(ticker)
        if tv_e is None:
            continue
        if p.get("entryDate") == today:
            expected_pnl += (p.get("currentPrice", 0) - p.get("entryPrice", 0)) * p["quantity"]
        else:
            expected_pnl += tv_e["changeAbs"] * p["quantity"]

    closed_trades = data.get("closedTrades", [])
    for t in closed_trades:
        if t.get("exitDate") != today:
            continue
        ticker_clean = t["ticker"].replace("b.HK", ".HK")
        prev_close = yesterday_closing.get(ticker_clean)
        if prev_close is not None:
            expected_pnl += (t.get("exitPrice", 0) - prev_close) * t.get("quantity", 0)
        elif t.get("entryDate") == today:
            expected_pnl += (t.get("exitPrice", 0) - t.get("entryPrice", 0)) * t.get("quantity", 0)

    stored_pnl = snap.get("dailyPnL", 0)
    if abs(stored_pnl - expected_pnl) > PNL_DRIFT:
        issues.append(
            f"[{user_id}] dailyPnL drift: stored={stored_pnl:+,.2f} expected(TV)={expected_pnl:+,.2f} "
            f"diff={stored_pnl - expected_pnl:+,.2f}"
        )

    # Check 4: sanity cap — dailyPnL > 8% of portfolio value is almost certainly wrong
    portfolio_value = snap.get("portfolioValue", 0)
    if portfolio_value > 0 and abs(stored_pnl) / portfolio_value > 0.08:
        issues.append(
            f"[{user_id}] dailyPnL sanity: {stored_pnl:+,.2f} is {abs(stored_pnl)/portfolio_value*100:.1f}% "
            f"of portfolio {portfolio_value:,.0f} — likely overcount"
        )

    return issues


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in MARKETS:
        print("Usage: verify-daily.py [hk|us]")
        sys.exit(2)
    market = sys.argv[1]
    cfg = MARKETS[market]

    today = datetime.now(cfg["tz"]).strftime("%Y-%m-%d")
    weekday = datetime.now(cfg["tz"]).weekday()
    if weekday >= 5:
        print(f"verify-daily {market}: {today} is a weekend — skip")
        return

    db = init_firebase()
    tv = fetch_tv(cfg)
    if not tv:
        print(f"ERROR: TV scanner ({market}) returned no data — cannot verify")
        sys.exit(2)

    all_issues = []
    for doc in db.collection(cfg["collection"]).stream():
        data = doc.to_dict()
        if not data.get("positions"):
            continue
        all_issues.extend(verify_portfolio(doc.id, data, tv, today))

    if all_issues:
        print(f"=== verify-daily {market.upper()} FAIL — {len(all_issues)} issue(s) on {today} ===")
        for i in all_issues:
            print(" - " + i)
        sys.exit(1)
    print(f"verify-daily {market.upper()} PASS — {today}")


if __name__ == "__main__":
    main()
