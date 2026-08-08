#!/usr/bin/env python3
"""
Post-cron self-check.

Runs immediately after update.py / update-us.py finishes its daily snapshot.
For every portfolio it just touched, it re-pulls TradingView's settlement
values and verifies that today's snapshot agrees with TV.

Usage:
    python verify-daily.py hk    # checks the `portfolios` collection
    python verify-daily.py us    # checks the `us-portfolios` collection

Six checks, with their thresholds:

  1. Per-ticker closingPrice drift  > 0.02 in market currency
  2. Per-ticker changePercent drift > 0.05 percentage points
  3. dailyPnL drift                 > 50 in market currency vs sum(TV change_abs * qty)
  4. dailyPnL sanity cap            > 8% of portfolio value
  5. Record completeness            every held position present in today's snapshot
  6. Snapshot self-consistency      totals agree with positionsAtClose  > 1.0

Checks 1-4 validate the ARITHMETIC of what the snapshot records. Checks 5-6 validate
the RECORD ITSELF: that it contains every position held (5), and that its totals agree
with the positions it lists (6). Neither is visible to 1-4, which iterate over
`positions` and `continue` whenever a snapshot lookup misses — a snapshot can be
internally consistent, pass every arithmetic check, and still omit a real holding.
See wiki/snapshot-record-gaps.md.

Ex-dividend aware (mirrors update.py): on a held ticker's ex-div day update.py folds the
dividend into changePercent and the dailyPnL leg (total return), while TV reports only the
raw price gap-down. Checks 2 + 3 re-fold the dividend (read from priceCache.dividendPerShare
/ exDivDate) before comparing, so a legitimate ex-div day is not a false-alarm red run.

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
from zoneinfo import ZoneInfo

from market_calendar import is_trading_day, coverage_warning

CLOSE_DRIFT = 0.02
PCT_DRIFT = 0.05
PNL_DRIFT = 50.0

# Same snapshot-validity window as update.py / update-us.py: before this
# market-local time, either the close hasn't settled or we're a drifted run
# from yesterday's schedule sitting in the next day — skip instead of
# producing a false-alarm red run. Override: ALLOW_OFF_HOURS=1.
WINDOW_START = "16:10"

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
        "tz": ZoneInfo("America/New_York"),  # DST-aware (was fixed UTC-5)
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
        tv_pct = tv_e["changePct"]
        # Ex-dividend day: update.py folds the dividend into changePercent (total return),
        # while TV still reports the raw price-only gap-down. Re-fold the dividend into the
        # TV figure before comparing, else every ex-div day is a false-alarm red run.
        if cached.get("exDivDate") == today and cached.get("dividendPerShare"):
            prev_close = tv_e["close"] - tv_e["changeAbs"]
            if prev_close:
                tv_pct = (tv_e["changeAbs"] + cached["dividendPerShare"]) / prev_close * 100
        if stored_pct is not None and abs(stored_pct - tv_pct) > PCT_DRIFT:
            issues.append(
                f"[{user_id}] {ticker} priceCache.changePercent drift: stored={stored_pct:.4f}% "
                f"TV={tv_pct:.4f}% diff={stored_pct - tv_pct:+.4f}pp"
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
            # Mirror update.py's total-return fold: on an ex-div day the dividend is added
            # back into the daily move, so the dailyPnL leg is (change_abs + dividend) * qty.
            cached = price_cache.get(ticker, {})
            div = cached.get("dividendPerShare", 0) if cached.get("exDivDate") == today else 0
            expected_pnl += (tv_e["changeAbs"] + div) * p["quantity"]

    closed_trades = data.get("closedTrades", [])
    for t in closed_trades:
        if t.get("exitDate") != today:
            continue
        ticker_clean = t["ticker"].replace("b.HK", ".HK")
        # Mirror the cron: prev close = TV close − change_abs (prior trading-day
        # close, gap-proof); stored snapshot close only as fallback.
        tv_e = tv.get(ticker_clean)
        if tv_e is not None:
            prev_close = tv_e["close"] - tv_e["changeAbs"]
        else:
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

    # Check 5: record completeness — every held position must APPEAR in today's snapshot.
    # Checks 1-3 above iterate over `positions` and `continue` whenever the TV or snapshot
    # lookup misses, so a position absent from the snapshot is skipped, not flagged: the
    # snapshot stays internally consistent (pv, cap and posCount all agree with each other)
    # while silently omitting a real holding. 2600.HK was held from 2026-07-23 and missing
    # from 11 consecutive snapshots without tripping any check — its P&L was excluded from
    # dailyPnL every one of those days, and one day's sign was wrong as a result.
    # See wiki/snapshot-record-gaps.md.
    pac = snap.get("positionsAtClose")
    if not pac:
        issues.append(f"[{user_id}] snapshot {today} has no positionsAtClose — cannot confirm completeness")
    else:
        pac_tickers = {q.get("ticker") for q in pac}
        for p in positions:
            ticker = p["ticker"].replace("b.HK", ".HK")
            if p.get("entryDate") and p["entryDate"] > today:
                continue  # future-dated entry, not yet held
            absent = [where for where, keys in
                      (("positionsAtClose", pac_tickers), ("closingPrices", closing_prices))
                      if ticker not in keys]
            if absent:
                issues.append(
                    f"[{user_id}] {ticker} held (entry {p.get('entryDate')}, qty {p.get('quantity')}) "
                    f"but missing from snapshot {today}: {' + '.join(absent)} — "
                    f"its P&L is excluded from dailyPnL"
                )

    # Check 6: snapshot self-consistency (wiki/snapshot-schema.md "Invariants").
    # Distinct from check 5: these catch a snapshot whose totals disagree with its own
    # positionsAtClose — the signature of a partial write or a delta-subtraction patch
    # that skipped capitalEngaged (incidents 2026-06-10). The 2026-08-08 sweep found
    # three historical snapshots in this state (2026-03-31, 2026-04-13, 2026-05-15);
    # on 2026-05-15, positionCount said 16 while positionsAtClose held 13.
    if pac:
        pv_pac = sum(q.get("closingPrice", 0) * q.get("quantity", 0) for q in pac)
        cap_pac = sum(q.get("entryPrice", 0) * q.get("quantity", 0) for q in pac)
        for label, stored, expected in (
            ("portfolioValue", snap.get("portfolioValue", 0), pv_pac),
            ("capitalEngaged", snap.get("capitalEngaged", 0), cap_pac),
            ("unrealizedPnL", snap.get("unrealizedPnL", 0), pv_pac - cap_pac),
        ):
            if abs(stored - expected) > 1.0:
                issues.append(
                    f"[{user_id}] snapshot {today} {label} disagrees with positionsAtClose: "
                    f"stored={stored:,.2f} expected={expected:,.2f} diff={stored - expected:+,.2f}"
                )
        if snap.get("positionCount") != len(pac):
            issues.append(
                f"[{user_id}] snapshot {today} positionCount={snap.get('positionCount')} "
                f"but positionsAtClose holds {len(pac)}"
            )
        orphan = set(closing_prices) - {q.get("ticker") for q in pac}
        if orphan:
            issues.append(
                f"[{user_id}] snapshot {today} has closingPrices with no positionsAtClose entry: "
                f"{sorted(orphan)}"
            )

    return issues


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in MARKETS:
        print("Usage: verify-daily.py [hk|us]")
        sys.exit(2)
    market = sys.argv[1]
    cfg = MARKETS[market]

    now_local = datetime.now(cfg["tz"])
    today = now_local.strftime("%Y-%m-%d")

    warn = coverage_warning(today)
    if warn:
        print(warn)

    # Holiday-aware skip. The old weekend-only check made every HKEX holiday a
    # false-alarm red run ("no snapshot for today") — confirmed on 2026-05-25.
    # False reds train the operator to ignore the only channel that catches
    # real failures.
    if not is_trading_day(today, market):
        print(f"verify-daily {market}: {today} is a weekend/holiday — skip")
        return

    # Same validity window as the updater: a run drifted past market-local
    # midnight must not red-flag the next day's (legitimately absent) snapshot.
    if os.environ.get("ALLOW_OFF_HOURS") != "1" and now_local.strftime("%H:%M") < WINDOW_START:
        print(f"verify-daily {market}: {now_local.strftime('%H:%M')} local is before {WINDOW_START} — "
              "nothing to verify yet, skip")
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
