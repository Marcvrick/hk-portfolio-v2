#!/usr/bin/env python3
"""
diagnose-1308.py
Check current state of 1308.HK in Firestore:
  - is it still in positions?
  - which snapshots (from 2026-06-01 onwards) have it in positionsAtClose / closingPrices?
  - is there already a closedTrades entry?
"""
import firebase_admin
from firebase_admin import credentials, firestore

CRED = 'hk-portfolio-v2/hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json'
DOC_ID = 'cNcZwUx3nQMV96TbB1kSkQ62u8U2'
TICKER = '1308.HK'

cred = credentials.Certificate(CRED)
firebase_admin.initialize_app(cred)
db = firestore.client()
ref = db.collection('portfolios').document(DOC_ID)
doc = ref.get().to_dict()

positions = doc.get('positions', [])
closed = doc.get('closedTrades', [])
snapshots = sorted(doc.get('snapshots', []), key=lambda s: s.get('date', ''))

print(f"=== positions ({len(positions)} total) ===")
p1308 = [p for p in positions if p.get('ticker') == TICKER]
if p1308:
    print(f"  STILL OPEN: {p1308[0]}")
else:
    print("  NOT in positions (already removed)")

print(f"\n=== closedTrades for {TICKER} ===")
ct = [c for c in closed if c.get('ticker') == TICKER]
if ct:
    for c in ct:
        print(f"  {c}")
else:
    print("  None found")

print(f"\n=== Snapshots >= 2026-06-01 containing {TICKER} ===")
for s in snapshots:
    d = s.get('date', '')
    if d < '2026-06-01':
        continue
    pac = s.get('positionsAtClose') or []
    cp = s.get('closingPrices') or {}
    has_pac = any(p.get('ticker') == TICKER for p in pac)
    has_cp = TICKER in cp
    print(f"  {d}: posCount={s.get('positionCount')} dailyPnL={s.get('dailyPnL')} "
          f"pv={s.get('portfolioValue')} "
          f"1308_in_pac={has_pac} 1308_in_cp={has_cp} "
          f"1308_close={cp.get(TICKER, 'n/a')}")
