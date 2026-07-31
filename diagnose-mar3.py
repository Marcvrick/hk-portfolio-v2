#!/usr/bin/env python3
"""
Diagnostic: Read Firebase snapshots + priceCache, compare with FinMC parquet data.
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import firebase_admin
from firebase_admin import credentials, firestore
import pandas as pd

HKT = timezone(timedelta(hours=8))
USER_ID = "cNcZwUx3nQMV96TbB1kSkQ62u8U2"
CACHE_DIR = Path("/Users/mc/Documents/MarcOS/TRADING/FinMC screener/FinMC/cache")

# Firebase ticker -> FinMC parquet filename
TICKER_MAP = {
    "3998.HK": "3998.HK", "2643.HK": "2643.HK", "0285.HK": "285.HK",
    "0564.HK": "564.HK", "1913.HK": "1913.HK", "0434.HK": "434.HK",
    "0178.HK": "178.HK", "2175.HK": "2175.HK", "9690.HK": "9690.HK",
    "6826.HK": "6826.HK", "2438.HK": "2438.HK", "0177.HK": "177.HK",
    "3600.HK": "3600.HK", "2510.HK": "2510.HK", "1316.HK": "1316.HK",
    "1361.HK": "1361.HK", "1999.HK": "1999.HK",
}


def load_finmc():
    """Load recent closes from FinMC parquet files."""
    data = {}
    for fb_ticker, finmc_ticker in TICKER_MAP.items():
        path = CACHE_DIR / f"{finmc_ticker}_daily_local.parquet"
        if not path.exists():
            print(f"  WARNING: {path.name} not found")
            continue
        df = pd.read_parquet(path)
        # Last 10 trading days
        recent = df.tail(10)
        prices = {}
        for idx, row in recent.iterrows():
            date_str = idx.strftime("%Y-%m-%d") if hasattr(idx, 'strftime') else str(idx)[:10]
            prices[date_str] = round(float(row["Close"]), 4)
        data[fb_ticker] = prices
    return data


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
    print("DIAGNOSTIC — Firebase vs FinMC")
    print("=" * 70)

    # 1. Load FinMC truth data
    print("\n[1] Loading FinMC parquet data...")
    finmc = load_finmc()
    # Show available trading dates
    all_dates = set()
    for prices in finmc.values():
        all_dates.update(prices.keys())
    recent_dates = sorted(d for d in all_dates if d >= "2026-02-20")
    print(f"  FinMC trading dates (recent): {recent_dates}")

    # 2. Load Firebase data
    print("\n[2] Loading Firebase data...")
    db = init_firebase()
    doc = db.document(f"portfolios/{USER_ID}").get()
    data = doc.to_dict()

    positions = data.get("positions", [])
    price_cache = data.get("priceCache", {})
    snapshots = sorted(data.get("snapshots", []), key=lambda s: s["date"])

    print(f"  Positions: {len(positions)}")
    print(f"  Total snapshots: {len(snapshots)}")

    # 3. List all tickers in portfolio
    portfolio_tickers = [p["ticker"].replace("b.HK", ".HK") for p in positions]
    print(f"  Portfolio tickers: {portfolio_tickers}")

    # 4. Show recent snapshots
    print("\n" + "=" * 70)
    print("RECENT SNAPSHOTS (last 10)")
    print("=" * 70)
    for snap in snapshots[-10:]:
        d = snap["date"]
        pv = snap.get("portfolioValue", "?")
        dpnl = snap.get("dailyPnL", "?")
        cp = snap.get("closingPrices", {})
        n_prices = len(cp)
        print(f"\n  {d} | value={pv} | dailyPnL={dpnl} | closingPrices={n_prices} tickers")

        # Compare closingPrices with FinMC
        if cp:
            mismatches = 0
            for fb_ticker, snap_price in sorted(cp.items()):
                finmc_price = finmc.get(fb_ticker, {}).get(d)
                if finmc_price is not None:
                    diff = abs(snap_price - finmc_price)
                    if diff > 0.02:
                        print(f"    MISMATCH {fb_ticker}: snapshot={snap_price} vs FinMC={finmc_price} (diff={diff:.2f})")
                        mismatches += 1
                else:
                    # Check if FinMC has data for this date at all
                    has_any = d in all_dates
                    if has_any:
                        print(f"    MISSING  {fb_ticker}: snapshot={snap_price}, FinMC has no data for this ticker on {d}")
            if mismatches == 0:
                print(f"    All closingPrices match FinMC ✓")

    # 5. Price Cache vs FinMC
    print("\n" + "=" * 70)
    print("PRICE CACHE (current live data)")
    print("=" * 70)
    today = "2026-03-03"
    for fb_ticker in sorted(portfolio_tickers):
        cached = price_cache.get(fb_ticker, {})
        if not cached:
            print(f"  {fb_ticker}: NOT IN CACHE")
            continue
        cp = cached.get("price", "?")
        pc = cached.get("previousClose", "?")
        upd = str(cached.get("lastUpdated", "?"))[:16]
        finmc_today = finmc.get(fb_ticker, {}).get(today, "N/A")

        # Find previous trading day in FinMC
        finmc_dates = sorted(finmc.get(fb_ticker, {}).keys())
        prev_dates = [dd for dd in finmc_dates if dd < today]
        finmc_prev = finmc[fb_ticker][prev_dates[-1]] if prev_dates else "N/A"
        prev_date = prev_dates[-1] if prev_dates else "?"

        price_ok = "✓" if finmc_today != "N/A" and isinstance(cp, (int, float)) and abs(cp - finmc_today) < 0.02 else "✗"
        prev_ok = "✓" if finmc_prev != "N/A" and isinstance(pc, (int, float)) and abs(pc - finmc_prev) < 0.02 else "✗"

        print(f"  {fb_ticker}: price={cp} {price_ok} (FinMC={finmc_today}) | prevClose={pc} {prev_ok} (FinMC {prev_date}={finmc_prev}) | updated={upd}")

    # 6. Positions detail
    print("\n" + "=" * 70)
    print("POSITIONS")
    print("=" * 70)
    for p in positions:
        ticker = p["ticker"].replace("b.HK", ".HK")
        qty = p.get("quantity", "?")
        entry = p.get("entryPrice", "?")
        cur = p.get("currentPrice", "?")
        print(f"  {ticker}: qty={qty} entry={entry} currentPrice={cur}")


if __name__ == "__main__":
    run()
