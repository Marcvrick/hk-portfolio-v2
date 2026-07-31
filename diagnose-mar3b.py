#!/usr/bin/env python3
"""
Targeted diagnostic: Dump Mar 2 snapshot closingPrices vs Mar 3 Yahoo previousClose.
Also fetch actual Mar 2 closes from Yahoo directly.
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
import urllib.request

import firebase_admin
from firebase_admin import credentials, firestore

HKT = timezone(timedelta(hours=8))
USER_ID = "cNcZwUx3nQMV96TbB1kSkQ62u8U2"

TICKERS = [
    "3998.HK", "2643.HK", "0285.HK", "0564.HK", "1913.HK", "0434.HK",
    "0178.HK", "2175.HK", "9690.HK", "6826.HK", "2438.HK", "0177.HK",
    "3600.HK", "2510.HK", "1316.HK", "1361.HK", "1999.HK",
]


def fetch_yahoo_history(ticker, days=10):
    """Fetch daily OHLC from Yahoo for last N days."""
    clean = ticker.replace("0285", "285").replace("0564", "564").replace("0434", "434").replace("0178", "178").replace("0177", "177")
    # Actually Yahoo uses 4-digit format for HK stocks
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range={days}d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        return {}

    result = data.get("chart", {}).get("result", [None])[0]
    if not result:
        return {}

    timestamps = result.get("timestamp", [])
    quotes = result.get("indicators", {}).get("quote", [{}])[0]
    closes = quotes.get("close", [])
    opens = quotes.get("open", [])
    highs = quotes.get("high", [])
    lows = quotes.get("low", [])

    history = {}
    for i, ts in enumerate(timestamps):
        dt = datetime.fromtimestamp(ts, tz=HKT)
        date_str = dt.strftime("%Y-%m-%d")
        c = closes[i] if i < len(closes) else None
        if c is not None:
            history[date_str] = round(c, 4)

    return history


def init_firebase():
    cred_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "hk-portfolio-v2",
        "hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json"
    )
    cred = credentials.Certificate(cred_path)
    firebase_admin.initialize_app(cred)
    return firestore.client()


def run():
    print("=" * 70)
    print("TARGETED DIAGNOSTIC: Mar 2 snapshot + Yahoo history")
    print("=" * 70)

    # Load Firebase
    db = init_firebase()
    doc = db.document(f"portfolios/{USER_ID}").get()
    data = doc.to_dict()
    snapshots = {s["date"]: s for s in data.get("snapshots", [])}
    price_cache = data.get("priceCache", {})

    # Get snapshots
    snap_feb27 = snapshots.get("2026-02-27", {})
    snap_mar02 = snapshots.get("2026-03-02", {})
    snap_mar03 = snapshots.get("2026-03-03", {})

    cp_feb27 = snap_feb27.get("closingPrices", {})
    cp_mar02 = snap_mar02.get("closingPrices", {})
    cp_mar03 = snap_mar03.get("closingPrices", {})

    print(f"\nFeb 27 snapshot: value={snap_feb27.get('portfolioValue')}, dailyPnL={snap_feb27.get('dailyPnL')}")
    print(f"Mar 02 snapshot: value={snap_mar02.get('portfolioValue')}, dailyPnL={snap_mar02.get('dailyPnL')}")
    print(f"Mar 03 snapshot: value={snap_mar03.get('portfolioValue')}, dailyPnL={snap_mar03.get('dailyPnL')}")

    # Fetch Yahoo history for all tickers
    print(f"\nFetching Yahoo 10d history for all tickers...")
    yahoo = {}
    for ticker in TICKERS:
        hist = fetch_yahoo_history(ticker, 10)
        yahoo[ticker] = hist
        dates_str = ", ".join(f"{d}:{p}" for d, p in sorted(hist.items()) if d >= "2026-02-25")
        print(f"  {ticker}: {dates_str}")

    # Compare
    print("\n" + "=" * 70)
    print("COMPARISON TABLE: Feb 27, Mar 2, Mar 3")
    print("=" * 70)
    print(f"{'Ticker':<10} {'Feb27-snap':>10} {'Feb27-yahoo':>11} {'Mar02-snap':>10} {'Mar02-yahoo':>11} {'Mar03-snap':>10} {'Mar03-yahoo':>11} {'prevClose':>10}")
    print("-" * 90)

    for ticker in TICKERS:
        f27s = cp_feb27.get(ticker, "—")
        f27y = yahoo.get(ticker, {}).get("2026-02-27", "—")
        m02s = cp_mar02.get(ticker, "—")
        m02y = yahoo.get(ticker, {}).get("2026-03-02", "—")
        m03s = cp_mar03.get(ticker, "—")
        m03y = yahoo.get(ticker, {}).get("2026-03-03", "—")
        pc = price_cache.get(ticker, {}).get("previousClose", "—")
        if isinstance(pc, float):
            pc = round(pc, 2)

        print(f"{ticker:<10} {str(f27s):>10} {str(f27y):>11} {str(m02s):>10} {str(m02y):>11} {str(m03s):>10} {str(m03y):>11} {str(pc):>10}")

    # Check: does Mar 2 snapshot closingPrices == Yahoo Mar 2 close?
    print("\n" + "=" * 70)
    print("VALIDATION: Mar 2 snapshot vs Yahoo Mar 2 close")
    print("=" * 70)
    for ticker in TICKERS:
        m02s = cp_mar02.get(ticker)
        m02y = yahoo.get(ticker, {}).get("2026-03-02")
        if m02s is not None and m02y is not None:
            diff = abs(m02s - m02y)
            status = "✓" if diff < 0.02 else f"✗ diff={diff:.2f}"
            print(f"  {ticker}: snap={m02s} yahoo={m02y} {status}")
        elif m02y is None:
            print(f"  {ticker}: snap={m02s} yahoo=NO DATA (market closed on Mar 2?)")
        else:
            print(f"  {ticker}: snap=MISSING yahoo={m02y}")

    # Check: does priceCache previousClose match Mar 2 snapshot closingPrices?
    print("\n" + "=" * 70)
    print("VALIDATION: priceCache previousClose vs Mar 2 snapshot closingPrices")
    print("=" * 70)
    for ticker in TICKERS:
        pc = price_cache.get(ticker, {}).get("previousClose")
        m02s = cp_mar02.get(ticker)
        if pc is not None and m02s is not None:
            diff = abs(pc - m02s)
            status = "✓" if diff < 0.02 else f"✗ diff={diff:.2f}"
            print(f"  {ticker}: prevClose={round(pc, 4)} mar02snap={m02s} {status}")


if __name__ == "__main__":
    run()
