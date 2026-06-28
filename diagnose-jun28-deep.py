#!/usr/bin/env python3
"""
diagnose-jun28-deep.py  (READ-ONLY)
Find the LAST GOOD STATE for 2359 (WuXi) and 1810 (Xiaomi) before the overwrite.
  - full-history presence timeline in snapshots (qty/entry/close) for each
  - realizedPnL trajectory across ALL snapshots (when did it move off 9979?)
  - priceCache entries for both
  - all closedTrades sorted by exitDate (what realized history survives)
"""
import firebase_admin
from firebase_admin import credentials, firestore

CRED = 'hk-portfolio-v2/hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json'
DOC_ID = 'cNcZwUx3nQMV96TbB1kSkQ62u8U2'

cred = credentials.Certificate(CRED)
firebase_admin.initialize_app(cred)
db = firestore.client()
doc = db.collection('portfolios').document(DOC_ID).get().to_dict()

closed = doc.get('closedTrades', [])
snapshots = sorted(doc.get('snapshots', []), key=lambda s: s.get('date', ''))
pc = doc.get('priceCache') or {}

def V(num):
    return {f"{num}.HK", f"{int(num):04d}.HK", f"{int(num)}.HK", f"0{num}.HK"}

for label, num in (("WuXi", "2359"), ("Xiaomi", "1810")):
    vs = V(num)
    print(f"\n========== {label} ({num}) — full snapshot presence ==========")
    found_any = False
    for s in snapshots:
        pac = s.get('positionsAtClose') or []
        leg = [x for x in pac if x.get('ticker') in vs]
        if leg:
            found_any = True
            l = leg[0]
            print(f"  {s.get('date')}: qty={l.get('quantity')} entry={l.get('entryPrice')} "
                  f"close={l.get('closingPrice')} pnl={l.get('pnl')}")
    if not found_any:
        print("  NEVER present in any snapshot's positionsAtClose")
    print(f"  priceCache: ", {k: pc.get(k) for k in pc if k in vs} or "absent")

print("\n\n========== realizedPnL trajectory (ALL snapshots) ==========")
prev = None
for s in snapshots:
    r = s.get('realizedPnL')
    mark = ""
    if prev is not None and r != prev:
        mark = f"  <<< CHANGED {prev} -> {r}"
    print(f"  {s.get('date')}: realizedPnL={r}{mark}")
    prev = r

print("\n\n========== all closedTrades (sorted by exitDate) ==========")
for c in sorted(closed, key=lambda x: x.get('exitDate', '')):
    realized = None
    try:
        realized = (c.get('exitPrice') - c.get('entryPrice')) * c.get('quantity')
    except Exception:
        pass
    print(f"  {c.get('exitDate')}  {c.get('ticker'):10s} qty={c.get('quantity')} "
          f"entry={c.get('entryPrice')} exit={c.get('exitPrice')} realized={realized}")
