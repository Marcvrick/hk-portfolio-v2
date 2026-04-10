#!/usr/bin/env python3
"""
One-time patch: Create missing April 7, 2026 snapshot.
April 7 was incorrectly listed as HKEX holiday (Easter Monday = April 6, not 7).
No snapshot was taken. This script fetches Apr 7 closing prices from Stooq
and creates a proper snapshot with correct dailyPnL (vs Apr 2 closing prices).
"""

import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta

import urllib.request

import firebase_admin
from firebase_admin import credentials, firestore

HKT = timezone(timedelta(hours=8))
COLLECTION = "portfolios"
USER_ID = "cNcZwUx3nQMV96TbB1kSkQ62u8U2"
TARGET_DATE = "2026-04-07"
PREV_DATE = "2026-04-02"   # last snapshot before the Easter break


def init_firebase():
    cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if cred_path and os.path.exists(cred_path):
        cred = credentials.Certificate(cred_path)
    elif os.environ.get("FIREBASE_CREDENTIALS_JSON"):
        cred = credentials.Certificate(json.loads(os.environ["FIREBASE_CREDENTIALS_JSON"]))
    else:
        # Try local service account key next to this script
        local_key = os.path.join(os.path.dirname(__file__), "hk-portfolio-v2", "hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json")
        if os.path.exists(local_key):
            cred = credentials.Certificate(local_key)
        else:
            print("ERROR: No Firebase credentials found.")
            print("  Set GOOGLE_APPLICATION_CREDENTIALS or place the service account JSON next to this script.")
            sys.exit(1)
    firebase_admin.initialize_app(cred)
    return firestore.client()


def fetch_yahoo_close(ticker_hk: str, date_str: str) -> float | None:
    """
    Fetch closing price for a HK ticker on a specific date from Yahoo Finance.
    Uses range=15d endpoint (returns recent history) then looks up the target date in HKT.
    ticker_hk: e.g. '0700.HK'
    date_str: 'YYYY-MM-DD'
    """
    clean = ticker_hk.replace("b.HK", ".HK")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{clean}?interval=1d&range=15d"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode())
        result = data["chart"]["result"][0]
        timestamps = result.get("timestamp", [])
        closes     = result["indicators"]["quote"][0].get("close", [])
        for ts, close in zip(timestamps, closes):
            if close is None:
                continue
            dt = datetime.fromtimestamp(ts, tz=HKT)
            if dt.strftime("%Y-%m-%d") == date_str:
                return round(close, 4)
        return None
    except Exception as e:
        print(f"  WARN: Yahoo fetch failed for {ticker_hk}: {e}")
        return None


