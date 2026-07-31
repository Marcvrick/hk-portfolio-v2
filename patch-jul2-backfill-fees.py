#!/usr/bin/env python3
"""
patch-jul2-backfill-fees.py

Backfill trading fees on closedTrades that were re-added by repair patches
(or old imports) and never got buyFees/sellFees/totalFees. The app treats a
missing totalFees as ZERO, so those trades overstate realized P&L.

Replicates the app's OWN calcTradingFees (index.html ~L1689) EXACTLY so the
backfilled trades are computed identically to app-created ones:
  brokerage    = max(amount*0.0025, 100)
  depositCharge= isBuy ? min(max(ceil(qty/100)*5, 30), 200) : 0
  stampDuty    = ceil(amount*0.001)
  sfcLevy      = amount*0.000027
  afrcLevy     = amount*0.0000015
  hkexFee      = amount*0.0000565
  settlementFee= min(max(amount*0.00002, 2), 100)   # app has NOT adopted the Jun-2026 change
  total        = round(sum, 2)

Only touches trades where totalFees is missing/None (idempotent).
Snapshots are NOT touched: they store realizedPnL as GROSS by design.

DRY-RUN by default. Pass --apply to write.
"""
import sys, math
import firebase_admin
from firebase_admin import credentials, firestore

CRED = 'hk-portfolio-v2/hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json'
DOC_ID = 'cNcZwUx3nQMV96TbB1kSkQ62u8U2'
APPLY = '--apply' in sys.argv

def calc_fees(amount, qty, is_buy):
    brokerage = max(amount * 0.0025, 100)
    board_lots = math.ceil(qty / 100)
    deposit = min(max(board_lots * 5, 30), 200) if is_buy else 0
    stamp = math.ceil(amount * 0.001)
    sfc = amount * 0.000027
    afrc = amount * 0.0000015
    hkex = amount * 0.0000565
    settle = min(max(amount * 0.00002, 2), 100)
    return round((brokerage + deposit + stamp + sfc + afrc + hkex + settle) * 100) / 100

cred = credentials.Certificate(CRED)
firebase_admin.initialize_app(cred)
db = firestore.client()
ref = db.collection('portfolios').document(DOC_ID)
doc = ref.get().to_dict()
closed = doc.get('closedTrades', [])

def net_realized(trades):
    tot = 0.0
    for c in trades:
        gross = (c['exitPrice'] - c['entryPrice']) * c['quantity']
        fees = c.get('totalFees') or 0
        tot += (gross - fees) if fees > 0 else gross
    return tot

before = net_realized(closed)
touched = []
for c in closed:
    if c.get('totalFees') in (None, 0) and not (isinstance(c.get('totalFees'), (int, float)) and c.get('totalFees') > 0):
        # only backfill when genuinely absent (None or missing). A stored 0 is unexpected -> also backfill.
        if c.get('totalFees') is not None and c.get('totalFees') != 0:
            continue
        qty = c['quantity']
        ba = c['entryPrice'] * qty
        sa = c['exitPrice'] * qty
        bf = calc_fees(ba, qty, True)
        sf = calc_fees(sa, qty, False)
        tf = round((bf + sf) * 100) / 100
        c['buyFees'] = bf
        c['sellFees'] = sf
        c['totalFees'] = tf
        touched.append((c['ticker'], c.get('exitDate'), qty, bf, sf, tf))

print(f"{'Ticker':9} {'ExitDate':11} {'Qty':>7} {'buyFees':>9} {'sellFees':>9} {'totalFees':>10}")
print('-' * 60)
for t, ed, q, bf, sf, tf in touched:
    print(f"{t:9} {str(ed):11} {q:>7} {bf:>9,.2f} {sf:>9,.2f} {tf:>10,.2f}")
print('-' * 60)
added = sum(x[5] for x in touched)
after = net_realized(closed)
print(f"Trades backfilled : {len(touched)}")
print(f"Fees added total  : {added:,.2f}")
print(f"Realized P&L (net): {before:,.2f}  ->  {after:,.2f}   (Delta {after-before:+,.2f})")
print(f"Snapshots         : UNCHANGED (realizedPnL stored gross by design)")

if not APPLY:
    print("\n[DRY-RUN] No write. Re-run with --apply to commit.")
    sys.exit(0)

ref.update({'closedTrades': closed})
print("\n[APPLIED] closedTrades updated.")
# verify
v = ref.get().to_dict().get('closedTrades', [])
missing = [c['ticker'] for c in v if c.get('totalFees') in (None,)]
print(f"[VERIFY] trades still missing totalFees: {missing if missing else 'NONE'}")
print(f"[VERIFY] realized P&L (net) now: {net_realized(v):,.2f}")
