#!/usr/bin/env python3
"""
Patch May 6 2026 closingPrices to match Yahoo's settled exchange closes.

Why: the cron's TradingView Scanner snapshot at 16:30 HKT captured pre-CAS
prints, not post-auction settlement. 12 of 14 tickers were off, with 1913.HK
the worst at -1.02 HKD (-2,346 impact). Total stored dailyPnL was understated
by 3,568 HKD: stored 295, real ~3,863.

Cross-check sources:
  - 1913.HK: Yahoo May 6 close = 36.78. TV today (May 7) shows change_abs=+1.5
    from prev_close=36.78. Both agree, snapshot's 35.76 is wrong.
  - Other tickers verified vs Yahoo only (typical CAS-drift magnitude 0.02-0.10).

What this script does (idempotent — safe to re-run):
  1. Updates may6.closingPrices for 12 tickers
  2. Recomputes may6.dailyPnL using:
       sum (corrected_close - prior_close) * qty over open positions
       + sum (exitPrice - prior_close) * qty over closed-on-may6 trades
  3. Recomputes may6.portfolioValue and may6.unrealizedPnL
  4. Updates priceCache previousClose so today's UI displays correct baseline

Usage:
  python3 patch-may6-closes-from-yahoo.py [--dry-run]
"""
import os, sys, json
import firebase_admin
from firebase_admin import credentials, firestore

DRY = "--dry-run" in sys.argv
USER = "cNcZwUx3nQMV96TbB1kSkQ62u8U2"
TARGET = "2026-05-06"

# Yahoo-confirmed correct closes
CORRECTIONS = {
    "0177.HK": 10.69,
    "0285.HK": 27.44,
    "0434.HK":  2.91,
    "113.HK":   6.12,
    "1316.HK":  4.91,
    "1585.HK": 12.12,
    "1698.HK": 36.18,
    "1913.HK": 36.78,
    "1999.HK":  4.33,
    "2643.HK": 23.00,
    "9690.HK": 13.46,
    "9988.HK": 134.20,
}

cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or \
    "/Users/mc/Downloads/hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json"
firebase_admin.initialize_app(credentials.Certificate(cred_path))
db = firestore.client()

doc_ref = db.collection("portfolios").document(USER)
data = doc_ref.get().to_dict() or {}
snaps = data.get("snapshots", [])

target = next((s for s in snaps if s.get("date") == TARGET), None)
prior = max((s for s in snaps if s.get("date", "") < TARGET), key=lambda s: s["date"])
if not target or not prior:
    print("ERROR: snapshots missing"); sys.exit(1)

# 1. Apply corrections
old_closes = dict(target.get("closingPrices", {}))
new_closes = dict(old_closes)
print(f"\nApplying {len(CORRECTIONS)} corrections to {TARGET}.closingPrices:")
print(f"  {'ticker':<10} {'before':>9}  →  {'after':>9}  {'delta':>8}")
for tk, new_v in CORRECTIONS.items():
    if tk not in new_closes:
        print(f"  {tk:<10}  not in stored closes — skip")
        continue
    old_v = new_closes[tk]
    new_closes[tk] = new_v
    print(f"  {tk:<10} {old_v:>9.4f}  →  {new_v:>9.4f}  {new_v - old_v:>+8.4f}")

# 2. Recompute dailyPnL using cron formula
prior_closes = prior.get("closingPrices", {})
positions_at_close = target.get("positionsAtClose", []) or []
closed_today = [t for t in (data.get("closedTrades", []) or []) if t.get("exitDate") == TARGET]

open_session = 0.0
for p in positions_at_close:
    tk = p["ticker"]
    qty = p.get("quantity", 0)
    new_c = new_closes.get(tk)
    prior_c = prior_closes.get(tk)
    if new_c is None: continue
    if prior_c is None:
        # New today (entered on TARGET) — use entry price as baseline
        if p.get("entryDate") == TARGET:
            open_session += (new_c - p.get("entryPrice", new_c)) * qty
        continue
    open_session += (new_c - prior_c) * qty

closed_session = 0.0
for t in closed_today:
    tk = t.get("ticker")
    qty = t.get("quantity", 0)
    exit_p = t.get("exitPrice")
    prior_c = prior_closes.get(tk) or t.get("entryPrice")
    if exit_p is None or prior_c is None: continue
    closed_session += (exit_p - prior_c) * qty

new_daily_pnl = round(open_session + closed_session, 2)

# 3. Recompute portfolioValue (sum of new_closes * qty over open positions)
new_pv = 0.0
new_capital = 0.0
for p in positions_at_close:
    tk = p["ticker"]
    qty = p.get("quantity", 0)
    new_c = new_closes.get(tk, p.get("closingPrice", 0))
    new_pv += new_c * qty
    new_capital += p.get("entryPrice", 0) * qty
new_pv = round(new_pv, 2)

new_unrealized = round(new_pv - new_capital, 2)

print(f"\nDailyPnL : {target.get('dailyPnL'):>12,.2f}  →  {new_daily_pnl:>12,.2f}  ({new_daily_pnl - target.get('dailyPnL'):+,.2f})")
print(f"Portfolio: {target.get('portfolioValue'):>12,.2f}  →  {new_pv:>12,.2f}  ({new_pv - target.get('portfolioValue'):+,.2f})")
print(f"UnrealPL : {target.get('unrealizedPnL'):>12,.2f}  →  {new_unrealized:>12,.2f}  ({new_unrealized - target.get('unrealizedPnL'):+,.2f})")

# 4. Update positionsAtClose closingPrice / marketValue / pnl per row
new_pac = []
for p in positions_at_close:
    tk = p["ticker"]
    qty = p.get("quantity", 0)
    new_c = new_closes.get(tk, p.get("closingPrice", 0))
    entry = p.get("entryPrice", 0)
    new_pac.append({
        **p,
        "closingPrice": new_c,
        "marketValue": round(new_c * qty, 2),
        "pnl": round((new_c - entry) * qty, 2),
        "pnlPercent": round(((new_c - entry) / entry) * 100, 4) if entry else 0,
    })

# 5. Update target snapshot
new_snap = {**target,
    "closingPrices": new_closes,
    "dailyPnL": new_daily_pnl,
    "portfolioValue": new_pv,
    "unrealizedPnL": new_unrealized,
    "positionsAtClose": new_pac,
}
new_snaps = [new_snap if s.get("date") == TARGET else s for s in snaps]

# 6. Update priceCache previousClose for tickers with corrections
old_pc = data.get("priceCache", {}) or {}
new_pc = dict(old_pc)
for tk, corrected in CORRECTIONS.items():
    # priceCache uses both with-leading-zero and without
    for key in {tk, tk.lstrip("0"), tk.lstrip("0").zfill(4)+".HK" if tk.endswith(".HK") else tk}:
        if key in new_pc:
            entry = dict(new_pc[key])
            old_prev = entry.get("previousClose")
            entry["previousClose"] = corrected
            # Recompute change/changePercent using stored current price
            cur = entry.get("price")
            if cur and corrected:
                entry["change"] = round(cur - corrected, 4)
                entry["changePercent"] = round((cur - corrected) / corrected * 100, 4) if corrected else 0
            new_pc[key] = entry
            if old_prev != corrected:
                print(f"  priceCache[{key}].previousClose: {old_prev} → {corrected}")

if DRY:
    print("\nDRY RUN — no writes performed")
    sys.exit(0)

doc_ref.update({
    "snapshots": new_snaps,
    "priceCache": new_pc,
})
print(f"\nFirestore updated: portfolios/{USER}")
print(f"  May 6 dailyPnL: 295 → {new_daily_pnl} HKD")
