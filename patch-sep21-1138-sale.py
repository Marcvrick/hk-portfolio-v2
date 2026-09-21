#!/usr/bin/env python3
"""
patch-sep21-1138-sale.py
Record the 1138.HK (Cosco Ship) sale Dany executed at the broker and entered in
the app on 2026-09-21, and that never reached Firestore: full exit, 10,000
shares @ 19.76.

Why the write never landed (wiki/incidents.md 2026-09-21): offline persistence
is off, so the pre-write guard read and set() resolve only on a server ACK, and
on a link that drops mid-flight they resolve never. closePosition awaited them
with no timeout, so the close hung — button stuck on "Enregistrement...", no
alert, no rollback. Dany confirms: the screen did nothing, it was stuck. The
live Security Rules reject any update that shrinks closedTrades, so the absence
of a 1138 row (56 trades, none of them 1138) proves no write ever landed; this
is not a reverted write. Client fix shipped in f82dcd1; this script is the data
repair only.

What it changes:
  positions[]     remove the 1138.HK leg (10,000 @ 18.042, entered 2026-09-04)
  closedTrades[]  prepend the sale, fees from the ported calcTradingFees
  snapshots[]     the 2026-09-21 snapshot only (the single post-sale snapshot):
                    - drop the leg from positionsAtClose + closingPrices +
                      priceProvenance (all three, or pac ends up longer than
                      closingPrices, which is the browser-minted signature
                      wiki/reliability-risks.md #14 sweeps for)
                    - RECOMPUTE pv / capitalEngaged / unrealized / count from
                      the filtered positionsAtClose (never subtract per-field
                      deltas — wiki/recording-a-sale.md Step 4)
                    - realizedPnL += gross (exit − entry) × qty
                    - dailyPnL: swap the held leg (close − prevClose) × qty for
                      the closed-today leg (exit − prevClose) × qty, the same
                      formula update.py uses

DIFFERENCE FROM patch-sep4-2714-sale.py: that snapshot was browser-minted, so
the next cron rebuilt it wholesale and the patched values were only an
intermediate state. THIS snapshot is cron-settled (settledAt 18:04 HKT) and
nothing will rebuild it, so the values written here are final. Per the
2026-09-09 rule, the dry-run therefore prints every calendar tile this moves,
before -> after.

Idempotent: aborts if a 1138 closedTrade already exists, if the position is
absent or disagrees with the constants, if any snapshot after the sale date
carries the ticker, or if the book's realizedPnL checksum is already broken.

Usage:
  python3 patch-sep21-1138-sale.py           # dry-run
  python3 patch-sep21-1138-sale.py --apply   # CLOSE THE APP FIRST (risk #11-bis:
                                             # an open tab republishes its whole
                                             # state every ~15s and erases this)
"""
import math
import sys
import time
import firebase_admin
from firebase_admin import credentials, firestore

CRED   = 'hk-portfolio-v2/hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json'
DOC_ID = 'cNcZwUx3nQMV96TbB1kSkQ62u8U2'

TICKER      = '1138.HK'
NAME        = 'Cosco Ship'
QTY         = 10000
ENTRY       = 18.042
ENTRY_DATE  = '2026-09-04'
EXIT        = 19.76
EXIT_DATE   = '2026-09-21'
PREV_DATE   = '2026-09-18'   # prior trading day, source of prevClose

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


firebase_admin.initialize_app(credentials.Certificate(CRED))
ref = firestore.client().collection('portfolios').document(DOC_ID)
doc = ref.get().to_dict()

positions   = doc['positions']
closed      = doc['closedTrades']
snapshots   = doc['snapshots']
price_cache = doc.get('priceCache', {})

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

prev_snap = next((s for s in snapshots if s['date'] == PREV_DATE), None)
if prev_snap is None:
    sys.exit(f"ABORT: no {PREV_DATE} snapshot to source prevClose from.")

