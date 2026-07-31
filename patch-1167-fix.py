#!/usr/bin/env python3
"""
Patch: Fix 1167.HK position (wrong quantity entered) + remove bogus closed trade.

Problem:
  - User entered USD value instead of share count as quantity
  - Attempted correction created a false closed trade
  - Correct data: 14,100 shares @ 7.25 HKD, bought 2026-03-31
  - Market data: prevClose 6.91, today close 7.30 (+5.644%)

What this script does:
  1. Removes ALL closed trades for 1167.HK created today (bogus)
  2. Replaces all 1167.HK positions with ONE correct position: qty=14100, entry=7.25
  3. Keeps priceCache OFFICIAL TradingView values (prevClose=6.91, not entry price)
  4. Recalculates today's snapshot (Apr 1)
  5. Fixes yesterday's snapshot (Mar 31) if corrupted by wrong qty

Usage:
  GOOGLE_APPLICATION_CREDENTIALS=... python patch-1167-fix.py [--dry-run]
"""
import os
import sys
import json
import firebase_admin
from firebase_admin import credentials, firestore

# === CONFIG ===
MARC_UID = "cNcZwUx3nQMV96TbB1kSkQ62u8U2"
TODAY = "2026-04-01"
YESTERDAY = "2026-03-31"
TICKER = "1167.HK"
CORRECT_QTY = 14100
CORRECT_ENTRY_PRICE = 7.25
CORRECT_ENTRY_DATE = "2026-03-31"
TODAY_CLOSE = 7.30
# Official TradingView market data — DO NOT override with entry price
OFFICIAL_PREV_CLOSE = 6.91
OFFICIAL_CHANGE = 0.39
OFFICIAL_CHANGE_PCT = 5.644
# Yesterday's market data (1167 dropped -4.29% from 7.22)
YESTERDAY_CLOSE = 6.91
YESTERDAY_PREV_CLOSE = 7.22

DRY_RUN = "--dry-run" in sys.argv

# === INIT FIREBASE ===
cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
if not cred_path:
    print("ERROR: Set GOOGLE_APPLICATION_CREDENTIALS env var")
    sys.exit(1)
cred = credentials.Certificate(cred_path)
firebase_admin.initialize_app(cred)
db = firestore.client()

doc_ref = db.document(f"portfolios/{MARC_UID}")
doc = doc_ref.get()
data = doc.to_dict()

# === 1. INSPECT CURRENT STATE ===
positions = data.get("positions", [])
closed_trades = data.get("closedTrades", [])
snapshots = data.get("snapshots", [])
price_cache = data.get("priceCache", {})

print("=" * 60)
print("CURRENT STATE")
print("=" * 60)

print(f"\n--- Positions with ticker {TICKER} ---")
positions_1167 = [p for p in positions if p.get("ticker") == TICKER]
for p in positions_1167:
    print(f"  id={p.get('id')}  qty={p.get('quantity')}  entry={p.get('entryPrice')}  "
          f"current={p.get('currentPrice')}  date={p.get('entryDate')}  name={p.get('name')}")

print(f"\n--- Closed trades with ticker {TICKER} ---")
closed_1167 = [t for t in closed_trades if t.get("ticker") == TICKER]
for t in closed_1167:
    print(f"  id={t.get('id')}  qty={t.get('quantity')}  entry={t.get('entryPrice')}  "
          f"exit={t.get('exitPrice')}  exitDate={t.get('exitDate')}  "
          f"profit={(t.get('exitPrice',0)-t.get('entryPrice',0))*t.get('quantity',0):.0f}")

print(f"\n--- priceCache for {TICKER} ---")
cache_1167 = price_cache.get(TICKER, {})
print(f"  {json.dumps(cache_1167, indent=2, default=str)}")

