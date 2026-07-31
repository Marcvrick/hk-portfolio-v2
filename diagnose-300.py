#!/usr/bin/env python3
"""
diagnose-300.py  (READ-ONLY)
Dany sold 800 of 300.HK @ 94.15 but the order was validated as a FULL close of
the 1200-share position. Diagnose the live state before any patch:
  - current position (if any) for 300.HK
  - the FULL closedTrade object(s) for 300.HK (qty, entry, exit, exitDate, fees, id)
  - priceCache entry for 300.HK
  - snapshot presence timeline: which snapshots carry a 300.HK leg, which dropped it,
    with date / qty / entry / close / capEng / pv / unrealized / dailyPnL / realizedPnL
  - the sale date = exitDate in the closedTrade (and first snapshot where the leg vanishes)
"""
import json
import firebase_admin
from firebase_admin import credentials, firestore

CRED = 'hk-portfolio-v2/hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json'
DOC_ID = 'cNcZwUx3nQMV96TbB1kSkQ62u8U2'
TICKER = '300.HK'

cred = credentials.Certificate(CRED)
firebase_admin.initialize_app(cred)
db = firestore.client()
doc = db.collection('portfolios').document(DOC_ID).get().to_dict()

positions = doc.get('positions', [])
closed = doc.get('closedTrades', [])
snapshots = sorted(doc.get('snapshots', []), key=lambda s: s.get('date', ''))
priceCache = doc.get('priceCache', {})

print(f"=== positions ({len(positions)} total) — looking for {TICKER} ===")
p = [x for x in positions if x.get('ticker') == TICKER]
if p:
    print("  " + json.dumps(p[0], ensure_ascii=False, default=str))
else:
    print(f"  NOT in positions (full-close state)")

print(f"\n=== closedTrades for {TICKER} (full objects) ===")
ct = [c for c in closed if c.get('ticker') == TICKER]
for c in ct:
    print("  " + json.dumps(c, ensure_ascii=False, default=str))
if not ct:
    print("  None")

# sale date from closedTrade
sale_dates = sorted({c.get('exitDate') for c in ct if c.get('exitDate')})
print(f"\n=== exitDate(s) in closedTrade: {sale_dates} ===")

print(f"\n=== priceCache for {TICKER} ===")
pc = priceCache.get(TICKER) or priceCache.get('0300.HK')
if pc:
    print("  " + json.dumps(pc, ensure_ascii=False, default=str))
else:
    print(f"  NOT in priceCache (keys sample: {list(priceCache.keys())[:5]})")

def fnum(x, w):
    return (f"{x:>{w}.1f}" if isinstance(x, (int, float)) else f"{'-':>{w}}")

def fraw(x, w):
    return (f"{str(x):>{w}}" if x is not None else f"{'-':>{w}}")

print(f"\n=== Snapshot presence timeline for {TICKER} (all {len(snapshots)} snapshots) ===")
print(f"  {'date':12} {'inPac':5} {'qty':>6} {'entry':>9} {'close':>9} | {'posCount':>8} {'capEng':>12} {'pv':>12} {'unreal':>12} {'dailyPnL':>11} {'realized':>11}")
last_held_date = None
first_dropped_date = None
for s in snapshots:
    pac = s.get('positionsAtClose') or []
    leg = [x for x in pac if x.get('ticker') == TICKER]
    d = s.get('date')
    if leg:
        l = leg[0]
        last_held_date = d
        print(f"  {d:12} {'YES':5} {fraw(l.get('quantity'),6)} {fnum(l.get('entryPrice'),9)} {fnum(l.get('closingPrice'),9)} | "
              f"{fraw(s.get('positionCount'),8)} {fnum(s.get('capitalEngaged'),12)} {fnum(s.get('portfolioValue'),12)} "
              f"{fnum(s.get('unrealizedPnL'),12)} {fnum(s.get('dailyPnL'),11)} {fnum(s.get('realizedPnL'),11)}")
    else:
        if first_dropped_date is None and sale_dates and d >= sale_dates[0]:
            first_dropped_date = d
        print(f"  {d:12} {'no':5} {'-':>6} {'-':>9} {'-':>9} | "
              f"{fraw(s.get('positionCount'),8)} {fnum(s.get('capitalEngaged'),12)} {fnum(s.get('portfolioValue'),12)} "
              f"{fnum(s.get('unrealizedPnL'),12)} {fnum(s.get('dailyPnL'),11)} {fnum(s.get('realizedPnL'),11)}")

print(f"\n=== Summary ===")
print(f"  last snapshot WITH {TICKER} leg: {last_held_date}")
print(f"  first snapshot WITHOUT {TICKER} leg (>= sale date): {first_dropped_date}")
print(f"  snapshots total: {len(snapshots)}")
n_post = len([s for s in snapshots if sale_dates and s.get('date', '') >= sale_dates[0]])
print(f"  snapshots on/after sale date ({sale_dates[0] if sale_dates else '?'}): {n_post}")
