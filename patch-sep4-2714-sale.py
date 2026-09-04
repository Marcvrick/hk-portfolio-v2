#!/usr/bin/env python3
"""
patch-sep4-2714-sale.py
Record the 2714.HK (Muyuan Foods) sale that Dany entered in the app on
2026-09-04 and that never reached Firestore: full exit, 2,900 shares @ 39.00.

Why the write is needed at all: the app's close was optimistic and every
saveData failure path was silent, so the UI booked the sale while the cloud
never received it. The live Security Rules reject any update that shrinks
closedTrades, which proves no write ever landed (54 trades, no 2714 row) —
this is not a reverted write. See wiki/incidents.md 2026-09-04.

What it changes:
  positions[]     remove the 2714.HK leg (2,900 @ 35.48, entered 2026-08-31)
  closedTrades[]  prepend the sale, fees from the ported calcTradingFees
  snapshots[]     the 2026-09-04 snapshot only:
                    - drop the leg from positionsAtClose + closingPrices
                    - RECOMPUTE pv / capitalEngaged / unrealized / count from
                      the filtered positionsAtClose (never subtract per-field
                      deltas — wiki/recording-a-sale.md Step 4)
                    - realizedPnL += gross (exit − entry) × qty
                    - dailyPnL: swap the held leg (change × qty) for the
                      closed-today leg (exit − prevClose) × qty, the same
                      formula update.py uses (update.py L534-556)

Snapshots 2026-08-31 → 2026-09-03 carry 2714 as legitimately held and are NOT
touched. The 2026-09-04 snapshot is browser-minted (no settledAt), so the
16:35 HKT cron rebuilds it wholesale from the corrected arrays (update.py
L596-604); the values written here are the consistent intermediate state in
case the cron is late or red.

Idempotent: aborts if a 2714 closedTrade already exists, if the position is
absent or disagrees with the constants, or if 2714 appears in a snapshot after
the sale date.

Usage:
  python3 patch-sep4-2714-sale.py           # dry-run
  python3 patch-sep4-2714-sale.py --apply   # app CLOSED first
"""
import math
import sys
import time
import firebase_admin
from firebase_admin import credentials, firestore

CRED   = 'hk-portfolio-v2/hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json'
DOC_ID = 'cNcZwUx3nQMV96TbB1kSkQ62u8U2'

TICKER      = '2714.HK'
NAME        = 'Muyuan food'
QTY         = 2900
ENTRY       = 35.48
ENTRY_DATE  = '2026-08-31'
EXIT        = 39.00
EXIT_DATE   = '2026-09-04'
PREV_DATE   = '2026-09-03'   # prior trading day, source of prevClose

APPLY = '--apply' in sys.argv


def calc_trading_fees(amount, quantity, is_buy):
    """Port of calcTradingFees (index.html, HSBC HK schedule). Rounded 2dp per side."""
    brokerage = max(amount * 0.0025, 100)
    board_lots = math.ceil(quantity / 100)
    deposit = min(max(board_lots * 5, 30), 200) if is_buy else 0
    stamp = math.ceil(amount * 0.001)
    sfc = amount * 0.000027
    afrc = amount * 0.0000015
    hkex = amount * 0.0000565
    settle = min(max(amount * 0.00002, 2), 100)
    return round((brokerage + deposit + stamp + sfc + afrc + hkex + settle) * 100) / 100


cred = credentials.Certificate(CRED)
firebase_admin.initialize_app(cred)
ref = firestore.client().collection('portfolios').document(DOC_ID)
doc = ref.get().to_dict()

positions    = doc['positions']
closed       = doc['closedTrades']
snapshots    = doc['snapshots']
price_cache  = doc.get('priceCache', {})

# ---------------- Idempotency / safety ----------------
if any(t.get('ticker') == TICKER for t in closed):
    sys.exit(f"ABORT: a closedTrade for {TICKER} already exists — already patched?")

legs = [p for p in positions if p['ticker'] == TICKER]
if len(legs) != 1:
    sys.exit(f"ABORT: {len(legs)} {TICKER} legs in positions[], expected exactly 1.")
pos = legs[0]
if pos['quantity'] != QTY or pos['entryPrice'] != ENTRY or pos['entryDate'] != ENTRY_DATE:
    sys.exit(f"ABORT: position disagrees with the confirmed constants: {pos}")

carriers = sorted({s['date'] for s in snapshots
                   if any(p['ticker'] == TICKER for p in s.get('positionsAtClose', []))
                   or TICKER in s.get('closingPrices', {})})
