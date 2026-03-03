#!/usr/bin/env python3
"""
Daily portfolio updater for Firebase Firestore.
Fetches TradingView prices for all positions, updates priceCache and saves a daily snapshot.
Designed to run via GitHub Actions cron at HK market close (16:30 HKT = 08:30 UTC).
"""

import json
import os
import ssl
import sys
from datetime import datetime, timezone, timedelta
import urllib.request

# Firebase Admin SDK
import firebase_admin
from firebase_admin import credentials, firestore

HKT = timezone(timedelta(hours=8))
COLLECTION = "portfolios"

# HKEX Market Holidays (market fully closed)
# Source: https://www.hkex.com.hk/-/media/HKEX-Market/Services/Circulars-and-Notices/Participant-and-Members-Circulars/SEHK/2025/ce_SEHK_CT_075_2025.pdf
HKEX_HOLIDAYS = {
    '2025-01-01', '2025-01-29', '2025-01-30', '2025-01-31',
    '2025-04-04', '2025-04-18', '2025-04-21', '2025-05-01',
    '2025-05-05', '2025-05-31', '2025-07-01', '2025-10-01',
    '2025-10-07', '2025-12-25', '2025-12-26',
    '2026-01-01', '2026-02-17', '2026-02-18', '2026-02-19',
    '2026-04-03', '2026-04-06', '2026-04-07', '2026-05-01',
    '2026-05-25', '2026-06-19', '2026-07-01', '2026-10-01',
    '2026-10-19', '2026-12-25',
}


def is_trading_day(date_str):
    """Check if a date is a HKEX trading day (not weekend, not holiday)."""
    d = datetime.strptime(date_str, "%Y-%m-%d")
    if d.weekday() >= 5:  # Saturday or Sunday
        return False
    return date_str not in HKEX_HOLIDAYS


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


