#!/usr/bin/env python3
"""
Weekly verification: compare Firebase snapshot closingPrices against FinMC/Stooq parquet data.
Flags mismatches > 0.02 HKD and optionally fixes them with cascading dailyPnL recalc.

Usage:
    python verify-weekly.py                 # Fix mismatches and save
    python verify-weekly.py --dry-run       # Preview only, no writes
    python verify-weekly.py --days 14       # Check last 14 days (default: 7)

Designed to run on weekends. Could be a GitHub Action (cron: 0 10 * * 6).
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta

import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore

HKT = timezone(timedelta(hours=8))
COLLECTION = "portfolios"
USER_ID = "cNcZwUx3nQMV96TbB1kSkQ62u8U2"
FINMC_CACHE = os.path.expanduser(
    "~/Documents/MarcOS/TRADING/FinMC screener/FinMC/cache"
)
TOLERANCE = 0.02  # HKD — flag mismatches above this

# Firebase ticker → FinMC parquet ticker (without 0-padding)
TICKER_MAP = {
    "3998.HK": "3998.HK", "2643.HK": "2643.HK", "0285.HK": "285.HK",
    "0564.HK": "564.HK",  "1913.HK": "1913.HK", "0434.HK": "434.HK",
    "0178.HK": "178.HK",  "2175.HK": "2175.HK", "9690.HK": "9690.HK",
    "6826.HK": "6826.HK", "2438.HK": "2438.HK", "0177.HK": "177.HK",
    "3600.HK": "3600.HK", "2510.HK": "2510.HK", "1316.HK": "1316.HK",
    "1361.HK": "1361.HK", "1999.HK": "1999.HK",
}


def init_firebase():
    cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if cred_path and os.path.exists(cred_path):
        cred = credentials.Certificate(cred_path)
    elif os.environ.get("FIREBASE_CREDENTIALS_JSON"):
        cred_json = json.loads(os.environ.get("FIREBASE_CREDENTIALS_JSON"))
        cred = credentials.Certificate(cred_json)
    else:
        print("ERROR: No Firebase credentials found.")
        sys.exit(1)
    firebase_admin.initialize_app(cred)
    return firestore.client()


def load_finmc_prices(tickers, dates):
    """Load closing prices from FinMC parquet files for the given dates.

    Returns: dict of {date_str: {firebase_ticker: close_price}}

    Note: FinMC dates may be off by 1 day (labeled as next trading day).
    We try both the exact date and the next day.
    """
    prices = {}
    for fb_ticker, finmc_ticker in tickers.items():
        parquet_path = os.path.join(FINMC_CACHE, f"{finmc_ticker}_daily_local.parquet")
        if not os.path.exists(parquet_path):
            print(f"  WARNING: Missing parquet for {finmc_ticker}")
            continue

        df = pd.read_parquet(parquet_path)
        # Ensure date column is string
        if "Date" in df.columns:
            df["date_str"] = pd.to_datetime(df["Date"]).dt.strftime("%Y-%m-%d")
        elif "date" in df.columns:
            df["date_str"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        else:
            # Try index
            df["date_str"] = pd.to_datetime(df.index).strftime("%Y-%m-%d")

        close_col = "Close" if "Close" in df.columns else "close"

        for date_str in dates:
            if date_str not in prices:
                prices[date_str] = {}

            row = df[df["date_str"] == date_str]
            if not row.empty:
                prices[date_str][fb_ticker] = float(row[close_col].iloc[0])
            else:
                # Try next trading day (FinMC mislabeling)
                next_day = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
                row2 = df[df["date_str"] == next_day]
                if not row2.empty:
                    prices[date_str][fb_ticker] = float(row2[close_col].iloc[0])

    return prices


def find_previous_snapshot(snapshots, before_date):
    prev = None
    for s in sorted(snapshots, key=lambda x: x["date"]):
        if s["date"] < before_date:
            prev = s
    return prev


def recalc_daily_pnl(snapshot, positions, prev_snapshot, closed_trades, transactions):
    """Recalculate dailyPnL for a snapshot using its (possibly corrected) closing prices."""
    closing_prices = snapshot.get("closingPrices", {})
    date = snapshot["date"]

    realized_pnl = sum(
        (t.get("exitPrice", 0) - t.get("entryPrice", 0)) * t.get("quantity", 0)
        for t in closed_trades
    )

    daily_pnl = 0
    if prev_snapshot:
        prev_closing = prev_snapshot.get("closingPrices", {})
        for p in positions:
            clean = p["ticker"].replace("b.HK", ".HK")
            cur_price = closing_prices.get(clean, 0)
            if p.get("entryDate") == date:
                daily_pnl += (cur_price - p.get("entryPrice", 0)) * p["quantity"]
            else:
                prev_close = prev_closing.get(clean)
                if prev_close is not None:
                    daily_pnl += (cur_price - prev_close) * p["quantity"]
        prev_realized = prev_snapshot.get("realizedPnL", 0)
        daily_pnl += (realized_pnl - prev_realized)
    else:
        capital = sum(p.get("entryPrice", 0) * p["quantity"] for p in positions)
        portfolio_val = sum(
            closing_prices.get(p["ticker"].replace("b.HK", ".HK"), 0) * p["quantity"]
            for p in positions
        )
        daily_pnl = portfolio_val - capital

    return round(daily_pnl, 2)


def run():
    parser = argparse.ArgumentParser(description="Weekly Firebase vs FinMC verification")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, don't write to Firebase")
    parser.add_argument("--days", type=int, default=7, help="Number of days to check (default: 7)")
    args = parser.parse_args()

    print("=== Weekly Portfolio Verification ===")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE (will fix mismatches)'}")
    print(f"Checking last {args.days} days\n")

    db = init_firebase()
    doc_ref = db.collection(COLLECTION).document(USER_ID)
    doc = doc_ref.get()
    if not doc.exists:
        print("ERROR: Document not found")
        sys.exit(1)

    data = doc.to_dict()
    positions = data.get("positions", [])
    snapshots = data.get("snapshots", [])
    closed_trades = data.get("closedTrades", [])
    transactions = data.get("transactions", [])

    snapshots.sort(key=lambda s: s["date"])

    # Determine date range to check
    today = datetime.now(HKT)
    start_date = (today - timedelta(days=args.days)).strftime("%Y-%m-%d")
    end_date = today.strftime("%Y-%m-%d")

    # Filter snapshots in range
    target_snapshots = [s for s in snapshots if start_date <= s["date"] <= end_date]
    if not target_snapshots:
        print(f"No snapshots found between {start_date} and {end_date}")
        return

    target_dates = [s["date"] for s in target_snapshots]
    print(f"Snapshots to verify: {', '.join(target_dates)}\n")

    # Load FinMC prices
    print("Loading FinMC parquet data...")
    finmc_prices = load_finmc_prices(TICKER_MAP, target_dates)
    print(f"  Loaded prices for {len(finmc_prices)} dates\n")

    # Compare
    mismatches = []
    for snap in target_snapshots:
        date = snap["date"]
        fb_closing = snap.get("closingPrices", {})
        finmc_closing = finmc_prices.get(date, {})

        if not finmc_closing:
            print(f"  {date}: No FinMC data available, skipping")
            continue

        date_mismatches = []
        for fb_ticker in fb_closing:
            fb_price = fb_closing[fb_ticker]
            finmc_price = finmc_closing.get(fb_ticker)

            if finmc_price is None:
                continue

            diff = abs(fb_price - finmc_price)
            if diff > TOLERANCE:
                date_mismatches.append({
                    "ticker": fb_ticker,
                    "firebase": fb_price,
                    "finmc": finmc_price,
                    "diff": round(diff, 4),
                })

        if date_mismatches:
            print(f"  {date}: {len(date_mismatches)} MISMATCH(ES)")
            for m in date_mismatches:
                print(f"    {m['ticker']}: Firebase={m['firebase']} vs FinMC={m['finmc']} (diff={m['diff']})")
            mismatches.append({"date": date, "items": date_mismatches})
        else:
            matched = len([t for t in fb_closing if t in finmc_closing])
            print(f"  {date}: OK ({matched} tickers matched)")

    print()

    if not mismatches:
        print("All snapshots match FinMC data. Nothing to fix.")
        return

    print(f"Found mismatches on {len(mismatches)} date(s).\n")

    if args.dry_run:
        print("DRY RUN — no changes written to Firebase.")
        return

    # Fix mismatches
    print("Fixing mismatches...")
    dates_fixed = set()

    for mismatch in mismatches:
        date = mismatch["date"]
        idx = next((i for i, s in enumerate(snapshots) if s["date"] == date), None)
        if idx is None:
            continue

        snap = snapshots[idx]
        finmc_closing = finmc_prices.get(date, {})

        # Replace closing prices with FinMC values
        for item in mismatch["items"]:
            snap["closingPrices"][item["ticker"]] = item["finmc"]

        # Recalculate positionsAtClose
        positions_at_close = []
        current_value = 0
        capital_engaged = 0
        for p in positions:
            clean = p["ticker"].replace("b.HK", ".HK")
            price = snap["closingPrices"].get(clean, p.get("entryPrice", 0))
            entry_price = p.get("entryPrice", 0)
            quantity = p["quantity"]
            market_value = price * quantity
            pnl = (price - entry_price) * quantity
            pnl_pct = ((price - entry_price) / entry_price * 100) if entry_price else 0
            positions_at_close.append({
                "ticker": p["ticker"],
                "name": p.get("name", ""),
                "quantity": quantity,
                "entryPrice": entry_price,
                "entryDate": p.get("entryDate", ""),
                "closingPrice": price,
                "marketValue": round(market_value, 2),
                "pnl": round(pnl, 2),
                "pnlPercent": round(pnl_pct, 2),
            })
            current_value += market_value
            capital_engaged += entry_price * quantity

        snap["positionsAtClose"] = positions_at_close
        snap["portfolioValue"] = round(current_value, 2)
        snap["capitalEngaged"] = round(capital_engaged, 2)
        snap["unrealizedPnL"] = round(current_value - capital_engaged, 2)

        dates_fixed.add(date)
        print(f"  Fixed closingPrices for {date}")

    # Recalculate dailyPnL chain for all affected dates and successors
    all_fixed_dates = sorted(dates_fixed)
    if all_fixed_dates:
        # Start recalculating from the earliest fixed date
        earliest = all_fixed_dates[0]
        for i, snap in enumerate(snapshots):
            if snap["date"] >= earliest:
                prev_snap = snapshots[i - 1] if i > 0 else None
                old_daily = snap.get("dailyPnL", 0)
                snap["dailyPnL"] = recalc_daily_pnl(snap, positions, prev_snap, closed_trades, transactions)
                if abs(old_daily - snap["dailyPnL"]) > 0.01:
                    print(f"  Recalc dailyPnL {snap['date']}: {old_daily} -> {snap['dailyPnL']}")

    # Save
    doc_ref.update({
        "snapshots": snapshots,
        "lastUpdated": firestore.SERVER_TIMESTAMP,
    })
    print(f"\nSaved to Firestore. Fixed {len(dates_fixed)} date(s).")
    print("\n=== Verification complete ===")


if __name__ == "__main__":
    run()
