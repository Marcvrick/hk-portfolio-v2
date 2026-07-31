#!/usr/bin/env python3
"""
patch-jul20-300-partial.py
Fix the 300.HK (Haier) sale recorded as a FULL 1200-share close but actually an
800-share PARTIAL sale @ 94.15 on 2026-07-20. 400 shares remain held.

Root cause: Dany sold 800 of 1200 sh @ 94.15 but the order was validated as the
full position. The app's closePosition took the full-close branch: position removed
from positions[], closedTrade booked qty=1200.

This patch mirrors what closePosition WOULD have done for sellQuantity=800:
  - positions[]: re-add 300.HK, qty=400, entryPrice=90.25 (avg cost invariant under
    partial close — see 2026-06-25 incident), entryDate 2026-06-09, fresh id.
  - closedTrades[]: the 300.HK trade (id 1784534096547) qty 1200 -> 800; buyFees/
    sellFees/totalFees recomputed via calcTradingFees (ported from index.html L1756)
    on the SOLD qty (800).
  - snapshots[]: only 2026-07-20 is on/after the sale date (sale is today). Re-add
    the 400-sh leg (add-to-stored, invariant-safe): portfolioValue/capitalEngaged/
    unrealizedPnL/positionCount/closingPrices recomputed from the augmented
    positionsAtClose; realizedPnL -= (94.15-90.25)*400 = 1560; dailyPnL target-leg
    correction: remove the wrong 1200 closed-today leg (2280), add the correct
    400 held leg (800) + 800 closed-today leg (1520) = net +40.

Idempotent: aborts if 300.HK already in positions[] OR its closedTrade already qty 800.

Usage:
  python3 patch-jul20-300-partial.py           # dry-run
  python3 patch-jul20-300-partial.py --apply
"""
import sys, json, time, math
import firebase_admin
from firebase_admin import credentials, firestore

CRED = 'hk-portfolio-v2/hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json'
DOC_ID = 'cNcZwUx3nQMV96TbB1kSkQ62u8U2'
APPLY = '--apply' in sys.argv

TICKER = '300.HK'
SALE_DATE = '2026-07-20'
ENTRY_PRICE = 90.25
EXIT_PRICE = 94.15
SOLD_QTY = 800
REMAIN_QTY = 400
TRADE_ID = 1784534096547
TODAY_CLOSE = 94.25        # priceCache["300.HK"].price = today's close
TV_PREV_CLOSE = 92.25      # priceCache["300.HK"].previousClose (TV official prior close)
TV_CHANGE_ABS = 2.0        # priceCache["300.HK"].change

# ---- calcTradingFees ported verbatim from index.html L1756 ----
def calc_trading_fees(amount, quantity, is_buy):
    brokerage = max(amount * 0.0025, 100)
    board_lots = math.ceil(quantity / 100)
    deposit = min(max(board_lots * 5, 30), 200) if is_buy else 0
    stamp = math.ceil(amount * 0.001)
    sfc = amount * 0.000027
    afrc = amount * 0.0000015
    hkex = amount * 0.0000565
    settle = min(max(amount * 0.00002, 2), 100)
    return round((brokerage + deposit + stamp + sfc + afrc + hkex + settle) * 100) / 100

buy_fees = calc_trading_fees(SOLD_QTY * ENTRY_PRICE, SOLD_QTY, True)
sell_fees = calc_trading_fees(SOLD_QTY * EXIT_PRICE, SOLD_QTY, False)
total_fees = round((buy_fees + sell_fees) * 100) / 100

cred = credentials.Certificate(CRED)
firebase_admin.initialize_app(cred)
db = firestore.client()
ref = db.collection('portfolios').document(DOC_ID)
doc = ref.get().to_dict()

positions = doc.get('positions', [])
closed = doc.get('closedTrades', [])
snapshots = sorted(doc.get('snapshots', []), key=lambda s: s.get('date', ''))

# ---- Idempotency ----
if any(p.get('ticker') == TICKER for p in positions):
    print("[ABORT] 300.HK already present in positions[] — patch already applied."); sys.exit(0)
trade = next((c for c in closed if c.get('ticker') == TICKER), None)
if trade is None:
    print("[ABORT] No 300.HK closedTrade found — nothing to fix."); sys.exit(0)
if trade.get('quantity') == SOLD_QTY:
    print(f"[ABORT] 300.HK closedTrade already qty={SOLD_QTY} — already fixed."); sys.exit(0)
