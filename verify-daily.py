#!/usr/bin/env python3
"""
Post-cron self-check.

Runs immediately after update.py finishes its daily HK snapshot. For every
portfolio it just touched, it re-pulls TradingView's settlement values and
verifies that today's snapshot agrees with TV.

Three checks, with their thresholds:

  1. Per-ticker closingPrice drift  > 0.02 HKD
  2. Per-ticker changePercent drift > 0.05 percentage points
  3. dailyPnL drift                 > 50 HKD vs sum(TV change_abs * qty)

If anything trips, the script prints a structured FAIL block and exits 1
so the GitHub Actions run is marked red and surfaces in the email/PR feed.
A clean run prints a one-line PASS and exits 0.

This catches the regressions we've been hand-patching all year:
- The Mar 5 incident (cron wrote stale closingPrices/changePercent)
- The Apr 24 incident (dailyPnL diverged from sum(change_abs * qty))
- The 2175.HK-style CAS-vs-settlement drift
- Any future code change that quietly breaks the cron's math
"""

import json
import os
import ssl
import sys
import urllib.request
from datetime import datetime, timezone, timedelta

import firebase_admin
from firebase_admin import credentials, firestore

HKT = timezone(timedelta(hours=8))
CLOSE_DRIFT = 0.02      # HKD
PCT_DRIFT = 0.05        # percentage points
PNL_DRIFT = 50.0        # HKD


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


def fetch_tv():
    """Same Scanner call the cron uses. Returns {ticker: {close, changeAbs, changePct}}."""
    payload = {
        "columns": ["name", "close", "change", "change_abs"],
        "range": [0, 25000],
        "sort": {"sortBy": "name", "sortOrder": "asc"},
    }
    req = urllib.request.Request(
        "https://scanner.tradingview.com/hongkong/scan",
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
    for item in data.get("data", []):
        code = item["s"].split(":")[1]
        d = item["d"]
        close, chg_pct, chg_abs = d[1], d[2], d[3]
        if close is None or chg_abs is None:
            continue
        entry = {"close": close, "changeAbs": chg_abs, "changePct": chg_pct}
        out[f"{code}.HK"] = entry
        out[f"{code.zfill(4)}.HK"] = entry
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

    # Check 1 + 2: per-ticker closingPrice and changePercent drift
    closing_prices = snap.get("closingPrices", {})
    price_cache = data.get("priceCache", {})
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

    # Check 3: dailyPnL vs sum(TV change_abs * qty) + realized delta
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
    # Realized delta vs yesterday
    yesterday_snap = next(
        (s for s in sorted(snapshots, key=lambda x: x["date"], reverse=True) if s["date"] < today),
        None,
    )
    if yesterday_snap:
        expected_pnl += snap.get("realizedPnL", 0) - yesterday_snap.get("realizedPnL", 0)

    stored_pnl = snap.get("dailyPnL", 0)
    if abs(stored_pnl - expected_pnl) > PNL_DRIFT:
        issues.append(
            f"[{user_id}] dailyPnL drift: stored={stored_pnl:+,.2f} expected(TV)={expected_pnl:+,.2f} "
            f"diff={stored_pnl - expected_pnl:+,.2f}"
        )

    return issues


def main():
    today = datetime.now(HKT).strftime("%Y-%m-%d")
    weekday = datetime.now(HKT).weekday()
    if weekday >= 5:
        print(f"verify-daily: {today} is a weekend — skip")
        return

    db = init_firebase()
    tv = fetch_tv()
    if not tv:
        print("ERROR: TV scanner returned no data — cannot verify")
        sys.exit(2)

    all_issues = []
    for doc in db.collection("portfolios").stream():
        data = doc.to_dict()
        if not data.get("positions"):
            continue
        all_issues.extend(verify_portfolio(doc.id, data, tv, today))

    if all_issues:
        print(f"=== verify-daily FAIL — {len(all_issues)} issue(s) on {today} ===")
        for i in all_issues:
            print(" - " + i)
        sys.exit(1)
    print(f"verify-daily PASS — {today}")


if __name__ == "__main__":
    main()