# Show both snapshots
for date_label, date_val in [("Yesterday", YESTERDAY), ("Today", TODAY)]:
    snap = next((s for s in snapshots if s.get("date") == date_val), None)
    print(f"\n--- {date_label}'s snapshot ({date_val}) ---")
    if snap:
        print(f"  portfolioValue={snap.get('portfolioValue')}")
        print(f"  dailyPnL={snap.get('dailyPnL')}")
        print(f"  positionCount={snap.get('positionCount')}")
        cp = snap.get("closingPrices", {})
        print(f"  closingPrices[{TICKER}]={cp.get(TICKER)}")
        pac = snap.get("positionsAtClose", [])
        p1167 = [p for p in pac if p.get("ticker") == TICKER]
        if p1167:
            print(f"  positionsAtClose[{TICKER}]: qty={p1167[0].get('quantity')} "
                  f"entry={p1167[0].get('entryPrice')} close={p1167[0].get('closingPrice')}")
    else:
        print("  (no snapshot)")

# === 2. FIX POSITIONS ===
print("\n" + "=" * 60)
print("APPLYING FIXES")
print("=" * 60)

first_1167 = positions_1167[0] if positions_1167 else {}
correct_position = {
    "id": first_1167.get("id", int(__import__('time').time() * 1000)),
    "ticker": TICKER,
    "name": first_1167.get("name", "Jacobio Pharma"),
    "quantity": CORRECT_QTY,
    "entryPrice": CORRECT_ENTRY_PRICE,
    "currentPrice": TODAY_CLOSE,
    "entryDate": CORRECT_ENTRY_DATE,
}

new_positions = [p for p in positions if p.get("ticker") != TICKER]
new_positions.append(correct_position)
print(f"\n[FIX 1] Positions: removed {len(positions_1167)} entries for {TICKER}, "
      f"added 1 correct (qty={CORRECT_QTY}, entry={CORRECT_ENTRY_PRICE})")

# === 3. REMOVE BOGUS CLOSED TRADES ===
new_closed = [t for t in closed_trades if t.get("ticker") != TICKER]
removed_count = len(closed_trades) - len(new_closed)
print(f"[FIX 2] Closed trades: removed {removed_count} bogus trade(s) for {TICKER}")

# === 4. KEEP OFFICIAL PRICE CACHE (don't override with entry price) ===
new_cache = dict(price_cache)
new_cache[TICKER] = {
    "price": TODAY_CLOSE,
    "previousClose": OFFICIAL_PREV_CLOSE,
    "change": OFFICIAL_CHANGE,
    "changePercent": OFFICIAL_CHANGE_PCT,
    "success": True,
    "currency": "HKD",
    "lastUpdated": cache_1167.get("lastUpdated", ""),
}
print(f"[FIX 3] priceCache[{TICKER}]: price={TODAY_CLOSE}, prevClose={OFFICIAL_PREV_CLOSE} (official), "
      f"change=+{OFFICIAL_CHANGE}, changePercent=+{OFFICIAL_CHANGE_PCT}%")

# === 5. RECALCULATE TODAY'S SNAPSHOT (Apr 1) ===
total_value = 0
total_daily_pnl = 0
closing_prices = {}

for p in new_positions:
    tk = p["ticker"]
    qty = p["quantity"]
    current = p.get("currentPrice", 0)
    cached = new_cache.get(tk, price_cache.get(tk, {}))
    change_per_share = cached.get("change", 0)

    total_value += current * qty
    total_daily_pnl += change_per_share * qty
    closing_prices[tk] = current

print(f"\n[FIX 4] Today's snapshot ({TODAY}) recalculation:")
print(f"  Total portfolio value: {total_value:,.0f} HKD")
print(f"  Daily P&L: {total_daily_pnl:,.0f} HKD")
print(f"  1167.HK contribution: {OFFICIAL_CHANGE * CORRECT_QTY:,.0f} HKD "
      f"(+{OFFICIAL_CHANGE_PCT}% from prevClose {OFFICIAL_PREV_CLOSE})")

