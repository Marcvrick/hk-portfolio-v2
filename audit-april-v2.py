#!/usr/bin/env python3
"""
April 2026 audit v2 — correct formula for all position types:
  open positions    : (target_close - prior_close) × qty
  new positions     : (target_close - entry_price) × qty  [entry_date == target_date]
  closed today      : (exit_price - prior_close) × qty
  (realizedPnL delta is NOT used — it double-counts prior-session unrealized gains)
"""
import os, sys, firebase_admin
from firebase_admin import credentials, firestore

CRED = os.path.join(os.path.dirname(__file__), "hk-portfolio-v2",
                    "hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json")
USER_ID = "cNcZwUx3nQMV96TbB1kSkQ62u8U2"
PNL_DRIFT = 50.0

firebase_admin.initialize_app(credentials.Certificate(CRED))
db = firestore.client()
data = db.collection("portfolios").document(USER_ID).get().to_dict()
snaps = sorted(data["snapshots"], key=lambda s: s["date"])
closed_trades = data.get("closedTrades", [])

def find(date): return next((s for s in snaps if s["date"] == date), None)
def prior(date):
    past = [s for s in snaps if s["date"] < date]
    return max(past, key=lambda s: s["date"]) if past else None

april_snaps = [s for s in snaps if s["date"].startswith("2026-04")]
print(f"{'Date':<14} {'Prior':<14} {'Stored':>10} {'Correct':>10} {'Diff':>10}  Status")
print("-" * 75)

sum_stored = 0.0; sum_correct = 0.0; drift_days = []

for snap in april_snaps:
    date = snap["date"]
    prev = prior(date)
    if not prev:
        print(f"{date:<14} {'N/A':<14} {'N/A':>10}"); continue

    stored_pnl = snap.get("dailyPnL", 0) or 0
    tc = snap.get("closingPrices") or {}
    pc = prev.get("closingPrices") or {}
    pac = snap.get("positionsAtClose") or []

    correct = 0.0
    warn = []

    # Open and new positions
    for p in pac:
        ticker = p.get("ticker", "").replace("b.HK", ".HK")
        qty = p.get("quantity", 0)
        t_close = tc.get(ticker)
        p_close = pc.get(ticker)
        entry_date = p.get("entryDate", "")
        entry_price = p.get("entryPrice", 0)

        if t_close is None:
            warn.append(f"no_target:{ticker}")
            continue
        if p_close is None:
            if entry_date == date:
                correct += (t_close - entry_price) * qty
            else:
                warn.append(f"no_prior:{ticker}(entered {entry_date})")
        else:
            correct += (t_close - p_close) * qty

    # Closed trades (session move only)
    for t in closed_trades:
        if t.get("exitDate") != date: continue
        clean = t["ticker"].replace("b.HK", ".HK")
        exit_price = t.get("exitPrice", 0)
        qty = t.get("quantity", 0)
        p_close = pc.get(clean)
        if p_close is not None:
            correct += (exit_price - p_close) * qty
        elif t.get("entryDate") == date:
            correct += (exit_price - t.get("entryPrice", 0)) * qty
        else:
            warn.append(f"closed_no_prior:{clean}")

    correct = round(correct, 2)
    diff = round(stored_pnl - correct, 2)
    status = "DRIFT" if abs(diff) > PNL_DRIFT else "ok"
    if warn: status += f" [{','.join(warn)}]"

    sum_stored += stored_pnl
    sum_correct += correct
    drift_days.append((date, diff)) if abs(diff) > PNL_DRIFT else None

    print(f"{date:<14} {prev['date']:<14} {stored_pnl:>+10,.0f} {correct:>+10,.0f} {diff:>+10,.0f}  {status}")

print("-" * 75)
print(f"{'APRIL TOTAL':<14} {'':14} {sum_stored:>+10,.0f} {sum_correct:>+10,.0f} {sum_stored-sum_correct:>+10,.0f}")
print(f"\nDays with drift > {PNL_DRIFT} HKD: {len(drift_days)}")
for d, diff in drift_days:
    print(f"  {d}: diff={diff:+,.0f}")