if trade.get('quantity') != 1200:
    print(f"[ABORT] 300.HK closedTrade qty={trade.get('quantity')}, expected 1200. STOP."); sys.exit(1)

snap = next((s for s in snapshots if s.get('date') == SALE_DATE), None)
if snap is None:
    print(f"[ABORT] No {SALE_DATE} snapshot found."); sys.exit(1)

# =====================================================================
# 1) positions[] — re-add the remaining 400 shares
# =====================================================================
new_pos = {
    'id': int(time.time() * 1000),
    'ticker': TICKER,
    'name': trade.get('name', 'Haier'),
    'quantity': REMAIN_QTY,
    'entryPrice': ENTRY_PRICE,
    'entryDate': trade.get('entryDate', '2026-06-09'),
    'currentPrice': TODAY_CLOSE,
}
new_positions = positions + [new_pos]

# =====================================================================
# 2) closedTrades[] — qty 1200 -> 800, recompute fees on SOLD_QTY
# =====================================================================
new_closed = []
for c in closed:
    if c.get('ticker') == TICKER:
        c = dict(c)
        c['quantity'] = SOLD_QTY
        c['buyFees'] = buy_fees
        c['sellFees'] = sell_fees
        c['totalFees'] = total_fees
    new_closed.append(c)

# =====================================================================
# 3) 2026-07-20 snapshot — re-add 400-sh leg (add-to-stored)
# =====================================================================
new_snap = dict(snap)
pac = list(snap.get('positionsAtClose') or [])
leg = {
    'ticker': TICKER,
    'name': trade.get('name', 'Haier'),
    'quantity': REMAIN_QTY,
    'entryPrice': ENTRY_PRICE,
    'entryDate': trade.get('entryDate', '2026-06-09'),
    'closingPrice': TODAY_CLOSE,
    'marketValue': round(TODAY_CLOSE * REMAIN_QTY, 2),
    'pnl': round((TODAY_CLOSE - ENTRY_PRICE) * REMAIN_QTY, 2),
    'pnlPercent': round(((TODAY_CLOSE - ENTRY_PRICE) / ENTRY_PRICE) * 100, 6),
}
pac.append(leg)

cap_old = snap.get('capitalEngaged', 0)
pv_old = snap.get('portfolioValue', 0)
unr_old = snap.get('unrealizedPnL', 0)
real_old = snap.get('realizedPnL', 0)
daily_old = snap.get('dailyPnL', 0)
pc_old = snap.get('positionCount', 0)

cap_add = ENTRY_PRICE * REMAIN_QTY          # 36100
pv_add = TODAY_CLOSE * REMAIN_QTY           # 37700
unr_add = (TODAY_CLOSE - ENTRY_PRICE) * REMAIN_QTY  # 1600
real_delta = -((EXIT_PRICE - ENTRY_PRICE) * REMAIN_QTY)  # -1560

# dailyPnL: remove wrong 1200 closed-today leg, add correct 400 held + 800 closed-today
wrong_closed_leg = (EXIT_PRICE - TV_PREV_CLOSE) * 1200     # 2280
correct_held_leg = TV_CHANGE_ABS * REMAIN_QTY              # 800
correct_closed_leg = (EXIT_PRICE - TV_PREV_CLOSE) * SOLD_QTY  # 1520
daily_delta = (correct_held_leg + correct_closed_leg) - wrong_closed_leg  # +40

closing_prices = dict(snap.get('closingPrices') or {})
closing_prices[TICKER] = TODAY_CLOSE

new_snap['positionsAtClose'] = pac
new_snap['closingPrices'] = closing_prices
new_snap['capitalEngaged'] = round(cap_old + cap_add, 2)
new_snap['portfolioValue'] = round(pv_old + pv_add, 2)
new_snap['unrealizedPnL'] = round(unr_old + unr_add, 2)
new_snap['positionCount'] = pc_old + 1
new_snap['realizedPnL'] = round(real_old + real_delta, 2)
new_snap['dailyPnL'] = round(daily_old + daily_delta, 2)

new_snapshots = []
for s in snapshots:
    new_snapshots.append(new_snap if s.get('date') == SALE_DATE else s)

# =====================================================================
# Preview
# =====================================================================
print("=== TRADE FIX (closedTrades) ===")
print(f"  qty:        {trade.get('quantity')} -> {SOLD_QTY}")
print(f"  buyFees:    {trade.get('buyFees')} -> {buy_fees}")
print(f"  sellFees:   {trade.get('sellFees')} -> {sell_fees}")
print(f"  totalFees:  {trade.get('totalFees')} -> {total_fees}")
print(f"  (entry/exit/entryDate/exitDate unchanged: {trade.get('entryPrice')} / {trade.get('exitPrice')} / {trade.get('entryDate')} / {trade.get('exitDate')})")

