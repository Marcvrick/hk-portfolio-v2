#!/usr/bin/env python3
"""
diagnose-2359.py  (READ-ONLY)
Check current state of 2359.HK (WuXi AppTec) in Firestore after a partial sale that
corrupted the entry price (sold 500 @ 148.2 from 800 @ 128.7 -> entryPrice became 96.20).
  - current position: qty, entryPrice
  - the closedTrades entry for the partial sale (should be entry 128.7 / exit 148.2 / qty 500)
  - any snapshots that already captured the wrong cost basis (capitalEngaged)
"""
import firebase_admin
from firebase_admin import credentials, firestore

CRED = 'hk-portfolio-v2/hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json'
DOC_ID = 'cNcZwUx3nQMV96TbB1kSkQ62u8U2'
TICKER = '2359.HK'

cred = credentials.Certificate(CRED)
firebase_admin.initialize_app(cred)
db = firestore.client()
doc = db.collection('portfolios').document(DOC_ID).get().to_dict()

positions = doc.get('positions', [])
closed = doc.get('closedTrades', [])
snapshots = sorted(doc.get('snapshots', []), key=lambda s: s.get('date', ''))

print(f"=== positions ({len(positions)} total) ===")
p = [x for x in positions if x.get('ticker') == TICKER]
if p:
    pos = p[0]
    print(f"  OPEN: qty={pos.get('quantity')} entryPrice={pos.get('entryPrice')} "
          f"entryDate={pos.get('entryDate')} id={pos.get('id')}")
else:
    print("  NOT in positions")

print(f"\n=== closedTrades for {TICKER} ===")
ct = [c for c in closed if c.get('ticker') == TICKER]
for c in ct:
    print(f"  qty={c.get('quantity')} entry={c.get('entryPrice')} exit={c.get('exitPrice')} "
          f"exitDate={c.get('exitDate')} fees={c.get('totalFees')}")
if not ct:
    print("  None")

print(f"\n=== Snapshots (last 8) — does any carry {TICKER}? ===")
for s in snapshots[-8:]:
    pac = s.get('positionsAtClose') or []
    leg = [x for x in pac if x.get('ticker') == TICKER]
    legstr = f" 2359:{{qty={leg[0].get('quantity')},entry={leg[0].get('entryPrice')}}}" if leg else ""
    print(f"  {s.get('date')}: posCount={s.get('positionCount')} "
          f"capEng={s.get('capitalEngaged')} pv={s.get('portfolioValue')}{legstr}")
