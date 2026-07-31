#!/usr/bin/env python3
"""
verify-jun8.py
Verify Jun 8 dailyPnL is correct after the 1308.HK patch.

Logic:
  dailyPnL on a given day = sum over all positions held that day of:
    (closing_price_day - closing_price_prev_day) * qty
  plus for any positions closed that day:
    (exit_price - closing_price_prev_day) * qty

  prevDay for Jun 8 = Jun 3 (no Jun 4 / Jun 5 snapshots exist).
"""
import firebase_admin
from firebase_admin import credentials, firestore

CRED = 'hk-portfolio-v2/hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json'
DOC_ID = 'cNcZwUx3nQMV96TbB1kSkQ62u8U2'

cred = credentials.Certificate(CRED)
firebase_admin.initialize_app(cred)
db = firestore.client()
ref = db.collection('portfolios').document(DOC_ID)
doc = ref.get().to_dict()

snapshots = {s['date']: s for s in doc.get('snapshots', []) if s.get('date')}

jun3 = snapshots.get('2026-06-03', {})
jun8 = snapshots.get('2026-06-08', {})

jun3_closes = jun3.get('closingPrices', {})
jun8_closes = jun8.get('closingPrices', {})
jun8_pac    = {p['ticker']: p for p in (jun8.get('positionsAtClose') or [])}

print("=== Jun 8 snapshot (current state) ===")
print(f"  stored dailyPnL  : {jun8.get('dailyPnL')}")
print(f"  positionCount    : {jun8.get('positionCount')}")
print(f"  portfolioValue   : {jun8.get('portfolioValue')}")
print(f"  realizedPnL      : {jun8.get('realizedPnL')}")
print()

print("=== Recomputed dailyPnL (open positions) ===")
total = 0.0
rows = []
for ticker, close_d in sorted(jun8_closes.items()):
    prev = jun3_closes.get(ticker)
    if prev is None:
        rows.append((ticker, '?', close_d, '  <-- no Jun 3 close, SKIP'))
        continue
    pac = jun8_pac.get(ticker, {})
    qty = pac.get('quantity', 0)
    contrib = (close_d - prev) * qty
    total += contrib
    rows.append((ticker, prev, close_d, qty, round(contrib, 2)))

for r in rows:
    if len(r) == 4:
        print(f"  {r[0]:12s}  prev={r[1]}  close={r[2]}  {r[3]}")
    else:
        print(f"  {r[0]:12s}  prev={r[1]:.2f}  close={r[2]:.2f}  qty={r[3]}  contrib={r[4]:+.2f}")

print(f"\n  RECOMPUTED total : {round(total, 2)}")
print(f"  STORED   total   : {jun8.get('dailyPnL')}")
drift = round(total - (jun8.get('dailyPnL') or 0), 2)
print(f"  DRIFT            : {drift}  (expect ~0)")

print()
print("=== 1308.HK in Jun 8? ===")
print(f"  in closingPrices : {'1308.HK' in jun8_closes}")
print(f"  in positionsAtClose: {'1308.HK' in jun8_pac}")
