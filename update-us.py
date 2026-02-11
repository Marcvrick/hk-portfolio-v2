#!/usr/bin/env python3
"""
Daily portfolio updater for US stocks in Firebase Firestore.
Fetches Yahoo Finance prices for all positions, updates priceCache and saves a daily snapshot.
Designed to run via GitHub Actions cron at US market close (16:00 ET = 21:00 UTC).
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
import urllib.request

# Firebase Admin SDK
import firebase_admin
from firebase_admin import credentials, firestore

# Eastern Time (US)
ET = timezone(timedelta(hours=-5))  # EST (note: doesn't account for DST)
COLLECTION = "us-portfolios"


def init_firebase():
    """Initialize Firebase Admin SDK."""
    # Check for credentials file path in environment variable
    cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")

    if cred_path and os.path.exists(cred_path):
        # Use credentials file
        cred = credentials.Certificate(cred_path)
    elif os.environ.get("FIREBASE_CREDENTIALS_JSON"):
        # Use credentials from environment variable (for GitHub Actions)
        cred_json = json.loads(os.environ.get("FIREBASE_CREDENTIALS_JSON"))
        cred = credentials.Certificate(cred_json)
    else:
        print("ERROR: No Firebase credentials found.")
        print("Set GOOGLE_APPLICATION_CREDENTIALS path or FIREBASE_CREDENTIALS_JSON content.")
        sys.exit(1)

    firebase_admin.initialize_app(cred)
    return firestore.client()


def fetch_yahoo_price(ticker: str) -> dict:
    """Fetch price from Yahoo Finance chart API (no CORS needed server-side)."""
    # US tickers don't need cleaning like HK tickers
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=5d"

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        print(f"  FAIL {ticker}: {e}")
        return {"success": False, "error": str(e)}

    result = data.get("chart", {}).get("result", [None])[0]
    if not result:
        print(f"  FAIL {ticker}: no result")
        return {"success": False, "error": "No data"}

    meta = result.get("meta", {})
    price = meta.get("regularMarketPrice")
    if price is None:
        print(f"  FAIL {ticker}: no price")
        return {"success": False, "error": "No price"}

    # Find previousClose: most recent non-null close from BEFORE today (UTC midnight)
    # Uses timestamps to correctly skip today's data, handles null gaps properly
    timestamps = result.get("timestamp", [])
    closes_list = (result.get("indicators", {}).get("quote", [{}])[0].get("close") or [])
    today_utc_start = int(datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    previous_close = None
    for i in range(len(timestamps) - 1, -1, -1):
        if closes_list[i] is not None and timestamps[i] < today_utc_start:
            previous_close = closes_list[i]
            break
    if not previous_close:
        previous_close = meta.get("previousClose") or meta.get("chartPreviousClose") or price

    print(f"  OK {ticker}: {price} (prevClose: {previous_close})")
    return {
        "success": True,
        "price": price,
        "previousClose": previous_close,
        "change": round(price - previous_close, 4),
        "changePercent": round(((price - previous_close) / previous_close) * 100, 4) if previous_close else 0,
        "currency": meta.get("currency", "USD"),
        "lastUpdated": datetime.now(ET).isoformat(),
    }


def update_portfolio(db, doc_ref, user_id: str, today: str):
    """Update a single user's portfolio."""
    print(f"\n--- Updating portfolio for user: {user_id} ---")

    doc = doc_ref.get()
    if not doc.exists:
        print(f"  Document not found, skipping")
        return False

    data = doc.to_dict()

    positions = data.get("positions", [])
    price_cache = data.get("priceCache", {})
    snapshots = data.get("snapshots", [])
    closed_trades = data.get("closedTrades", [])
    transactions = data.get("transactions", [])

    if not positions:
        print("  No positions, skipping")
        return False

    print(f"  Positions: {len(positions)}")

    # 1. Fetch prices
    print("  Fetching prices...")
    for p in positions:
        ticker = p["ticker"].strip().replace(".HK", "").upper()  # Strip whitespace and .HK
        p["ticker"] = ticker  # Fix in-place for Firestore persistence
        result = fetch_yahoo_price(ticker)
        if result["success"]:
            price_cache[ticker] = result
            p["currentPrice"] = result["price"]

    # 2. Calculate snapshot
    current_value = sum(p["quantity"] * p.get("currentPrice", p.get("entryPrice", 0)) for p in positions)
    capital_engaged = sum(p["quantity"] * p.get("entryPrice", 0) for p in positions)
    realized_pnl = sum((t.get("exitPrice", 0) - t.get("entryPrice", 0)) * t.get("quantity", 0) for t in closed_trades)
    total_dividends = sum(t.get("amount", 0) for t in transactions if t.get("type") == "dividend")

    # Build closingPrices map and positionsAtClose for accurate calendar P&L
    closing_prices = {}
    positions_at_close = []
    for p in positions:
        ticker = p["ticker"]
        cur_price = p.get("currentPrice", p.get("entryPrice", 0))
        closing_prices[ticker] = cur_price
        positions_at_close.append({
            "ticker": ticker,
            "name": p.get("name", ""),
            "quantity": p["quantity"],
            "entryPrice": p.get("entryPrice", 0),
            "entryDate": p.get("entryDate", ""),
            "closingPrice": cur_price,
            "marketValue": cur_price * p["quantity"],
            "pnl": (cur_price - p.get("entryPrice", 0)) * p["quantity"],
            "pnlPercent": ((cur_price - p.get("entryPrice", 0)) / p["entryPrice"] * 100) if p.get("entryPrice") else 0,
        })

    # Calculate dailyPnL from yesterday's snapshot closingPrices
    yesterday_snap = None
    for s in sorted(snapshots, key=lambda x: x["date"], reverse=True):
        if s["date"] < today:
            yesterday_snap = s
            break

    daily_pnl = 0
    if yesterday_snap:
        yesterday_closing = yesterday_snap.get("closingPrices", {})
        for p in positions:
            ticker = p["ticker"]
            cur_price = p.get("currentPrice", p.get("entryPrice", 0))
            if p.get("entryDate") == today:
                # Entirely new position added today
                daily_pnl += (cur_price - p.get("entryPrice", 0)) * p["quantity"]
            elif p.get("addedTodayDate") == today and p.get("addedTodayQty", 0) > 0 and p.get("qtyBeforeToday", 0) > 0:
                # Existing position with intraday addition: split calculation
                prev_close = yesterday_closing.get(ticker)
                old_qty = p["qtyBeforeToday"]
                added_qty = p["addedTodayQty"]
                added_price = p.get("addedTodayPrice", 0)
                if prev_close is not None:
                    daily_pnl += (cur_price - prev_close) * old_qty
                daily_pnl += (cur_price - added_price) * added_qty
            else:
                prev_close = yesterday_closing.get(ticker)
                if prev_close is not None:
                    daily_pnl += (cur_price - prev_close) * p["quantity"]
        # Add realized P&L change
        yesterday_realized = yesterday_snap.get("realizedPnL", 0)
        daily_pnl += (realized_pnl - yesterday_realized)
    else:
        # No yesterday snapshot: use unrealized P&L as approximation
        daily_pnl = round(current_value - capital_engaged, 2)

    snapshot = {
        "date": today,
        "capitalEngaged": round(capital_engaged, 2),
        "portfolioValue": round(current_value, 2),
        "unrealizedPnL": round(current_value - capital_engaged, 2),
        "realizedPnL": round(realized_pnl, 2),
        "totalDividends": round(total_dividends, 2),
        "positionCount": len(positions),
        "closingPrices": closing_prices,
        "dailyPnL": round(daily_pnl, 2),
        "positionsAtClose": positions_at_close,
    }

    # Replace today's snapshot if exists, otherwise append
    existing_idx = next((i for i, s in enumerate(snapshots) if s["date"] == today), None)
    if existing_idx is not None:
        snapshots[existing_idx] = snapshot
        print(f"  Updated existing snapshot for {today}")
    else:
        snapshots.append(snapshot)
        snapshots.sort(key=lambda s: s["date"])
        print(f"  New snapshot for {today}")

    print(f"  Value: ${current_value:,.0f} | Capital: ${capital_engaged:,.0f} | P&L: ${current_value - capital_engaged:,.0f}")

    # Clean up intraday addition fields (no longer needed after snapshot)
    for p in positions:
        for field in ["addedTodayDate", "addedTodayQty", "addedTodayPrice", "qtyBeforeToday"]:
            p.pop(field, None)

    # 3. Save to Firestore
    update_data = {
        "priceCache": price_cache,
        "positions": positions,
        "snapshots": snapshots,
        "lastUpdated": firestore.SERVER_TIMESTAMP,
    }

    doc_ref.update(update_data)
    print(f"  Saved to Firestore ({len(snapshots)} snapshots)")
    return True


def run():
    # Initialize Firestore
    print("Connecting to Firestore...")
    db = init_firebase()

    today = datetime.now(ET).strftime("%Y-%m-%d")
    print(f"=== US Portfolio Update {today} ===")

    # Get all user portfolios in the us-portfolios collection
    collection_ref = db.collection(COLLECTION)
    docs = collection_ref.stream()

    updated_count = 0
    for doc in docs:
        user_id = doc.id
        doc_ref = collection_ref.document(user_id)
        if update_portfolio(db, doc_ref, user_id, today):
            updated_count += 1

    print(f"\n=== Done: Updated {updated_count} portfolio(s) ===")


if __name__ == "__main__":
    run()
