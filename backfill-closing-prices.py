#!/usr/bin/env python3
"""
Backfill closingPrices into snapshots that are missing them.
Uses positionsAtClose data when available, or fetches from Yahoo for recent snapshots.
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
import urllib.request

import firebase_admin
from firebase_admin import credentials, firestore

HKT = timezone(timedelta(hours=8))
MARC_UID = "cNcZwUx3nQMV96TbB1kSkQ62u8U2"


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


def fetch_yahoo_history(ticker, days=10):
    """Fetch recent daily closes from Yahoo Finance."""
    clean = ticker.replace("b.HK", ".HK")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{clean}?interval=1d&range={days}d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        print(f"  FAIL {clean}: {e}")
        return {}

    result = data.get("chart", {}).get("result", [None])[0]
    if not result:
        return {}

    timestamps = result.get("timestamp", [])
    closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])

    # Build date -> close price map
    history = {}
    for ts, close in zip(timestamps, closes):
        if close is not None:
            dt = datetime.fromtimestamp(ts, tz=HKT)
            date_str = dt.strftime("%Y-%m-%d")
            history[date_str] = round(close, 4)

    return history


def run():
    db = init_firebase()
    doc_ref = db.document(f"portfolios/{MARC_UID}")
    doc = doc_ref.get()

    if not doc.exists:
        print(f"Document not found")
        sys.exit(1)

    data = doc.to_dict()
    positions = data.get("positions", [])
    snapshots = data.get("snapshots", [])

    print(f"Total snapshots: {len(snapshots)}")

    # Find snapshots missing closingPrices
    missing = [s for s in snapshots if not s.get("closingPrices")]
    print(f"Missing closingPrices: {len(missing)}")

    if not missing:
        print("Nothing to backfill!")
        return

    for s in missing:
        print(f"  {s['date']}: no closingPrices")

    # Strategy 1: Use positionsAtClose if available
    fixed_from_positions = 0
    still_missing = []
    for s in missing:
        pac = s.get("positionsAtClose", [])
        if pac:
            closing_prices = {}
            for p in pac:
                ticker = p["ticker"].replace("b.HK", ".HK")
                closing_prices[ticker] = p.get("closingPrice", p.get("entryPrice", 0))
            s["closingPrices"] = closing_prices
            fixed_from_positions += 1
            print(f"  {s['date']}: filled from positionsAtClose ({len(closing_prices)} tickers)")
        else:
            still_missing.append(s)

    # Strategy 2: Fetch Yahoo history for remaining
    if still_missing:
        print(f"\nFetching Yahoo history for {len(still_missing)} remaining snapshots...")
        # Get all tickers from current positions
        tickers = [p["ticker"] for p in positions]
        print(f"  Tickers: {[t.replace('b.HK', '.HK') for t in tickers]}")

        # Fetch history for each ticker
        ticker_history = {}
        for ticker in tickers:
            clean = ticker.replace("b.HK", ".HK")
            print(f"  Fetching {clean}...")
            ticker_history[clean] = fetch_yahoo_history(ticker, days=30)

        # Fill in missing snapshots
        fixed_from_yahoo = 0
        for s in still_missing:
            date = s["date"]
            closing_prices = {}
            for ticker in tickers:
                clean = ticker.replace("b.HK", ".HK")
                history = ticker_history.get(clean, {})
                if date in history:
                    closing_prices[clean] = history[date]
            if closing_prices:
                s["closingPrices"] = closing_prices
                fixed_from_yahoo += 1
                print(f"  {date}: filled from Yahoo ({len(closing_prices)} tickers)")
            else:
                print(f"  {date}: could not fill (no Yahoo data for this date)")

        print(f"\nFixed from Yahoo: {fixed_from_yahoo}")

    print(f"Fixed from positionsAtClose: {fixed_from_positions}")

    # Save
    doc_ref.update({"snapshots": snapshots})
    print(f"\nSaved to Firestore!")

    # Verify
    still_empty = sum(1 for s in snapshots if not s.get("closingPrices"))
    print(f"Snapshots still missing closingPrices: {still_empty}")


if __name__ == "__main__":
    run()