late = [d for d in carriers if d > EXIT_DATE]
if late:
    sys.exit(f"ABORT: {TICKER} appears in snapshots after the sale date: {late}. "
             f"Patch every post-sale snapshot, not just {EXIT_DATE}.")
if EXIT_DATE not in carriers:
    sys.exit(f"ABORT: no {EXIT_DATE} snapshot carries {TICKER}; inspect before patching.")

# Cross-check: sum of closedTrades gross must equal the stored realizedPnL.
# (The 2026-06-28 incident used exactly this checksum to prove the repair.)
prev_snap = next((s for s in snapshots if s['date'] == PREV_DATE), None)
if prev_snap is None:
    sys.exit(f"ABORT: no {PREV_DATE} snapshot to source prevClose from.")
gross_before = round(sum((t['exitPrice'] - t['entryPrice']) * t['quantity'] for t in closed), 2)
if abs(gross_before - round(prev_snap['realizedPnL'], 2)) > 0.5:
    sys.exit(f"ABORT: Σ closedTrades gross ({gross_before}) != {PREV_DATE} realizedPnL "
             f"({prev_snap['realizedPnL']}). The book is already inconsistent, stop here.")

# ---------------- prevClose (prior trading-day close) ----------------
prev_close = prev_snap.get('closingPrices', {}).get(TICKER)
if prev_close is None:
    sys.exit(f"ABORT: no {TICKER} close on the {PREV_DATE} snapshot.")
pc = price_cache.get(TICKER, {})
pc_prev = pc.get('previousClose')
if pc_prev is not None and abs(pc_prev - prev_close) > 0.005:
    sys.exit(f"ABORT: prevClose disagrees — snapshot {PREV_DATE} says {prev_close}, "
             f"priceCache says {pc_prev}. Resolve before writing.")

# ---------------- Build the trade ----------------
buy_amount  = QTY * ENTRY
sell_amount = QTY * EXIT
buy_fees  = calc_trading_fees(buy_amount, QTY, True)
sell_fees = calc_trading_fees(sell_amount, QTY, False)
trade = {
    'id': int(time.time() * 1000),
    'ticker': TICKER,
    'name': NAME,
    'quantity': QTY,
    'entryPrice': ENTRY,
    'exitPrice': EXIT,
    'entryDate': ENTRY_DATE,
    'exitDate': EXIT_DATE,
    'buyFees': buy_fees,
    'sellFees': sell_fees,
    'totalFees': round((buy_fees + sell_fees) * 100) / 100,
}
gross = round((EXIT - ENTRY) * QTY, 2)

new_positions = [p for p in positions if p['ticker'] != TICKER]
new_closed = [trade] + closed

# ---------------- Patch the sale-date snapshot ----------------
snap = next(s for s in snapshots if s['date'] == EXIT_DATE)
before = {k: snap.get(k) for k in
          ('dailyPnL', 'portfolioValue', 'capitalEngaged', 'unrealizedPnL',
           'realizedPnL', 'positionCount')}
leg = next(p for p in snap['positionsAtClose'] if p['ticker'] == TICKER)
leg_close = leg['closingPrice']

# Held leg currently inside dailyPnL, from the same source the browser used.
held_leg = round((leg_close - prev_close) * QTY, 2)
pc_change = pc.get('change')
if pc_change is not None:
    check = round(pc_change * QTY, 2)
    if abs(check - held_leg) > 1:
        sys.exit(f"ABORT: held leg disagrees — (close−prevClose)×qty={held_leg}, "
                 f"priceCache change×qty={check}.")
closed_today_leg = round((EXIT - prev_close) * QTY, 2)

new_pac = [p for p in snap['positionsAtClose'] if p['ticker'] != TICKER]
new_pv  = round(sum(p['closingPrice'] * p['quantity'] for p in new_pac), 2)
new_cap = round(sum(p['entryPrice'] * p['quantity'] for p in new_pac), 2)
after = {
    'dailyPnL': round(before['dailyPnL'] - held_leg + closed_today_leg, 2),
    'portfolioValue': new_pv,
    'capitalEngaged': new_cap,
    'unrealizedPnL': round(new_pv - new_cap, 2),
    'realizedPnL': round(before['realizedPnL'] + gross, 2),
    'positionCount': len(new_pac),
}
new_closing = {k: v for k, v in snap.get('closingPrices', {}).items() if k != TICKER}

# ---------------- Report ----------------
print("=== 2714.HK sale to be recorded ===")
print(f"  {QTY} sh  entry {ENTRY} ({ENTRY_DATE})  ->  exit {EXIT} ({EXIT_DATE})")
print(f"  gross P&L {gross:,.2f} HKD | buyFees {buy_fees} + sellFees {sell_fees} "
      f"= {trade['totalFees']} | net {gross - trade['totalFees']:,.2f}")
