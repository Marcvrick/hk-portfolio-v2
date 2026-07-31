#!/usr/bin/env python3
"""Check which top-level fields each affected snapshot has, and whether the
invariants (pv = Σclose×qty ; unrealized = pv − capEngaged ; posCount = len(pac))
currently hold. Read-only."""
import firebase_admin
from firebase_admin import credentials, firestore

CRED = 'hk-portfolio-v2/hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json'
DOC_ID = 'cNcZwUx3nQMV96TbB1kSkQ62u8U2'
DATES = ('2026-06-03', '2026-06-08', '2026-06-09', '2026-06-10')

cred = credentials.Certificate(CRED)
firebase_admin.initialize_app(cred)
db = firestore.client()
doc = db.collection('portfolios').document(DOC_ID).get().to_dict()
snaps = {s['date']: s for s in doc.get('snapshots', []) if s.get('date') in DATES}

for d in DATES:
    s = snaps[d]
    pac = s.get('positionsAtClose') or []
    cp = s.get('closingPrices') or {}
    sum_pv = sum(p['closingPrice']*p['quantity'] for p in pac)
    cap = s.get('capitalEngaged')
    sum_cap = sum(p['entryPrice']*p['quantity'] for p in pac)
    print(f"\n### {d}")
    print(f"   top-level keys: {sorted(s.keys())}")
    print(f"   capitalEngaged field = {cap}   (Σ entry×qty over pac = {round(sum_cap,2)})")
    print(f"   portfolioValue = {s.get('portfolioValue')}   (Σ close×qty over pac = {round(sum_pv,2)})")
    print(f"   unrealizedPnL  = {s.get('unrealizedPnL')}")
    if cap is not None:
        print(f"   invariant pv-cap = {round(s.get('portfolioValue')-cap,2)}  vs unrealized {s.get('unrealizedPnL')}")
    print(f"   positionCount={s.get('positionCount')}  len(pac)={len(pac)}  len(cp)={len(cp)}")
