#!/usr/bin/env python3
"""diagnose-300-detail.py  (READ-ONLY) — full 07-20 snapshot, raw 07-17 leg, sample position, realizedPnL recompute."""
import json, firebase_admin
from firebase_admin import credentials, firestore

CRED = 'hk-portfolio-v2/hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json'
DOC_ID = 'cNcZwUx3nQMV96TbB1kSkQ62u8U2'
cred = credentials.Certificate(CRED)
firebase_admin.initialize_app(cred)
db = firestore.client()
doc = db.collection('portfolios').document(DOC_ID).get().to_dict()

positions = doc.get('positions', [])
closed = doc.get('closedTrades', [])
snapshots = sorted(doc.get('snapshots', []), key=lambda s: s.get('date', ''))

def find(d):
    return next((s for s in snapshots if s.get('date') == d), None)

print("=== SAMPLE current position (field shape) ===")
if positions:
    print(json.dumps(positions[0], ensure_ascii=False, default=str))

print("\n=== 07-17 snapshot: 300.HK leg RAW + closingPrices[300.HK] ===")
s17 = find('2026-07-17')
if s17:
    leg = [x for x in (s17.get('positionsAtClose') or []) if x.get('ticker') == '300.HK']
    print("  leg:", json.dumps(leg[0], ensure_ascii=False, default=str) if leg else "NONE")
    print("  closingPrices['300.HK']:", (s17.get('closingPrices') or {}).get('300.HK'))
    print("  has settledAt:", s17.get('settledAt'), "| sources:", s17.get('sources'), "| provisional:", s17.get('provisional'))

print("\n=== 07-20 snapshot FULL ===")
s20 = find('2026-07-20')
if s20:
    top = {k: v for k, v in s20.items() if k not in ('positionsAtClose', 'closingPrices', 'priceProvenance')}
    print("  top-level:", json.dumps(top, ensure_ascii=False, default=str))
    cp = s20.get('closingPrices') or {}
    print(f"  closingPrices has '300.HK'? {'300.HK' in cp}  (value={cp.get('300.HK')})")
    print(f"  closingPrices key count: {len(cp)}")
    pp = s20.get('priceProvenance') or {}
    print(f"  priceProvenance has '300.HK'? {'300.HK' in pp}")
    if '300.HK' in pp:
        print("    ", json.dumps(pp.get('300.HK'), ensure_ascii=False, default=str))
    pac = s20.get('positionsAtClose') or []
    print(f"  positionsAtClose tickers: {[p.get('ticker') for p in pac]}")

print("\n=== realizedPnL recompute from closedTrades (GROSS) ===")
gross = 0.0
for c in closed:
    g = (c.get('exitPrice', 0) - c.get('entryPrice', 0)) * c.get('quantity', 0)
    gross += g
    if c.get('ticker') == '300.HK':
        print(f"  300.HK: qty={c.get('quantity')} entry={c.get('entryPrice')} exit={c.get('exitPrice')} -> gross {g:.2f}")
print(f"  SUM gross all closedTrades = {gross:.2f}")
print(f"  stored 07-20 realizedPnL    = {s20.get('realizedPnL') if s20 else 'n/a'}")
print(f"  stored 07-17 realizedPnL    = {s17.get('realizedPnL') if s17 else 'n/a'}")
print(f"  total closedTrades: {len(closed)}")
