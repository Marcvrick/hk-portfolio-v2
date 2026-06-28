#!/usr/bin/env python3
"""
diagnose-jun28-wuxi-xiaomi.py  (READ-ONLY)
Dany: 1810 (Xiaomi) missing, no profit shown on WuXi (2359) partial sale, missing lines.
Check live Firestore for:
  - 2359.HK (WuXi): open position + closedTrades (the ~9.75k realized from the 500-share partial)
  - 1810.HK (Xiaomi): is it in positions? closedTrades? snapshots? a re-buy lost?
  - realizedPnL trajectory across last snapshots vs Σ closedTrades (does the booked profit reach the app?)
"""
import firebase_admin
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

def variants(num):
    return {f"{num}.HK", f"{int(num):04d}.HK", f"{int(num)}.HK", f"0{num}.HK"}

for label, num in (("WuXi", "2359"), ("Xiaomi", "1810")):
    V = variants(num)
    print(f"\n========== {label} ({num}) ==========")
    op = [p for p in positions if p.get('ticker') in V]
    print(f"-- positions --")
    if op:
        for p in op:
            print(f"  OPEN {p.get('ticker')}: qty={p.get('quantity')} entry={p.get('entryPrice')} "
                  f"entryDate={p.get('entryDate')} id={p.get('id')}")
    else:
        print("  NOT in positions[]")
    print(f"-- closedTrades --")
    ct = [c for c in closed if c.get('ticker') in V]
    if ct:
        for c in ct:
            realized = None
            try:
                realized = (c.get('exitPrice') - c.get('entryPrice')) * c.get('quantity')
            except Exception:
                pass
            print(f"  {c.get('ticker')}: qty={c.get('quantity')} entry={c.get('entryPrice')} "
                  f"exit={c.get('exitPrice')} exitDate={c.get('exitDate')} "
                  f"realized={realized} storedRealized={c.get('realizedPnL')}")
    else:
        print("  None")
    print(f"-- presence in last 10 snapshots (positionsAtClose) --")
    for s in snapshots[-10:]:
        pac = s.get('positionsAtClose') or []
        leg = [x for x in pac if x.get('ticker') in V]
        if leg:
            l = leg[0]
            print(f"  {s.get('date')}: qty={l.get('quantity')} entry={l.get('entryPrice')} "
                  f"close={l.get('closingPrice')} pnl={l.get('pnl')}")

print("\n\n========== realizedPnL: does booked profit reach the app? ==========")
sum_closed = 0
for c in closed:
    try:
        sum_closed += (c.get('exitPrice') - c.get('entryPrice')) * c.get('quantity')
    except Exception:
        pass
print(f"Σ closedTrades realized (recomputed entry->exit) = {sum_closed:,.0f}")
print(f"closedTrades count = {len(closed)}")
print(f"\nrealizedPnL stored per snapshot (last 12):")
for s in snapshots[-12:]:
    print(f"  {s.get('date')}: realizedPnL={s.get('realizedPnL')} "
          f"dailyPnL={s.get('dailyPnL')} posCount={s.get('positionCount')} "
          f"settledAt={'Y' if s.get('settledAt') else '-'}")

print(f"\nTop-level doc realizedPnL field = {doc.get('realizedPnL')}")
print(f"open positions count = {len(positions)}")
print("\n=== all open tickers ===")
print(", ".join(sorted(p.get('ticker','?') for p in positions)))
