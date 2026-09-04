#!/usr/bin/env python3
"""
diagnose-2714-scan.py
Read-only. Scan EVERY doc in portfolios/ and us-portfolios/ for a 2714 trace,
to rule out "the close landed in a different document".
"""
import firebase_admin
from firebase_admin import credentials, firestore

CRED = 'hk-portfolio-v2/hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json'
cred = credentials.Certificate(CRED)
firebase_admin.initialize_app(cred)
db = firestore.client()

for coll in ('portfolios', 'us-portfolios'):
    print(f"\n===== collection {coll} =====")
    for snap in db.collection(coll).stream():
        d = snap.to_dict()
        pos = d.get('positions', [])
        ct = d.get('closedTrades', [])
        sn = d.get('snapshots', [])
        print(f"\n-- doc {snap.id}  owner={d.get('ownerEmail')}  "
              f"positions={len(pos)} closedTrades={len(ct)} snapshots={len(sn)} "
              f"lastUpdated={d.get('lastUpdated')}")
        for p in pos:
            if '2714' in str(p.get('ticker', '')):
                print("   POS 2714:", p)
        for t in ct:
            if '2714' in str(t.get('ticker', '')):
                print("   TRADE 2714:", t)