print(f"  prevClose {prev_close} (from the {PREV_DATE} snapshot, priceCache agrees: {pc_prev})")
print()
print("=== positions[] ===")
print(f"  {len(positions)} -> {len(new_positions)}  ({TICKER} removed)")
print("=== closedTrades[] ===")
print(f"  {len(closed)} -> {len(new_closed)}")
print(f"  Σ gross checksum {gross_before:,.2f} -> {round(gross_before + gross, 2):,.2f}")
print()
print(f"=== snapshot {EXIT_DATE} (browser-minted, settledAt={snap.get('settledAt')}) ===")
print(f"  dailyPnL       {before['dailyPnL']:>14,.2f} -> {after['dailyPnL']:>14,.2f}   "
      f"(held leg {held_leg:,.2f} out, closed-today leg {closed_today_leg:,.2f} in)")
for k in ('portfolioValue', 'capitalEngaged', 'unrealizedPnL', 'realizedPnL'):
    print(f"  {k:<14} {before[k]:>14,.2f} -> {after[k]:>14,.2f}")
print(f"  positionCount  {before['positionCount']:>14} -> {after['positionCount']:>14}")
print(f"  closingPrices  {len(snap.get('closingPrices', {}))} keys -> {len(new_closing)} keys")
print(f"  invariant pv - cap = unrealized: {round(after['portfolioValue'] - after['capitalEngaged'], 2)}"
      f" == {after['unrealizedPnL']}  "
      f"{'OK' if abs(after['portfolioValue'] - after['capitalEngaged'] - after['unrealizedPnL']) < 0.02 else 'FAIL'}")
print(f"  realizedPnL == Σ gross: {after['realizedPnL']} vs {round(gross_before + gross, 2)}  "
      f"{'OK' if abs(after['realizedPnL'] - (gross_before + gross)) < 0.5 else 'FAIL'}")
print()
print(f"NOTE: the {EXIT_DATE} snapshot is unsettled, so the 16:35 HKT cron rebuilds it")
print("      wholesale from these corrected arrays. These values are the consistent")
print("      intermediate state, not the final settled ones.")

if not APPLY:
    print("\n[DRY-RUN] No write.")
    sys.exit(0)

# ---------------- Apply ----------------
lu_before = ref.get().to_dict()['lastUpdated']
snap['positionsAtClose'] = new_pac
snap['closingPrices'] = new_closing
snap.update(after)

ref.update({'positions': new_positions, 'closedTrades': new_closed, 'snapshots': snapshots})
print("\n[APPLIED]")

print("polling lastUpdated for 30s to confirm no open app is republishing...")
lu0 = ref.get().to_dict()['lastUpdated']
time.sleep(30)
lu1 = ref.get().to_dict()['lastUpdated']
if lu0 != lu1:
    print(f"WARNING: lastUpdated moved ({lu0} -> {lu1}); an open app may have overwritten "
          f"this write. Re-run diagnose-2714.py.")
else:
    print(f"lastUpdated frozen ({lu1}), no republish detected. (was {lu_before} before the write)")

# ---------------- Verify ----------------
a = ref.get().to_dict()
assert not any(p['ticker'] == TICKER for p in a['positions']), "still open!"
at = [t for t in a['closedTrades'] if t['ticker'] == TICKER]
assert len(at) == 1, f"{len(at)} closedTrades for {TICKER}"
assert at[0]['exitPrice'] == EXIT and at[0]['quantity'] == QTY and at[0]['exitDate'] == EXIT_DATE
asnap = next(s for s in a['snapshots'] if s['date'] == EXIT_DATE)
assert not any(p['ticker'] == TICKER for p in asnap['positionsAtClose'])
assert TICKER not in asnap.get('closingPrices', {})
assert asnap['positionCount'] == len(asnap['positionsAtClose']) == len(a['positions'])
assert abs(asnap['portfolioValue'] - asnap['capitalEngaged'] - asnap['unrealizedPnL']) < 0.02
agross = round(sum((t['exitPrice'] - t['entryPrice']) * t['quantity'] for t in a['closedTrades']), 2)
assert abs(agross - asnap['realizedPnL']) < 0.5, f"checksum {agross} vs {asnap['realizedPnL']}"
assert len(a['snapshots']) == len(snapshots), "snapshot count changed!"
print(f"verified: still_open=False | 1 closedTrade {QTY}@{EXIT} exit {EXIT_DATE} | "
      f"posCount {asnap['positionCount']} | pv-cap=unrealized OK | Σ gross {agross:,.2f} "
      f"== realizedPnL OK")
