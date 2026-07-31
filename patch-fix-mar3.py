#\!/usr/bin/env python3
"""
Patch: Rebuild Mar 3 snapshot with correct data.

Root cause: `today` in useState was stale ("2026-03-03") when user sold positions
on Mar 4 morning. The snapshot useEffect overwrote the Mar 3 snapshot with
Mar 4 prices, 15 positions (instead of 17), and post-sale realizedPnL.

Fix: Rebuild Mar 3 snapshot using yfinance closing prices and pre-sale positions.
Then cascade-fix Mar 4 snapshot (its dailyPnL depends on Mar 3 closingPrices).
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

# === Correct closing prices from yfinance (verified Mar 4, 2026) ===

MAR3_CLOSES = {
    "0177.HK": 10.04, "0178.HK": 0.62, "0285.HK": 29.72,
    "0434.HK": 2.78, "0564.HK": 21.42, "1316.HK": 6.80,
    "1361.HK": 5.50, "1913.HK": 43.20, "1999.HK": 4.72,
    "2175.HK": 2.80, "2438.HK": 0.60, "2510.HK": 10.01,
    "2643.HK": 31.60, "3600.HK": 5.60, "3998.HK": 4.77,
    "6826.HK": 24.40, "9690.HK": 13.92,
}

MAR2_CLOSES = {
    "0177.HK": 10.16, "0178.HK": 0.61, "0285.HK": 31.56,
    "0434.HK": 2.72, "0564.HK": 22.96, "1316.HK": 7.32,
    "1361.HK": 5.54, "1913.HK": 43.68, "1999.HK": 4.91,
    "2175.HK": 2.76, "2438.HK": 0.60, "2510.HK": 9.88,
    "2643.HK": 35.08, "3600.HK": 5.76, "3998.HK": 4.80,
    "6826.HK": 24.56, "9690.HK": 14.31,
}

# Positions that were sold on Mar 4 (must be re-added to Mar 3 snapshot)
SOLD_ON_MAR4 = {
    "0564.HK": {"entryPrice": 21.72, "quantity": 2800, "name": "BYD Electronic"},
    "2510.HK": {"entryPrice": 8.59, "quantity": 9000, "name": "Smith Micro Software"},
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


def find_snapshot(snapshots, date_str):
    for i, s in enumerate(snapshots):
        if s["date"] == date_str:
            return i, s
    return None, None


def run():
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        print("=== DRY RUN — no changes will be saved ===\n")

    print("=== Patch: Rebuild Mar 3 Snapshot ===\n")
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

    snapshots.sort(key=lambda s: s["date"])
    print(f"Loaded: {len(positions)} positions, {len(snapshots)} snapshots\n")

    # === Step 1: Rebuild Mar 3 positions (current 15 + 2 sold on Mar 4) ===
    mar3_positions = list(positions)  # current 15 positions
    for ticker, info in SOLD_ON_MAR4.items():
        # Re-add the sold positions as they were on Mar 3
        existing = next((p for p in mar3_positions if p.get("ticker") == ticker), None)
        if existing:
            print(f"  WARNING: {ticker} already in positions, skipping re-add")
            continue
        # Find entry data from closed trades
        trade = next((t for t in closed_trades if t.get("ticker") == ticker and t.get("exitDate") == "2026-03-04"), None)
        if trade:
            mar3_positions.append({
                "ticker": ticker,
                "name": trade.get("name", info["name"]),
                "quantity": trade.get("quantity", info["quantity"]),
                "entryPrice": trade.get("entryPrice", info["entryPrice"]),
                "entryDate": trade.get("entryDate", ""),
            })
            print(f"  Re-added {ticker}: qty={trade.get('quantity')}, entry={trade.get('entryPrice')}")
        else:
            # Fallback to hardcoded data
            mar3_positions.append({
                "ticker": ticker,
                "name": info["name"],
                "quantity": info["quantity"],
                "entryPrice": info["entryPrice"],
            })
            print(f"  Re-added {ticker} (from hardcoded): qty={info['quantity']}, entry={info['entryPrice']}")

    print(f"\n  Mar 3 positions: {len(mar3_positions)} (should be 17)")

    # === Step 2: Calculate Mar 3 realizedPnL (BEFORE Mar 4 sales) ===
    # Exclude trades closed on Mar 4
    mar3_realized = sum(
        (t.get("exitPrice", 0) - t.get("entryPrice", 0)) * t.get("quantity", 0)
        for t in closed_trades
        if t.get("exitDate", "") < "2026-03-04"
    )
    print(f"  Mar 3 realizedPnL: {mar3_realized:.0f} (excluding Mar 4 sales)")

    # === Step 3: Build Mar 3 snapshot ===
    mar3_closing_prices = {}
    mar3_positions_at_close = []
    mar3_portfolio_value = 0
    mar3_capital_engaged = 0
    mar3_daily_pnl = 0

    for p in mar3_positions:
        ticker = p["ticker"].replace("b.HK", ".HK")
        entry_price = p.get("entryPrice", 0)
        quantity = p.get("quantity", 0)

        mar3_price = MAR3_CLOSES.get(ticker)
        mar2_price = MAR2_CLOSES.get(ticker)

        if mar3_price is None:
            print(f"  WARNING: No Mar 3 close for {ticker}, skipping")
            continue

        mar3_closing_prices[ticker] = mar3_price
        market_value = mar3_price * quantity
        pnl = (mar3_price - entry_price) * quantity
        pnl_pct = ((mar3_price - entry_price) / entry_price * 100) if entry_price else 0

        mar3_positions_at_close.append({
            "ticker": p["ticker"],
            "name": p.get("name", ""),
            "quantity": quantity,
            "entryPrice": entry_price,
            "entryDate": p.get("entryDate", ""),
            "closingPrice": mar3_price,
            "marketValue": round(market_value, 2),
            "pnl": round(pnl, 2),
            "pnlPercent": round(pnl_pct, 2),
        })

        mar3_portfolio_value += market_value
        mar3_capital_engaged += entry_price * quantity

        # dailyPnL = Σ(Mar3Close - Mar2Close) × qty
        if mar2_price is not None:
            mar3_daily_pnl += (mar3_price - mar2_price) * quantity

    # Add realized PnL change from previous snapshot
    _, mar2_snap = find_snapshot(snapshots, "2026-03-02")
    if mar2_snap:
        mar2_realized = mar2_snap.get("realizedPnL", 0)
        realized_change = mar3_realized - mar2_realized
        mar3_daily_pnl += realized_change
        print(f"  Realized PnL change (Mar 2→3): {realized_change:.0f}")

    total_dividends = sum(
        t.get("amount", 0) for t in transactions if t.get("type") == "dividend"
    )

    mar3_snapshot = {
        "date": "2026-03-03",
        "capitalEngaged": round(mar3_capital_engaged, 2),
        "portfolioValue": round(mar3_portfolio_value, 2),
        "unrealizedPnL": round(mar3_portfolio_value - mar3_capital_engaged, 2),
        "realizedPnL": round(mar3_realized, 2),
        "totalDividends": round(total_dividends, 2),
        "positionCount": len(mar3_positions),
        "closingPrices": mar3_closing_prices,
        "dailyPnL": round(mar3_daily_pnl, 2),
        "positionsAtClose": mar3_positions_at_close,
    }

    print(f"\n--- Rebuilt Mar 3 snapshot ---")
    print(f"  portfolioValue: {mar3_snapshot['portfolioValue']:,.0f}")
    print(f"  capitalEngaged: {mar3_snapshot['capitalEngaged']:,.0f}")
    print(f"  unrealizedPnL: {mar3_snapshot['unrealizedPnL']:,.0f}")
    print(f"  dailyPnL: {mar3_snapshot['dailyPnL']:,.0f}")
    print(f"  realizedPnL: {mar3_snapshot['realizedPnL']:,.0f}")
    print(f"  positionCount: {mar3_snapshot['positionCount']}")
    print(f"  closingPrices: {len(mar3_closing_prices)} tickers")

    # === Step 4: Replace Mar 3 snapshot ===
    mar3_idx, old_mar3 = find_snapshot(snapshots, "2026-03-03")
    if mar3_idx is not None:
        print(f"\n--- Replacing corrupt Mar 3 snapshot ---")
        print(f"  OLD: dailyPnL={old_mar3.get('dailyPnL'):.0f}, portfolioValue={old_mar3.get('portfolioValue'):,.0f}, tickers={len(old_mar3.get('closingPrices', {}))}")
        print(f"  NEW: dailyPnL={mar3_snapshot['dailyPnL']:,.0f}, portfolioValue={mar3_snapshot['portfolioValue']:,.0f}, tickers={len(mar3_closing_prices)}")
        snapshots[mar3_idx] = mar3_snapshot
    else:
        print(f"\n  No existing Mar 3 snapshot — adding new one")
        snapshots.append(mar3_snapshot)
        snapshots.sort(key=lambda s: s["date"])

    # === Step 5: Cascade-fix Mar 4 snapshot ===
    mar4_idx, mar4_snap = find_snapshot(snapshots, "2026-03-04")
    if mar4_idx is not None and mar4_snap:
        old_daily = mar4_snap.get("dailyPnL", 0)
        mar4_closing = mar4_snap.get("closingPrices", {})

        # Recalculate Mar 4 dailyPnL using corrected Mar 3 closingPrices
        new_daily = 0
        # Mar 4 only has 15 positions (2 were sold during Mar 4)
        # For positions that existed both days:
        for ticker, mar4_price in mar4_closing.items():
            mar3_price = mar3_closing_prices.get(ticker)
            # Find quantity from Mar 4 positionsAtClose
            pos = next((p for p in mar4_snap.get("positionsAtClose", [])
                       if p["ticker"].replace("b.HK", ".HK") == ticker), None)
            qty = pos.get("quantity", 0) if pos else 0
            if mar3_price is not None:
                new_daily += (mar4_price - mar3_price) * qty

        # Add realized PnL change (Mar 4 sales)
        mar4_realized = mar4_snap.get("realizedPnL", 0)
        new_daily += (mar4_realized - mar3_realized)

        # Also add P&L from positions sold ON Mar 4 (their intraday P&L)
        for ticker, info in SOLD_ON_MAR4.items():
            trade = next((t for t in closed_trades
                         if t.get("ticker") == ticker and t.get("exitDate") == "2026-03-04"), None)
            if trade:
                exit_price = trade.get("exitPrice", 0)
                mar3_price = MAR3_CLOSES.get(ticker, 0)
                qty = trade.get("quantity", 0)
                # P&L from Mar 3 close to exit price
                intraday = (exit_price - mar3_price) * qty
                new_daily += intraday
                print(f"  Mar 4 sold {ticker}: ({exit_price} - {mar3_price}) × {qty} = {intraday:.0f}")

        # Wait, the realized PnL change already includes the full trade P&L.
        # The daily P&L should be: price change on held positions + (exit - prevClose) on sold positions
        # But realized PnL change = (exit - entry) * qty for both sold positions
        # We need: (exit - mar3Close) * qty, not (exit - entry) * qty
        # So let's recalculate without the double-count:
        new_daily = 0
        # 1. Held positions: (Mar4Close - Mar3Close) × qty
        for ticker, mar4_price in mar4_closing.items():
            mar3_price = mar3_closing_prices.get(ticker)
            pos = next((p for p in mar4_snap.get("positionsAtClose", [])
                       if p["ticker"].replace("b.HK", ".HK") == ticker), None)
            qty = pos.get("quantity", 0) if pos else 0
            if mar3_price is not None and qty > 0:
                new_daily += (mar4_price - mar3_price) * qty

        # 2. Sold positions: (exitPrice - Mar3Close) × qty
        for ticker, info in SOLD_ON_MAR4.items():
            trade = next((t for t in closed_trades
                         if t.get("ticker") == ticker and t.get("exitDate") == "2026-03-04"), None)
            if trade:
                exit_price = trade.get("exitPrice", 0)
                mar3_price = MAR3_CLOSES.get(ticker, 0)
                qty = trade.get("quantity", 0)
                new_daily += (exit_price - mar3_price) * qty

        mar4_snap["dailyPnL"] = round(new_daily, 2)
        snapshots[mar4_idx] = mar4_snap

        print(f"\n--- Cascade-fixed Mar 4 snapshot ---")
        print(f"  OLD dailyPnL: {old_daily:.0f}")
        print(f"  NEW dailyPnL: {new_daily:.0f}")

    # === Step 6: Update priceCache previousClose to Mar 3 closes ===
    print(f"\n--- Updating priceCache previousClose to Mar 3 closes ---")
    now_iso = datetime.now(HKT).isoformat()
    for ticker, mar3_price in MAR3_CLOSES.items():
        if ticker in price_cache:
            old_prev = price_cache[ticker].get("previousClose", "?")
            price_cache[ticker]["previousClose"] = mar3_price
            current = price_cache[ticker].get("price", mar3_price)
            price_cache[ticker]["change"] = round(current - mar3_price, 4)
            price_cache[ticker]["changePercent"] = round(
                ((current - mar3_price) / mar3_price) * 100, 4
            ) if mar3_price else 0
            price_cache[ticker]["lastUpdated"] = now_iso
            if isinstance(old_prev, (int, float)) and abs(old_prev - mar3_price) > 0.001:
                print(f"  {ticker}: previousClose {old_prev:.2f} -> {mar3_price}")

    # === Summary ===
    print(f"\n=== Summary ===")
    print(f"  Mar 3 rebuilt: {len(mar3_closing_prices)} tickers, dailyPnL={mar3_snapshot['dailyPnL']:,.0f}")
    if mar4_snap:
        print(f"  Mar 4 cascade: dailyPnL={mar4_snap['dailyPnL']:,.0f}")
    print(f"  priceCache: previousClose updated to Mar 3 closes")

    if dry_run:
        print(f"\n=== DRY RUN — nothing saved ===")
        return

    # === Save ===
    doc_ref.update({
        "priceCache": price_cache,
        "snapshots": snapshots,
        "lastUpdated": firestore.SERVER_TIMESTAMP,
    })
    print(f"\nSaved to Firestore.")
    print("=== Patch complete ===")


if __name__ == "__main__":
    run()
