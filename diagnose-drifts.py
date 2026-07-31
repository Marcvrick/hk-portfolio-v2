#!/usr/bin/env python3
"""
Deep-dive on remaining drift days: Apr 1, Apr 10, Apr 13, Apr 14, Apr 16, Apr 30.
For each, shows per-ticker contribution and what the discrepancy maps to.
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

DATES = ["2026-04-01", "2026-04-10", "2026-04-13", "2026-04-14", "2026-04-16", "2026-04-30"]

def find(date):
    return next((s for s in snaps if s["date"] == date), None)

def prior(date):
    past = [s for s in snaps if s["date"] < date]
    return max(past, key=lambda s: s["date"]) if past else None

for date in DATES:
    snap = find(date)
    prev = prior(date)
    if not snap or not prev:
        print(f"{date}: missing snap or prior"); continue

    stored_pnl = snap.get("dailyPnL", 0) or 0
    tc = snap.get("closingPrices") or {}
    pc = prev.get("closingPrices") or {}
    pac = snap.get("positionsAtClose") or []
    realized_delta = (snap.get("realizedPnL") or 0) - (prev.get("realizedPnL") or 0)

    rows = []
    missing = []
    new_pos = []
    derived = 0.0
    for p in pac:
        ticker = p.get("ticker", "").replace("b.HK", ".HK")
        qty = p.get("quantity", 0)
        t_close = tc.get(ticker)
        p_close = pc.get(ticker)
        entry_date = p.get("entryDate", "")
        entry_price = p.get("entryPrice", 0)

        if t_close is None:
            missing.append((ticker, "no target close"))
            continue
        if p_close is None:
            if entry_date == date:
                contrib = (t_close - entry_price) * qty
                new_pos.append((ticker, entry_price, t_close, qty, contrib))
                derived += contrib
            else:
                missing.append((ticker, f"no prior close (entered {entry_date})"))
            continue
        contrib = (t_close - p_close) * qty
        derived += contrib
        rows.append((ticker, p_close, t_close, qty, contrib))

    derived_total = round(derived + realized_delta, 2)
    diff = round(stored_pnl - derived_total, 2)

    print(f"\n{'='*70}")
    print(f"{date}  prior={prev['date']}  stored={stored_pnl:+,.0f}  derived={derived_total:+,.0f}  diff={diff:+,.0f}")
    if realized_delta:
        print(f"  realizedPnL delta : {realized_delta:+,.2f}")

    rows.sort(key=lambda r: abs(r[4]), reverse=True)
    print(f"  {'ticker':<12} {'prior':>9} {'close':>9} {'qty':>8} {'contrib':>12}")
    for t, p_c, t_c, q, c in rows:
        print(f"  {t:<12} {p_c:>9.4f} {t_c:>9.4f} {q:>8} {c:>+12,.2f}")
    if new_pos:
        print(f"  --- NEW POSITIONS (entry day) ---")
        for t, ep, tc_v, q, c in new_pos:
            print(f"  {t:<12} entry={ep:>7.4f} close={tc_v:>7.4f} {q:>8} {c:>+12,.2f}")
    if missing:
        print(f"  --- MISSING ---")
        for t, reason in missing:
            print(f"  {t:<12} {reason}")

    # Also show closed trades on this date
    ct = [t for t in closed_trades if t.get("exitDate") == date]
    if ct:
        print(f"  --- CLOSED TRADES on {date} ---")
        for t in ct:
            clean = t["ticker"].replace("b.HK", ".HK")
            prev_close = pc.get(clean)
            if prev_close:
                session = (t.get("exitPrice", 0) - prev_close) * t.get("quantity", 0)
                print(f"  {clean:<12} exit={t.get('exitPrice')} prevClose={prev_close} qty={t.get('quantity')} session_pnl={session:+,.2f}")
            else:
                print(f"  {clean:<12} exit={t.get('exitPrice')} prevClose=N/A qty={t.get('quantity')}")