def fetch_tradingview_prices():
    """Fetch all HKEX prices in one bulk call via TradingView Scanner API.

    Returns dict: { "1913.HK": close_price, "0285.HK": close_price, ... }
    TradingView returns codes without zero-padding (e.g. "285"),
    so we store both padded and unpadded versions for flexible lookup.
    """
    payload = {
        "columns": ["name", "open", "high", "low", "close", "volume"],
        "range": [0, 25000],
        "sort": {"sortBy": "name", "sortOrder": "asc"},
    }
    req = urllib.request.Request(
        "https://scanner.tradingview.com/hongkong/scan",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"  FAIL TradingView bulk fetch: {e}")
        return {}

    prices = {}
    skipped = 0
    for item in data.get("data", []):
        parts = item["s"].split(":")
        code = parts[1]  # e.g. "1913"
        d = item["d"]
        close = d[4]
        if close is None:
            skipped += 1
            continue
        # Store as both "1913.HK" and "01913.HK" (zero-padded to 4 digits) for flexible lookup
        ticker_raw = f"{code}.HK"
        ticker_padded = f"{code.zfill(4)}.HK"
        prices[ticker_raw] = close
        prices[ticker_padded] = close

    total = data.get("totalCount", len(prices) // 2)
    if skipped:
        print(f"  Skipped {skipped} tickers with no close price")
    print(f"  TradingView: {total} HK tickers fetched")
    return prices


# --- Yahoo Finance (disabled, kept as fallback) ---
# def fetch_yahoo_price(ticker: str) -> dict:
#     """Fetch price from Yahoo Finance chart API (no CORS needed server-side)."""
#     clean = ticker.replace("b.HK", ".HK")
#     url = f"https://query1.finance.yahoo.com/v8/finance/chart/{clean}?interval=1d&range=5d"
#     req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
#     try:
#         with urllib.request.urlopen(req, timeout=15) as resp:
#             data = json.loads(resp.read().decode())
#     except Exception as e:
#         return {"success": False, "error": str(e)}
#     result = data.get("chart", {}).get("result", [None])[0]
#     if not result:
#         return {"success": False, "error": "No data"}
#     meta = result.get("meta", {})
#     price = meta.get("regularMarketPrice")
#     if price is None:
#         return {"success": False, "error": "No price"}
#     timestamps = result.get("timestamp", [])
#     closes_list = (result.get("indicators", {}).get("quote", [{}])[0].get("close") or [])
#     today_utc_start = int(datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
#     previous_close = None
#     for i in range(len(timestamps) - 1, -1, -1):
#         if closes_list[i] is not None and timestamps[i] < today_utc_start:
#             previous_close = closes_list[i]
#             break
#     if not previous_close:
#         previous_close = meta.get("previousClose") or meta.get("chartPreviousClose") or price
#     return {
#         "success": True, "price": price, "previousClose": previous_close,
#         "change": round(price - previous_close, 4),
#         "changePercent": round(((price - previous_close) / previous_close) * 100, 4) if previous_close else 0,
#         "currency": meta.get("currency", "HKD"),
#         "lastUpdated": datetime.now(HKT).isoformat(),
#     }


def update_portfolio(db, doc_ref, user_id: str, today: str, tv_prices: dict):
    """Update a single user's portfolio using TradingView prices."""
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

    # Get yesterday's closingPrices for previousClose calculation
    yesterday_closing = {}
    for s in sorted(snapshots, key=lambda x: x["date"], reverse=True):
        if s["date"] < today:
            yesterday_closing = s.get("closingPrices", {})
            break

    # 1. Match TradingView prices to portfolio positions
    print("  Matching TradingView prices...")
    matched = 0
    for p in positions:
        ticker = p["ticker"]
        clean = ticker.replace("b.HK", ".HK")
        # Try direct lookup (handles both "1913.HK" and "0285.HK" via padded keys)
        price = tv_prices.get(clean)
        if price is None:
            print(f"  MISS {clean}: not found in TradingView data")
            continue
        prev_close = yesterday_closing.get(clean, price)
        price_cache[clean] = {
            "success": True,
            "price": price,
            "previousClose": prev_close,
            "change": round(price - prev_close, 4),
            "changePercent": round(((price - prev_close) / prev_close) * 100, 4) if prev_close else 0,
            "currency": "HKD",
            "lastUpdated": datetime.now(HKT).isoformat(),
        }
        p["currentPrice"] = price
        matched += 1
        print(f"  OK {clean}: {price} (prevClose: {prev_close})")
    print(f"  Matched {matched}/{len(positions)} positions")

    # 2. Calculate snapshot
    current_value = sum(p["quantity"] * p.get("currentPrice", p.get("entryPrice", 0)) for p in positions)
    capital_engaged = sum(p["quantity"] * p.get("entryPrice", 0) for p in positions)
    realized_pnl = sum((t.get("exitPrice", 0) - t.get("entryPrice", 0)) * t.get("quantity", 0) for t in closed_trades)
    total_dividends = sum(t.get("amount", 0) for t in transactions if t.get("type") == "dividend")

    # Build closingPrices map and positionsAtClose for accurate calendar P&L
    closing_prices = {}
    positions_at_close = []
    for p in positions:
        clean = p["ticker"].replace("b.HK", ".HK")
        cur_price = p.get("currentPrice", p.get("entryPrice", 0))
        closing_prices[clean] = cur_price
        positions_at_close.append({
            "ticker": p["ticker"],
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
            clean = p["ticker"].replace("b.HK", ".HK")
            cur_price = p.get("currentPrice", p.get("entryPrice", 0))
            if p.get("entryDate") == today:
                # Entirely new position added today
                daily_pnl += (cur_price - p.get("entryPrice", 0)) * p["quantity"]
            elif p.get("addedTodayDate") == today and p.get("addedTodayQty", 0) > 0 and p.get("qtyBeforeToday", 0) > 0:
                # Existing position with intraday addition: split calculation
                prev_close = yesterday_closing.get(clean)
                old_qty = p["qtyBeforeToday"]
                added_qty = p["addedTodayQty"]
                added_price = p.get("addedTodayPrice", 0)
                if prev_close is not None:
                    daily_pnl += (cur_price - prev_close) * old_qty
                daily_pnl += (cur_price - added_price) * added_qty
            else:
                prev_close = yesterday_closing.get(clean)
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

    print(f"  Value: {current_value:,.0f} HKD | Capital: {capital_engaged:,.0f} HKD | P&L: {current_value - capital_engaged:,.0f} HKD")

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

    today = datetime.now(HKT).strftime("%Y-%m-%d")
    print(f"=== HK Portfolio Update {today} ===")

    if not is_trading_day(today):
        weekday = datetime.strptime(today, "%Y-%m-%d").strftime("%A")
        reason = "holiday" if today in HKEX_HOLIDAYS else "weekend"
        print(f"  Skipping — {weekday} {today} is a {reason} (HKEX closed)")
        print("=== Done: No updates ===")
        return

    # Fetch all HKEX prices in one bulk call
    print("Fetching TradingView HKEX prices...")
    tv_prices = fetch_tradingview_prices()
    if not tv_prices:
        print("ERROR: No prices from TradingView — aborting")
        return

    # Get all user portfolios in the portfolios collection
    collection_ref = db.collection(COLLECTION)
    docs = collection_ref.stream()

    updated_count = 0
    for doc in docs:
        user_id = doc.id
        doc_ref = collection_ref.document(user_id)
        if update_portfolio(db, doc_ref, user_id, today, tv_prices):
            updated_count += 1

    print(f"\n=== Done: Updated {updated_count} portfolio(s) ===")


if __name__ == "__main__":
    run()
