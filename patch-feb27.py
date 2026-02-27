#!/usr/bin/env python3
"""
One-time patch: Restore Feb 27 HK closing prices from cron #18 (16:30 HKT).
The browser overwrote cron data with post-settlement Yahoo values.
This script restores the exact prices captured at market close.
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta

import firebase_admin
from firebase_admin import credentials, firestore

HKT = timezone(timedelta(hours=8))
COLLECTION = "portfolios"
USER_ID = "cNcZwUx3nQMV96TbB1kSkQ62u8U2"
TARGET_DATE = "2026-02-27"

# Exact prices from cron #18 (scheduled run at 16:30 HKT)
CORRECT_PRICES = {
    "3998.HK": {"price": 4.86, "previousClose": 4.829999923706055},
    "2643.HK": {"price": 37.52, "previousClose": 37.880001068115234},
    "0285.HK": {"price": 32.26, "previousClose": 32.29999923706055},
    "0564.HK": {"price": 23.5, "previousClose": 22.280000686645508},
    "1913.HK": {"price": 44.5, "previousClose": 43.81999969482422},
    "0434.HK": {"price": 2.94, "previousClose": 2.8299999237060547},
    "0178.HK": {"price": 0.62, "previousClose": 0.6100000143051147},
    "2175.HK": {"price": 2.81, "previousClose": 2.8499999046325684},
    "9690.HK": {"price": 14.39, "previousClose": 14.449999809265137},
    "6826.HK": {"price": 25.58, "previousClose": 25.280000686645508},
    "2438.HK": {"price": 0.64, "previousClose": 0.6399999856948853},
    "0177.HK": {"price": 10.18, "previousClose": 10.1899995803833},
    "3600.HK": {"price": 5.86, "previousClose": 5.809999942779541},
    "2510.HK": {"price": 9.51, "previousClose": 9.789999961853027},
    "1316.HK": {"price": 7.48, "previousClose": 7.619999885559082},
    "1361.HK": {"price": 5.65, "previousClose": 5.570000171661377},
    "1999.HK": {"price": 5.1, "previousClose": 5.039999961853027},
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


def run():
    print(f"=== Patching HK Portfolio for {TARGET_DATE} ===")
    db = init_firebase()

    doc_ref = db.collection(COLLECTION).document(USER_ID)
    doc = doc_ref.get()
    if not doc.exists:
        print("ERROR: Document not found")
        sys.exit(1)

    data = doc.to_dict()
    positions = data.get("positions", [])
    price_cache = data.get("priceCache", {})
    snapshots = data.get("snapshots", [])
    closed_trades = data.get("closedTrades", [])
    transactions = data.get("transactions", [])

    print(f"  Positions: {len(positions)}")

    # 1. Restore priceCache with correct prices
    now_iso = datetime.now(HKT).isoformat()
    for ticker, correct in CORRECT_PRICES.items():
        if ticker in price_cache:
            old_price = price_cache[ticker].get("price", "?")
            if old_price != correct["price"]:
                print(f"  FIX {ticker}: {old_price} -> {correct['price']}")
            else:
                print(f"  OK  {ticker}: {correct['price']} (unchanged)")
            price_cache[ticker]["price"] = correct["price"]
            price_cache[ticker]["previousClose"] = correct["previousClose"]
            price_cache[ticker]["change"] = round(correct["price"] - correct["previousClose"], 4)
            price_cache[ticker]["changePercent"] = round(
                ((correct["price"] - correct["previousClose"]) / correct["previousClose"]) * 100, 4
            ) if correct["previousClose"] else 0
            price_cache[ticker]["lastUpdated"] = now_iso
        else:
            print(f"  ADD {ticker}: {correct['price']}")
            price_cache[ticker] = {
                "success": True,
                "price": correct["price"],
                "previousClose": correct["previousClose"],
                "change": round(correct["price"] - correct["previousClose"], 4),
                "changePercent": round(
                    ((correct["price"] - correct["previousClose"]) / correct["previousClose"]) * 100, 4
                ) if correct["previousClose"] else 0,
                "currency": "HKD",
                "lastUpdated": now_iso,
            }

    # 2. Update positions currentPrice
    for p in positions:
        clean = p["ticker"].replace("b.HK", ".HK")
        if clean in CORRECT_PRICES:
            p["currentPrice"] = CORRECT_PRICES[clean]["price"]

    # 3. Recalculate snapshot with correct prices
    current_value = sum(p["quantity"] * p.get("currentPrice", p.get("entryPrice", 0)) for p in positions)
    capital_engaged = sum(p["quantity"] * p.get("entryPrice", 0) for p in positions)
    realized_pnl = sum((t.get("exitPrice", 0) - t.get("entryPrice", 0)) * t.get("quantity", 0) for t in closed_trades)
    total_dividends = sum(t.get("amount", 0) for t in transactions if t.get("type") == "dividend")

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

    # Calculate dailyPnL from yesterday's snapshot
    yesterday_snap = None
    for s in sorted(snapshots, key=lambda x: x["date"], reverse=True):
        if s["date"] < TARGET_DATE:
            yesterday_snap = s
            break

    daily_pnl = 0
    if yesterday_snap:
        yesterday_closing = yesterday_snap.get("closingPrices", {})
        for p in positions:
            clean = p["ticker"].replace("b.HK", ".HK")
            cur_price = p.get("currentPrice", p.get("entryPrice", 0))
            if p.get("entryDate") == TARGET_DATE:
                daily_pnl += (cur_price - p.get("entryPrice", 0)) * p["quantity"]
            else:
                prev_close = yesterday_closing.get(clean)
                if prev_close is not None:
                    daily_pnl += (cur_price - prev_close) * p["quantity"]
        yesterday_realized = yesterday_snap.get("realizedPnL", 0)
        daily_pnl += (realized_pnl - yesterday_realized)

    snapshot = {
        "date": TARGET_DATE,
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

    # Replace today's snapshot
    existing_idx = next((i for i, s in enumerate(snapshots) if s["date"] == TARGET_DATE), None)
    if existing_idx is not None:
        old_value = snapshots[existing_idx].get("portfolioValue", "?")
        snapshots[existing_idx] = snapshot
        print(f"\n  Snapshot {TARGET_DATE}: {old_value} -> {round(current_value, 2)}")
    else:
        snapshots.append(snapshot)
        snapshots.sort(key=lambda s: s["date"])
        print(f"\n  New snapshot for {TARGET_DATE}: {round(current_value, 2)}")

    print(f"  Value: {current_value:,.0f} HKD | Capital: {capital_engaged:,.0f} HKD | Daily P&L: {daily_pnl:,.0f} HKD")

    # Save to Firestore
    doc_ref.update({
        "priceCache": price_cache,
        "positions": positions,
        "snapshots": snapshots,
        "lastUpdated": firestore.SERVER_TIMESTAMP,
    })
    print(f"  Saved to Firestore")
    print(f"\n=== Patch complete ===")


if __name__ == "__main__":
    run()