today_snap = next((s for s in snapshots if s.get("date") == TODAY), None)
if today_snap:
    snap_idx = next(i for i, s in enumerate(snapshots) if s.get("date") == TODAY)
    snapshots[snap_idx]["portfolioValue"] = round(total_value, 2)
    snapshots[snap_idx]["dailyPnL"] = round(total_daily_pnl, 2)
    snapshots[snap_idx]["closingPrices"] = closing_prices
    snapshots[snap_idx]["positionCount"] = len(new_positions)
    snapshots[snap_idx]["positionsAtClose"] = [
        {
            "ticker": p["ticker"],
            "name": p.get("name", ""),
            "quantity": p["quantity"],
            "entryPrice": p["entryPrice"],
            "closingPrice": p.get("currentPrice", 0),
        }
        for p in new_positions
    ]
    print(f"  Updated existing snapshot for {TODAY}")

# === 6. FIX YESTERDAY'S SNAPSHOT (Mar 31) if corrupted ===
yesterday_snap = next((s for s in snapshots if s.get("date") == YESTERDAY), None)
if yesterday_snap:
    snap_idx_y = next(i for i, s in enumerate(snapshots) if s.get("date") == YESTERDAY)
    y_cp = yesterday_snap.get("closingPrices", {})
    y_pac = yesterday_snap.get("positionsAtClose", [])
    y_1167_pac = [p for p in y_pac if p.get("ticker") == TICKER]

    # Check if yesterday's snapshot has wrong qty for 1167
    needs_fix = False
    if y_1167_pac and y_1167_pac[0].get("quantity") != CORRECT_QTY:
        needs_fix = True
    if TICKER in y_cp and y_cp[TICKER] != YESTERDAY_CLOSE:
        needs_fix = True
    # 1167 might not be in yesterday's snapshot at all if it was added today in the app
    # but entry date is yesterday — check
    if TICKER not in y_cp:
        print(f"\n[FIX 5] Yesterday's snapshot ({YESTERDAY}): {TICKER} not present in closingPrices")
        print(f"  Adding {TICKER} with close={YESTERDAY_CLOSE}")
        needs_fix = True

    if needs_fix:
        print(f"\n[FIX 5] Yesterday's snapshot ({YESTERDAY}) — fixing {TICKER}:")
        old_cp_val = y_cp.get(TICKER, "N/A")
        y_cp[TICKER] = YESTERDAY_CLOSE
        print(f"  closingPrices[{TICKER}]: {old_cp_val} → {YESTERDAY_CLOSE}")

        # Fix positionsAtClose
        found = False
        for j, pac_entry in enumerate(y_pac):
            if pac_entry.get("ticker") == TICKER:
                old_qty = pac_entry.get("quantity")
                y_pac[j]["quantity"] = CORRECT_QTY
                y_pac[j]["entryPrice"] = CORRECT_ENTRY_PRICE
                y_pac[j]["closingPrice"] = YESTERDAY_CLOSE
                print(f"  positionsAtClose[{TICKER}]: qty {old_qty} → {CORRECT_QTY}")
                found = True
                break
        if not found:
            y_pac.append({
                "ticker": TICKER,
                "name": "Jacobio Pharma",
                "quantity": CORRECT_QTY,
                "entryPrice": CORRECT_ENTRY_PRICE,
                "closingPrice": YESTERDAY_CLOSE,
            })
            print(f"  positionsAtClose[{TICKER}]: added (qty={CORRECT_QTY}, close={YESTERDAY_CLOSE})")

        # Recalculate yesterday's portfolioValue
        y_total_value = 0
        for pac_entry in y_pac:
            y_total_value += pac_entry.get("closingPrice", 0) * pac_entry.get("quantity", 0)
        old_pv = yesterday_snap.get("portfolioValue")
        print(f"  portfolioValue: {old_pv:,.0f} → {y_total_value:,.0f}")

        # Recalculate yesterday's dailyPnL
        # 1167 was bought yesterday — its daily P&L contribution depends on prevClose
        # prevClose for Mar 31 was 7.22, close was 6.91
        # But user bought at 7.25 during the day, stock closed at 6.91
        # The app's normal behavior: new position added today uses entry price as baseline
        # So 1167 daily P&L on Mar 31 = (6.91 - 7.25) * 14100 = -4794
        # But we need to check what OTHER positions contributed — we can't easily recalc
        # from here without all prevCloses. So we adjust the delta only.
        #
        # Approach: compute the WRONG 1167 contribution, compute the CORRECT one, apply delta
        old_1167_pac = [p for p in yesterday_snap.get("positionsAtClose", []) if p.get("ticker") == TICKER]
        if old_1167_pac:
            old_qty_y = old_1167_pac[0].get("quantity", 0)
            old_entry_y = old_1167_pac[0].get("entryPrice", 0)
            old_close_y = old_1167_pac[0].get("closingPrice", 0)
            # The app computes daily P&L for new-today positions as (close - entry) * qty
            wrong_contribution = (old_close_y - old_entry_y) * old_qty_y
            correct_contribution = (YESTERDAY_CLOSE - CORRECT_ENTRY_PRICE) * CORRECT_QTY
            delta = correct_contribution - wrong_contribution
            old_dpnl = yesterday_snap.get("dailyPnL", 0)
            new_dpnl = old_dpnl + delta
            print(f"  dailyPnL: {old_dpnl:,.0f} + delta {delta:,.0f} → {new_dpnl:,.0f}")
            print(f"    (wrong 1167 contribution: ({old_close_y}-{old_entry_y})*{old_qty_y} = {wrong_contribution:,.0f})")
            print(f"    (correct 1167 contribution: ({YESTERDAY_CLOSE}-{CORRECT_ENTRY_PRICE})*{CORRECT_QTY} = {correct_contribution:,.0f})")
            snapshots[snap_idx_y]["dailyPnL"] = round(new_dpnl, 2)
        else:
            print(f"  dailyPnL: no previous 1167 entry to compute delta — leaving as-is")

        snapshots[snap_idx_y]["closingPrices"] = y_cp
        snapshots[snap_idx_y]["positionsAtClose"] = y_pac
        snapshots[snap_idx_y]["portfolioValue"] = round(y_total_value, 2)
        snapshots[snap_idx_y]["positionCount"] = len(y_pac)
    else:
        print(f"\n[FIX 5] Yesterday's snapshot ({YESTERDAY}): OK, no fix needed")
else:
    print(f"\n[FIX 5] No snapshot for {YESTERDAY}")

# === 7. SUMMARY ===
print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)
print(f"  Positions: {len(positions)} → {len(new_positions)}")
print(f"  Closed trades: {len(closed_trades)} → {len(new_closed)} (removed {removed_count})")
print(f"  1167.HK: qty={CORRECT_QTY}, entry={CORRECT_ENTRY_PRICE}")
print(f"  priceCache: official prevClose={OFFICIAL_PREV_CLOSE} (market), not entry price")
print(f"  Today P&L (1167): +{OFFICIAL_CHANGE * CORRECT_QTY:,.0f} HKD")
print(f"  Yesterday P&L (1167): {(YESTERDAY_CLOSE - CORRECT_ENTRY_PRICE) * CORRECT_QTY:,.0f} HKD")

if DRY_RUN:
    print(f"\n*** DRY RUN — no changes written to Firestore ***")
    print(f"Run without --dry-run to apply fixes.")
else:
    print(f"\nWriting to Firestore...")
    doc_ref.update({
        "positions": new_positions,
        "closedTrades": new_closed,
        "priceCache": new_cache,
        "snapshots": snapshots,
    })
    print("Done. Refresh the portfolio app to see corrected data.")
