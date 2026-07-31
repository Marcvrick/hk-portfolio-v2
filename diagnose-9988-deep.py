#!/usr/bin/env python3
"""Deep-inspect 9988.HK across the 4 affected snapshots: provenance, provisional,
pac entry, and any stored change fields. Read-only."""
import json
import firebase_admin
from firebase_admin import credentials, firestore

CRED = 'hk-portfolio-v2/hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json'
DOC_ID = 'cNcZwUx3nQMV96TbB1kSkQ62u8U2'
TICKER = '9988.HK'
DATES = ('2026-06-03', '2026-06-08', '2026-06-09', '2026-06-10')

cred = credentials.Certificate(CRED)
firebase_admin.initialize_app(cred)
db = firestore.client()
doc = db.collection('portfolios').document(DOC_ID).get().to_dict()
snaps = {s['date']: s for s in doc.get('snapshots', []) if s.get('date') in DATES}

for d in DATES:
    s = snaps.get(d)
    if not s:
        print(f"\n### {d}: NO SNAPSHOT")
        continue
    print(f"\n### {d}  posCount={s.get('positionCount')} dailyPnL={s.get('dailyPnL')} "
          f"pv={s.get('portfolioValue')} realizedPnL={s.get('realizedPnL')} "
          f"unrealizedPnL={s.get('unrealizedPnL')} provisional={s.get('provisional')}")
    print(f"    closingPrices[9988] = {s.get('closingPrices',{}).get(TICKER)}")
    pac = next((p for p in (s.get('positionsAtClose') or []) if p.get('ticker')==TICKER), None)
    print(f"    pac entry = {json.dumps(pac, default=str)}")
    prov = (s.get('priceProvenance') or {}).get(TICKER)
    print(f"    provenance = {json.dumps(prov, default=str)}")
