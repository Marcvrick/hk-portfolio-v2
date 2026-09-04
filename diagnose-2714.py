#!/usr/bin/env python3
"""
diagnose-2714.py
Read-only. Dany closed 2714.HK in the app on 2026-09-04 but it still shows open.
Inspect positions[], closedTrades[], transactions[], priceCache{}, snapshots[].
"""
import json
import firebase_admin
from firebase_admin import credentials, firestore

CRED   = 'hk-portfolio-v2/hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json'
DOC_ID = 'cNcZwUx3nQMV96TbB1kSkQ62u8U2'

cred = credentials.Certificate(CRED)
firebase_admin.initialize_app(cred)
doc = firestore.client().collection('portfolios').document(DOC_ID).get().to_dict()

NEEDLES = ('2714', '02714')


def hit(s):
    return any(n in str(s) for n in NEEDLES)


print("=== TOP-LEVEL doc keys ===")
for k, v in doc.items():
    if isinstance(v, list):
        print(f"  {k}: list[{len(v)}]")
    elif isinstance(v, dict):
        print(f"  {k}: dict[{len(v)}]")
    else:
        print(f"  {k}: {repr(v)[:120]}")

print("\n=== positions[] matching 2714 ===")
for p in doc.get('positions', []):
    if hit(p.get('ticker', '')):
        print(json.dumps(p, indent=2, default=str))

print("\n=== ALL open positions (ticker / qty / entry) ===")
for p in doc.get('positions', []):
    print(f"  {p.get('ticker'):>10}  qty={p.get('quantity')}  entry={p.get('entryPrice')}  "
          f"date={p.get('entryDate')}  id={p.get('id')}")

print("\n=== closedTrades[] matching 2714 ===")
for t in doc.get('closedTrades', []):
    if hit(t.get('ticker', '')):
        print(json.dumps(t, indent=2, default=str))

print("\n=== last 8 closedTrades (any ticker), by exitDate ===")
ct = doc.get('closedTrades', [])
ct_sorted = sorted(ct, key=lambda t: str(t.get('exitDate') or t.get('closeDate') or ''))
for t in ct_sorted[-8:]:
    print(f"  {t.get('ticker'):>10}  exit={t.get('exitDate') or t.get('closeDate')}  "
          f"qty={t.get('quantity')}  entry={t.get('entryPrice')} exitP={t.get('exitPrice')} "
          f"fees={t.get('totalFees')} id={t.get('id')}")

print("\n=== transactions[] matching 2714 ===")
for t in doc.get('transactions', []):
    if hit(t.get('ticker', '')):
        print(json.dumps(t, indent=2, default=str))

print("\n=== last 6 transactions (any) ===")
tx = doc.get('transactions', [])
for t in tx[-6:]:
    print("  ", json.dumps(t, default=str)[:300])

print("\n=== priceCache keys matching ===")
for k, v in doc.get('priceCache', {}).items():
    if hit(k):
        print(k, json.dumps(v, default=str))

print("\n=== snapshots ===")
snaps = sorted(doc.get('snapshots', []), key=lambda s: s['date'])
print("total:", len(snaps), "| latest 6 dates:", [s['date'] for s in snaps[-6:]])
for s in snaps[-6:]:
    hits = [p for p in s.get('positionsAtClose', []) if hit(p.get('ticker', ''))]
    ckeys = [k for k in s.get('closingPrices', {}) if hit(k)]
    print(f"\n-- {s['date']} dailyPnL={s.get('dailyPnL')} pv={s.get('portfolioValue')} "
          f"cap={s.get('capitalEngaged')} unreal={s.get('unrealizedPnL')} "
          f"realized={s.get('realizedPnL')} n={s.get('positionCount')} "
          f"settledAt={s.get('settledAt')} (len pac={len(s.get('positionsAtClose', []))})")
    for h in hits:
        print("   pac:", json.dumps(h, default=str))
    for k in ckeys:
        print("   closingPrices:", k, s['closingPrices'][k])

print("\n=== doc-level metadata ===")
for k in ('lastUpdated', 'lastSaved', 'updatedAt', 'lastModified', 'lastSync'):
    if k in doc:
        print(f"  {k}: {doc[k]}")