# Cross-check: sum of closedTrades gross must equal the stored realizedPnL.
gross_before = round(sum((t['exitPrice'] - t['entryPrice']) * t['quantity'] for t in closed), 2)
if abs(gross_before - round(prev_snap['realizedPnL'], 2)) > 0.5:
    sys.exit(f"ABORT: sum of closedTrades gross ({gross_before}) != {PREV_DATE} realizedPnL "
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

# Sanity on the fill itself: an exit outside the session's own range is a typo,
# not a trade. Day range is not stored, so bound it by the two closes it sits
# between, widened 8% each way for an intraday swing.
exit_day_close = next(s for s in snapshots if s['date'] == EXIT_DATE).get('closingPrices', {}).get(TICKER, prev_close)
lo, hi = sorted((prev_close, exit_day_close))
if not (lo * 0.92 <= EXIT <= hi * 1.08):
    sys.exit(f"ABORT: exit {EXIT} is outside [{lo * 0.92:.2f}, {hi * 1.08:.2f}], the plausible "
             f"range between the {PREV_DATE} and {EXIT_DATE} closes. Confirm the fill.")

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

# Held leg currently inside dailyPnL, cross-checked against priceCache's own move.
held_leg = round((leg_close - prev_close) * QTY, 2)
pc_change = pc.get('change')
if pc_change is not None:
    check = round(pc_change * QTY, 2)
    if abs(check - held_leg) > 1:
        sys.exit(f"ABORT: held leg disagrees — (close-prevClose)*qty={held_leg}, "
                 f"priceCache change*qty={check}.")
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
new_prov = {k: v for k, v in (snap.get('priceProvenance') or {}).items() if k != TICKER}

# ---------------- Report ----------------
print("=== 1138.HK sale to be recorded ===")
print(f"  {QTY:,} sh  entry {ENTRY} ({ENTRY_DATE})  ->  exit {EXIT} ({EXIT_DATE})")
print(f"  gross P&L {gross:,.2f} HKD | buyFees {buy_fees} + sellFees {sell_fees} "
      f"= {trade['totalFees']} | net {gross - trade['totalFees']:,.2f}")
print(f"  prevClose {prev_close} (from the {PREV_DATE} snapshot, priceCache agrees: {pc_prev})")
print()
print("=== positions[] ===")
print(f"  {len(positions)} -> {len(new_positions)}  ({TICKER} removed)")
print("=== closedTrades[] ===")
print(f"  {len(closed)} -> {len(new_closed)}")
print(f"  sum gross checksum {gross_before:,.2f} -> {round(gross_before + gross, 2):,.2f}")
print()
print(f"=== snapshot {EXIT_DATE} (CRON-SETTLED at {snap.get('settledAt')}) ===")
print(f"  dailyPnL       {before['dailyPnL']:>14,.2f} -> {after['dailyPnL']:>14,.2f}   "
      f"(held leg {held_leg:,.2f} out, closed-today leg {closed_today_leg:,.2f} in)")
for k in ('portfolioValue', 'capitalEngaged', 'unrealizedPnL', 'realizedPnL'):
    print(f"  {k:<14} {before[k]:>14,.2f} -> {after[k]:>14,.2f}")
print(f"  positionCount  {before['positionCount']:>14} -> {after['positionCount']:>14}")
print(f"  closingPrices    {len(snap.get('closingPrices', {}))} keys -> {len(new_closing)} keys")
print(f"  priceProvenance  {len(snap.get('priceProvenance') or {})} keys -> {len(new_prov)} keys")
print(f"  invariant pv - cap = unrealized: "
      f"{round(after['portfolioValue'] - after['capitalEngaged'], 2)} == {after['unrealizedPnL']}  "
      f"{'OK' if abs(after['portfolioValue'] - after['capitalEngaged'] - after['unrealizedPnL']) < 0.02 else 'FAIL'}")
print(f"  realizedPnL == sum gross: {after['realizedPnL']} vs {round(gross_before + gross, 2)}  "
      f"{'OK' if abs(after['realizedPnL'] - (gross_before + gross)) < 0.5 else 'FAIL'}")
print()
print("=== CALENDAR TILES THIS MOVES (2026-09-09 rule) ===")
print(f"  {EXIT_DATE}: {before['dailyPnL']:+,.2f} -> {after['dailyPnL']:+,.2f} HKD")
print("  no other tile moves: this is the only snapshot dated on or after the sale.")
print(f"  This snapshot is SETTLED, so no cron will rebuild it. These values are final.")

if not APPLY:
    print("\n[DRY-RUN] No write.")
    sys.exit(0)

# ---------------- Apply ----------------
lu_before = ref.get().to_dict()['lastUpdated']
snap['positionsAtClose'] = new_pac
snap['closingPrices'] = new_closing
if snap.get('priceProvenance') is not None:
    snap['priceProvenance'] = new_prov
snap.update(after)

ref.update({'positions': new_positions, 'closedTrades': new_closed, 'snapshots': snapshots})
print("\n[APPLIED]")

print("polling lastUpdated for 30s to confirm no open app is republishing...")
lu0 = ref.get().to_dict()['lastUpdated']
time.sleep(30)
lu1 = ref.get().to_dict()['lastUpdated']
if lu0 != lu1:
    print(f"WARNING: lastUpdated moved ({lu0} -> {lu1}); an open app may have overwritten "
          f"this write. Re-run the diagnosis before trusting it.")
else:
    print(f"lastUpdated frozen ({lu1}), no republish detected. (was {lu_before} before the write)")

# ---------------- Verify ----------------
a = ref.get().to_dict()
assert not any(p['ticker'] == TICKER for p in a['positions']), "still open!"
at = [t for t in a['closedTrades'] if t['ticker'] == TICKER]
assert len(at) == 1, f"{len(at)} closedTrades for {TICKER}"
assert at[0]['exitPrice'] == EXIT and at[0]['quantity'] == QTY and at[0]['exitDate'] == EXIT_DATE
assert at[0]['totalFees'] > 0, "closedTrade written without fees"
asnap = next(s for s in a['snapshots'] if s['date'] == EXIT_DATE)
assert not any(p['ticker'] == TICKER for p in asnap['positionsAtClose'])
assert TICKER not in asnap.get('closingPrices', {})
assert TICKER not in (asnap.get('priceProvenance') or {})
assert asnap['positionCount'] == len(asnap['positionsAtClose']) == len(a['positions'])
assert len(asnap['positionsAtClose']) == len(asnap['closingPrices']), "pac/closingPrices key gap"
assert abs(asnap['portfolioValue'] - asnap['capitalEngaged'] - asnap['unrealizedPnL']) < 0.02
agross = round(sum((t['exitPrice'] - t['entryPrice']) * t['quantity'] for t in a['closedTrades']), 2)
assert abs(agross - asnap['realizedPnL']) < 0.5, f"checksum {agross} vs {asnap['realizedPnL']}"
assert asnap['settledAt'], "settledAt lost — a browser could now mint over this date"
assert len(a['snapshots']) == len(snapshots), "snapshot count changed!"

# Independent recomputation of dailyPnL from first principles: every held leg
# priced against the PREV_DATE close, plus the closed-today leg. Drift must be ~0.
prev_closes = prev_snap.get('closingPrices', {})
held = sum((p['closingPrice'] - prev_closes[p['ticker']]) * p['quantity']
           for p in asnap['positionsAtClose'] if p['ticker'] in prev_closes)
recomputed = round(held + closed_today_leg, 2)
drift = round(asnap['dailyPnL'] - recomputed, 2)
print(f"verified: still_open=False | 1 closedTrade {QTY:,}@{EXIT} exit {EXIT_DATE} | "
      f"posCount {asnap['positionCount']} | pv-cap=unrealized OK | sum gross {agross:,.2f} "
      f"== realizedPnL OK")
print(f"independent dailyPnL recomputation: stored {asnap['dailyPnL']:,.2f} vs "
      f"recomputed {recomputed:,.2f} -> drift {drift:,.2f}"
      f"{'  (positions entered after ' + PREV_DATE + ' are excluded from the recomputation)' if drift else ''}")
