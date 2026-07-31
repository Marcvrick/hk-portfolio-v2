#!/usr/bin/env python3
"""
One-time patch: Fix incorrect closing prices for Feb 13, Feb 16, Mar 2
and delete the erroneous Mar 3 snapshot (which contains Mar 2 data).

Root cause: Yahoo Finance returned stale/wrong data for HK stocks on those dates.
Source of truth: FinMC/Stooq parquet data (confirmed correct).

Recalculates dailyPnL cascading for affected dates and their successors.
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

# --- Correct closing prices from FinMC/Stooq (source of truth) ---
# Keys use Firebase ticker format (0-padded)

CORRECT_CLOSES = {
    "2026-02-13": {
        "3998.HK": 4.82, "2643.HK": 36.94, "0285.HK": 32.78, "0564.HK": 23.16,
        "1913.HK": 41.88, "0434.HK": 2.79, "0178.HK": 0.59, "2175.HK": 2.80,
        "9690.HK": 15.71, "6826.HK": 26.72, "2438.HK": 0.63, "0177.HK": 10.31,
        "3600.HK": 5.85, "2510.HK": 9.66, "1316.HK": 7.81, "1361.HK": 5.63,
        "1999.HK": 4.91,
    },
    "2026-02-16": {
        "3998.HK": 4.80, "2643.HK": 35.28, "0285.HK": 32.62, "0564.HK": 23.76,
        "1913.HK": 40.92, "0434.HK": 2.84, "0178.HK": 0.59, "2175.HK": 2.78,
        "9690.HK": 15.43, "6826.HK": 26.72, "2438.HK": 0.61, "0177.HK": 10.26,
        "3600.HK": 5.85, "2510.HK": 9.70, "1316.HK": 7.79, "1361.HK": 5.66,
        "1999.HK": 4.96,
    },
    "2026-03-02": {
        "3998.HK": 4.77, "2643.HK": 31.60, "0285.HK": 29.72, "0564.HK": 21.42,
        "1913.HK": 43.20, "0434.HK": 2.78, "0178.HK": 0.62, "2175.HK": 2.80,
        "9690.HK": 13.92, "6826.HK": 24.40, "2438.HK": 0.60, "0177.HK": 10.04,
        "3600.HK": 5.60, "2510.HK": 10.01, "1316.HK": 6.80, "1361.HK": 5.50,
        "1999.HK": 4.72,
    },
}

# Dates whose dailyPnL must be recalculated (the patched dates + their successors)
# Order matters: earliest first so the cascade is correct
DATES_TO_FIX = ["2026-02-13", "2026-02-16", "2026-03-02"]
DELETE_DATE = "2026-03-03"


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
    """Find snapshot by date, return (index, snapshot) or (None, None)."""
    for i, s in enumerate(snapshots):
        if s["date"] == date_str:
            return i, s
    return None, None


def find_previous_snapshot(snapshots, before_date):
    """Find the most recent snapshot before a given date."""
    prev = None
    for s in sorted(snapshots, key=lambda x: x["date"]):
        if s["date"] < before_date:
            prev = s
    return prev


def recalc_snapshot(snapshot, correct_prices, positions, prev_snapshot, closed_trades, transactions):
    """Recalculate a snapshot with corrected closing prices.

    correct_prices: dict of {ticker: price} using Firebase ticker format
    positions: list of position dicts (from the document)
    prev_snapshot: the previous day's snapshot (for dailyPnL calculation)
    """
    date = snapshot["date"]

    # Build new closing prices and positions at close
    closing_prices = {}
    positions_at_close = []
    current_value = 0
    capital_engaged = 0

    for p in positions:
        clean = p["ticker"].replace("b.HK", ".HK")
        entry_price = p.get("entryPrice", 0)
        quantity = p["quantity"]

        # Use corrected price if available, otherwise keep existing
        if clean in correct_prices:
            price = correct_prices[clean]
        else:
            # Fallback: use existing snapshot closing price
            price = snapshot.get("closingPrices", {}).get(clean, entry_price)

        closing_prices[clean] = price
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

    realized_pnl = sum(
        (t.get("exitPrice", 0) - t.get("entryPrice", 0)) * t.get("quantity", 0)
        for t in closed_trades
    )
    total_dividends = sum(
        t.get("amount", 0) for t in transactions if t.get("type") == "dividend"
    )

    # dailyPnL calculation
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
        daily_pnl = current_value - capital_engaged

    snapshot.update({
        "closingPrices": closing_prices,
        "positionsAtClose": positions_at_close,
        "portfolioValue": round(current_value, 2),
        "capitalEngaged": round(capital_engaged, 2),
        "unrealizedPnL": round(current_value - capital_engaged, 2),
        "realizedPnL": round(realized_pnl, 2),
        "totalDividends": round(total_dividends, 2),
        "dailyPnL": round(daily_pnl, 2),
        "positionCount": len(positions),
    })

    return snapshot


def run():
    print("=== HK Portfolio Data Correction Patch ===\n")
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

    print(f"Loaded: {len(positions)} positions, {len(snapshots)} snapshots\n")

    # Sort snapshots by date for consistent processing
    snapshots.sort(key=lambda s: s["date"])

    # --- Step 1: Fix Feb 13, Feb 16, Mar 2 closingPrices ---
    for target_date in DATES_TO_FIX:
        idx, snap = find_snapshot(snapshots, target_date)
        if idx is None:
            print(f"WARNING: No snapshot found for {target_date}, skipping")
            continue

        correct_prices = CORRECT_CLOSES[target_date]
        old_closing = snap.get("closingPrices", {})
        old_value = snap.get("portfolioValue", 0)
        old_daily = snap.get("dailyPnL", 0)

        # Show changes
        print(f"--- Fixing {target_date} ---")
        changes = 0
        for ticker, new_price in correct_prices.items():
            old_price = old_closing.get(ticker)
            if old_price is not None and abs(old_price - new_price) > 0.001:
                print(f"  {ticker}: {old_price} -> {new_price}")
                changes += 1
        if changes == 0:
            print(f"  No price changes needed")

        # Recalculate with correct prices
        prev_snap = find_previous_snapshot(snapshots, target_date)
        recalc_snapshot(snap, correct_prices, positions, prev_snap, closed_trades, transactions)

        print(f"  portfolioValue: {old_value} -> {snap['portfolioValue']}")
        print(f"  dailyPnL: {old_daily} -> {snap['dailyPnL']}")
        print()

    # --- Step 2: Recalculate dailyPnL for successor dates ---
    # After fixing Feb 13, Feb 16, Mar 2 — their successors need dailyPnL recalc
    # because dailyPnL = today's value - yesterday's closing prices
    successor_dates = set()
    all_dates = [s["date"] for s in snapshots]

    for target_date in DATES_TO_FIX:
        # Find the next snapshot date after target_date
        for d in all_dates:
            if d > target_date:
                successor_dates.add(d)
                break

    # Remove dates we already fixed and the date we'll delete
    successor_dates -= set(DATES_TO_FIX)
    successor_dates.discard(DELETE_DATE)

    for succ_date in sorted(successor_dates):
        idx, snap = find_snapshot(snapshots, succ_date)
        if idx is None:
            continue

        old_daily = snap.get("dailyPnL", 0)
        prev_snap = find_previous_snapshot(snapshots, succ_date)

        # Recalculate using existing closing prices (they're correct)
        # but with the corrected previous day's prices
        existing_prices = snap.get("closingPrices", {})
        recalc_snapshot(snap, existing_prices, positions, prev_snap, closed_trades, transactions)

        if abs(old_daily - snap["dailyPnL"]) > 0.01:
            print(f"--- Cascading fix: {succ_date} ---")
            print(f"  dailyPnL: {old_daily} -> {snap['dailyPnL']}")
            print()

    # --- Step 3: Delete Mar 3 snapshot (contains Mar 2 data, wrong date) ---
    mar3_idx, mar3_snap = find_snapshot(snapshots, DELETE_DATE)
    if mar3_idx is not None:
        print(f"--- Deleting {DELETE_DATE} snapshot (duplicate of Mar 2 data) ---")
        print(f"  Was: portfolioValue={mar3_snap.get('portfolioValue')}, dailyPnL={mar3_snap.get('dailyPnL')}")
        snapshots.pop(mar3_idx)
        print(f"  Deleted.\n")
    else:
        print(f"No snapshot found for {DELETE_DATE} to delete.\n")

    # --- Step 4: Update priceCache with corrected Mar 2 closes as previousClose ---
    print("--- Updating priceCache previousClose (Mar 2 corrected closes) ---")
    mar2_prices = CORRECT_CLOSES["2026-03-02"]
    now_iso = datetime.now(HKT).isoformat()

    for ticker, price in mar2_prices.items():
        if ticker in price_cache:
            old_prev = price_cache[ticker].get("previousClose", "?")
            price_cache[ticker]["previousClose"] = price
            # Recalculate change/changePercent based on new previousClose
            current = price_cache[ticker].get("price", price)
            price_cache[ticker]["change"] = round(current - price, 4)
            price_cache[ticker]["changePercent"] = round(
                ((current - price) / price) * 100, 4
            ) if price else 0
            price_cache[ticker]["lastUpdated"] = now_iso
            if abs(old_prev - price) > 0.001 if isinstance(old_prev, (int, float)) else True:
                print(f"  {ticker}: previousClose {old_prev} -> {price}")

    print()

    # --- Step 5: Summary ---
    print("=== Summary ===")
    print(f"  Snapshots fixed: {', '.join(DATES_TO_FIX)}")
    print(f"  Snapshot deleted: {DELETE_DATE}")
    print(f"  Total snapshots: {len(snapshots)}")
    print()

    # --- Step 6: Save to Firestore ---
    doc_ref.update({
        "priceCache": price_cache,
        "snapshots": snapshots,
        "lastUpdated": firestore.SERVER_TIMESTAMP,
    })
    print("Saved to Firestore.")
    print("\n=== Patch complete ===")


if __name__ == "__main__":
    run()
