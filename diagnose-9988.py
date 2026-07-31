#!/usr/bin/env python3
"""
diagnose-9988.py
Check current state of 9988.HK (Alibaba) in Firestore:
  - is it still in positions? (qty, entryPrice, entryDate)
  - which snapshots (from 2026-05-28 onwards) have it in positionsAtClose / closingPrices?
  - is there already a closedTrades entry?
Sale reported: 2026-05-29 @ HK$121.4 (qty unknown until we read positions).
"""
import firebase_admin
from firebase_admin import credentials, firestore

CRED = 'hk-portfolio-v2/hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json'
DOC_ID = 'cNcZwUx3nQMV96TbB1kSkQ62u8U2'
TICKER = '9988.HK'

cred = credentials.Certificate(CRED)
firebase_admin.initialize_app(cred)
db = firestore.client()
ref = db.collection('portfolios').document(DOC_ID)
doc = ref.get().to_dict()

positions = doc.get('positions', [])
closed = doc.get('closedTrades', [])
snapshots = sorted(doc.get('snapshots', []), key=lambda s: s.get('date', ''))

print(f"=== positions ({len(positions)} total) ===")
p = [x for x in positions if x.get('ticker') == TICKER]
if p:
    print(f"  STILL OPEN: {p[0]}")
else:
    print("  NOT in positions (already removed)")

print(f"\n=== closedTrades for {TICKER} ===")
ct = [c for c in closed if c.get('ticker') == TICKER]
if ct:
    for c in ct:
        print(f"  {c}")
else:
    print("  None found")

print(f"\n=== Snapshots >= 2026-05-28 containing {TICKER} ===")
for s in snapshots:
    d = s.get('date', '')
    if d < '2026-05-28':
        continue
    pac = s.get('positionsAtClose') or []
    cp = s.get('closingPrices') or {}
    has_pac = any(x.get('ticker') == TICKER for x in pac)
    has_cp = TICKER in cp
    flag = '  <-- has 9988' if (has_pac or has_cp) else ''
    print(f"  {d}: posCount={s.get('positionCount')} dailyPnL={s.get('dailyPnL')} "
          f"pv={s.get('portfolioValue')} in_pac={has_pac} in_cp={has_cp} "
          f"close={cp.get(TICKER, 'n/a')}{flag}")

print(f"\n=== All snapshot dates (for gap detection) ===")
print("  " + ", ".join(s.get('date', '?') for s in snapshots if s.get('date', '') >= '2026-05-26'))
