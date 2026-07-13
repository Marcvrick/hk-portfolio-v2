#!/usr/bin/env python3
"""diagnose-1810.py  (READ-ONLY) — is the 1810.HK sale in the cloud, or still open?"""
import firebase_admin
from firebase_admin import credentials, firestore

CRED = 'hk-portfolio-v2/hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json'
DOC_ID = 'cNcZwUx3nQMV96TbB1kSkQ62u8U2'
TICKER = '1810.HK'

firebase_admin.initialize_app(credentials.Certificate(CRED))
db = firestore.client()
doc = db.collection('portfolios').document(DOC_ID).get().to_dict()

positions = doc.get('positions', [])
closed = doc.get('closedTrades', [])

print(f"=== positions ({len(positions)} total) ===")
p = [x for x in positions if x.get('ticker') == TICKER]
if p:
    pos = p[0]
    print(f"  STILL OPEN: qty={pos.get('quantity')} entryPrice={pos.get('entryPrice')} "
          f"entryDate={pos.get('entryDate')} id={pos.get('id')}")
else:
    print(f"  {TICKER} NOT in positions (sale removed it, or never held)")

print(f"\n=== closedTrades for {TICKER} ===")
ct = [c for c in closed if c.get('ticker') == TICKER]
for c in ct:
    print(f"  qty={c.get('quantity')} entry={c.get('entryPrice')} exit={c.get('exitPrice')} "
          f"exitDate={c.get('exitDate')} fees={c.get('totalFees')} id={c.get('id')}")
if not ct:
    print("  None — no sale recorded")