def run():
    print(f"=== Patching HK Portfolio: insert {TARGET_DATE} snapshot ===\n")
    db = init_firebase()

    doc_ref = db.collection(COLLECTION).document(USER_ID)
    doc = doc_ref.get()
    if not doc.exists:
        print("ERROR: Firestore document not found.")
        sys.exit(1)

    data = doc.to_dict()
    snapshots   = data.get("snapshots", [])
    closed_trades = data.get("closedTrades", [])
    transactions  = data.get("transactions", [])

    # --- Warn if snapshot already exists (we will overwrite with correct prices) ----
    existing = next((s for s in snapshots if s["date"] == TARGET_DATE), None)
    if existing:
        print(f"Snapshot for {TARGET_DATE} exists (dailyPnL={existing.get('dailyPnL')}) — will overwrite with correct prices.")

    # --- Find Apr 2 snapshot (previous close reference) -------------------
    prev_snap = next((s for s in sorted(snapshots, key=lambda x: x["date"], reverse=True)
                      if s["date"] == PREV_DATE), None)
    if not prev_snap:
        # Fallback: latest snapshot strictly before TARGET_DATE
        prev_snap = next((s for s in sorted(snapshots, key=lambda x: x["date"], reverse=True)
                          if s["date"] < TARGET_DATE), None)
    if not prev_snap:
        print("ERROR: No snapshot found before April 7.")
        sys.exit(1)
    print(f"Previous snapshot: {prev_snap['date']}")

    prev_closing = prev_snap.get("closingPrices", {})
    positions_at_prev = prev_snap.get("positionsAtClose", [])
    if not positions_at_prev:
        print("ERROR: positionsAtClose missing in previous snapshot.")
        sys.exit(1)

    # --- Fetch Apr 7 closing prices from Stooq ----------------------------
    print(f"\nFetching {TARGET_DATE} closing prices from Yahoo Finance...")
    apr7_prices = {}
    for pos in positions_at_prev:
        ticker = pos["ticker"].replace("b.HK", ".HK")
        print(f"  {ticker} ...", end=" ", flush=True)
        price = fetch_yahoo_close(ticker, TARGET_DATE)
        if price is not None:
            apr7_prices[ticker] = price
            print(f"{price}")
        else:
            # Fallback: use previous close (flat day, 0 P&L contribution)
            fallback = prev_closing.get(ticker)
            if fallback:
                apr7_prices[ticker] = fallback
                print(f"MISSING → using prev close {fallback}")
            else:
                print("MISSING → skipped")
        time.sleep(0.3)   # polite rate limit

    # --- Calculate portfolio values at Apr 7 close ------------------------
    realized_pnl = sum(
        (t.get("exitPrice", 0) - t.get("entryPrice", 0)) * t.get("quantity", 0)
        for t in closed_trades
        if t.get("exitDate", "") <= TARGET_DATE
    )
    total_dividends = sum(
        t.get("amount", 0) for t in transactions
        if t.get("type") == "dividend" and t.get("date", "") <= TARGET_DATE
    )

    capital_engaged = sum(pos["quantity"] * pos.get("entryPrice", 0) for pos in positions_at_prev)
    current_value   = sum(
        pos["quantity"] * apr7_prices.get(pos["ticker"].replace("b.HK", ".HK"), pos.get("closingPrice", pos.get("entryPrice", 0)))
        for pos in positions_at_prev
    )
    unrealized_pnl = current_value - capital_engaged

    # --- Calculate daily P&L (Apr 7 vs Apr 2) -----------------------------
    daily_pnl = 0.0
    positions_at_close = []
    for pos in positions_at_prev:
        clean = pos["ticker"].replace("b.HK", ".HK")
        qty = pos["quantity"]
        entry_price = pos.get("entryPrice", 0)
        entry_date  = pos.get("entryDate", "")
        apr7_close  = apr7_prices.get(clean)

        if apr7_close is None:
            positions_at_close.append({**pos, "closingPrice": pos.get("closingPrice", entry_price)})
            continue

        if entry_date == TARGET_DATE:
            daily_pnl += (apr7_close - entry_price) * qty
        else:
            prev_close = prev_closing.get(clean)
            if prev_close is not None:
                daily_pnl += (apr7_close - prev_close) * qty

        market_value = apr7_close * qty
        positions_at_close.append({
            "ticker":      pos["ticker"],
            "name":        pos.get("name", ""),
            "quantity":    qty,
            "entryPrice":  entry_price,
            "entryDate":   entry_date,
            "closingPrice": apr7_close,
            "marketValue": round(market_value, 2),
            "pnl":         round((apr7_close - entry_price) * qty, 2),
            "pnlPercent":  round((apr7_close - entry_price) / entry_price * 100, 2) if entry_price else 0,
        })

    # Add realized P&L delta vs previous snapshot
    prev_realized = prev_snap.get("realizedPnL", 0)
    daily_pnl += (realized_pnl - prev_realized)

    closing_prices = {pos["ticker"].replace("b.HK", ".HK"): apr7_prices[pos["ticker"].replace("b.HK", ".HK")]
                      for pos in positions_at_prev
                      if pos["ticker"].replace("b.HK", ".HK") in apr7_prices}

    snapshot = {
        "date":            TARGET_DATE,
        "capitalEngaged":  round(capital_engaged, 2),
        "portfolioValue":  round(current_value, 2),
        "unrealizedPnL":   round(unrealized_pnl, 2),
        "realizedPnL":     round(realized_pnl, 2),
        "totalDividends":  round(total_dividends, 2),
        "positionCount":   len(positions_at_prev),
        "closingPrices":   closing_prices,
        "dailyPnL":        round(daily_pnl, 2),
        "positionsAtClose": positions_at_close,
    }

    print(f"\n--- Apr 7 Snapshot ---")
    print(f"  Portfolio value : {current_value:>12,.0f} HKD")
    print(f"  Capital engaged : {capital_engaged:>12,.0f} HKD")
    print(f"  Unrealized P&L  : {unrealized_pnl:>12,.0f} HKD")
    print(f"  Daily P&L       : {daily_pnl:>12,.0f} HKD")
    print(f"  Positions       : {len(positions_at_close)}")

    confirm = input("\nInsert this snapshot into Firebase? [y/N] ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        sys.exit(0)

    snapshots = [s for s in snapshots if s["date"] != TARGET_DATE]
    snapshots.append(snapshot)
    snapshots.sort(key=lambda s: s["date"])
    doc_ref.update({
        "snapshots":   snapshots,
        "lastUpdated": firestore.SERVER_TIMESTAMP,
    })
    print(f"\n✓ Snapshot {TARGET_DATE} inserted successfully.")
    print("=== Done ===")


if __name__ == "__main__":
    run()