print("\n=== POSITION RESTORE (positions[]) ===")
print(f"  + {json.dumps(new_pos, ensure_ascii=False)}")
print(f"  positions count: {len(positions)} -> {len(new_positions)}")

print(f"\n=== SNAPSHOT {SALE_DATE} (add-to-stored) ===")
print(f"  capitalEngaged: {cap_old} -> {new_snap['capitalEngaged']}  (+{cap_add})")
print(f"  portfolioValue: {pv_old} -> {new_snap['portfolioValue']}  (+{pv_add})")
print(f"  unrealizedPnL:  {unr_old} -> {new_snap['unrealizedPnL']}  (+{unr_add})")
print(f"  positionCount:  {pc_old} -> {new_snap['positionCount']}  (+1)")
print(f"  realizedPnL:    {real_old} -> {new_snap['realizedPnL']}  ({real_delta})")
print(f"  dailyPnL:       {daily_old} -> {new_snap['dailyPnL']}  ({'+' if daily_delta>=0 else ''}{daily_delta})")
print(f"  closingPrices['300.HK']: added {TODAY_CLOSE}")
print(f"  leg added: qty={REMAIN_QTY} entry={ENTRY_PRICE} close={TODAY_CLOSE} pnl={leg['pnl']}")

print("\n=== INVARIANT CHECK ===")
inv_pv = round(sum((p.get('closingPrice',0))*p.get('quantity',0) for p in pac), 2)
inv_cap = round(sum((p.get('entryPrice',0))*p.get('quantity',0) for p in pac), 2)
print(f"  recomputed pv from pac:  {inv_pv}  (stored {new_snap['portfolioValue']})  match={abs(inv_pv-new_snap['portfolioValue'])<0.5}")
print(f"  recomputed cap from pac: {inv_cap} (stored {new_snap['capitalEngaged']})  match={abs(inv_cap-new_snap['capitalEngaged'])<0.5}")
print(f"  unrealized = pv - cap:    {round(inv_pv-inv_cap,2)}  (stored {new_snap['unrealizedPnL']})  match={abs(round(inv_pv-inv_cap,2)-new_snap['unrealizedPnL'])<0.5}")
print(f"  positionCount = len(pac): {len(pac)}  (stored {new_snap['positionCount']})  match={len(pac)==new_snap['positionCount']}")
realized_recompute = round(sum((c.get('exitPrice',0)-c.get('entryPrice',0))*c.get('quantity',0) for c in new_closed),2)
print(f"  realizedPnL = Σ gross closedTrades: {realized_recompute}  (stored {new_snap['realizedPnL']})  match={abs(realized_recompute-new_snap['realizedPnL'])<0.5}")

if not APPLY:
    print("\n[DRY-RUN] No write. Re-run with --apply to commit.")
    sys.exit(0)

# =====================================================================
# Apply (targeted field updates — NOT a full doc.set)
# =====================================================================
ref.update({
    'positions': new_positions,
    'closedTrades': new_closed,
    'snapshots': new_snapshots,
})
print("\n[APPLIED] positions, closedTrades, snapshots updated.")

# =====================================================================
# Verify
# =====================================================================
after = ref.get().to_dict()
v_pos = [p for p in after.get('positions', []) if p.get('ticker') == TICKER]
v_trade = next((c for c in after.get('closedTrades', []) if c.get('ticker') == TICKER), None)
v_snap = next((s for s in after.get('snapshots', []) if s.get('date') == SALE_DATE), None)
print("\n=== VERIFY ===")
print(f"  position present: {bool(v_pos)}  -> {v_pos[0] if v_pos else 'MISSING'}")
print(f"  closedTrade qty:  {v_trade.get('quantity') if v_trade else 'MISSING'}  totalFees={v_trade.get('totalFees') if v_trade else '-'}")
print(f"  snapshot posCount: {v_snap.get('positionCount')}  pv={v_snap.get('portfolioValue')}  dailyPnL={v_snap.get('dailyPnL')}  realized={v_snap.get('realizedPnL')}")
print(f"  snapshot has 300.HK leg: {any(p.get('ticker')==TICKER for p in (v_snap.get('positionsAtClose') or []))}")
print(f"  snapshot closingPrices has 300.HK: {'300.HK' in (v_snap.get('closingPrices') or {})}")
