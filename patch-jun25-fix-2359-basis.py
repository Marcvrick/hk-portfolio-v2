#!/usr/bin/env python3
"""
patch-jun25-fix-2359-basis.py

Repair the cost-basis corruption from the partial-sale bug (closePosition reduced the
remaining shares' entry price by the realized profit). On 2026-06-25 Dany sold 500 of 800
shares of 2359.HK @ 148.2 (bought 128.7). The app wrongly rewrote the remaining 300 shares'
entryPrice to 96.201. The realized gain is already (correctly) booked in closedTrades, so
the remaining basis must stay 128.7.

Fixes:
  1. positions[2359.HK].entryPrice : 96.201 -> 128.7   (qty 300 unchanged)
  2. Any snapshot whose 2359.HK leg has the corrupted basis (entryPrice < 100, qty 300):
       - leg.entryPrice  -> 128.7
       - leg.pnl         -> (closingPrice - 128.7) * qty   (recomputed)
       - leg.pnlPercent  -> (closingPrice - 128.7)/128.7 * 100
       - capitalEngaged  -> recomputed = Σ leg.entryPrice*leg.quantity over positionsAtClose
       - unrealizedPnL   -> portfolioValue - capitalEngaged
     (portfolioValue, dailyPnL, realizedPnL, closingPrices are NOT touched — the entry-price
      bug does not affect them.)

Dry-run by default. Pass --apply to write.
"""
import sys
import firebase_admin
from firebase_admin import credentials, firestore

CRED = 'hk-portfolio-v2/hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json'
DOC_ID = 'cNcZwUx3nQMV96TbB1kSkQ62u8U2'
TICKER = '2359.HK'
CORRECT_ENTRY = 128.7
APPLY = '--apply' in sys.argv

firebase_admin.initialize_app(credentials.Certificate(CRED))
db = firestore.client()
ref = db.collection('portfolios').document(DOC_ID)
doc = ref.get().to_dict()
positions = doc.get('positions', [])
snapshots = doc.get('snapshots', [])

# ---- Idempotency ----
pos = next((p for p in positions if p.get('ticker') == TICKER), None)
if pos is None:
    print(f"ABORT: {TICKER} not found in positions."); sys.exit(1)
if abs(pos.get('entryPrice', 0) - CORRECT_ENTRY) < 0.01:
    print(f"Already fixed: {TICKER} entryPrice = {pos.get('entryPrice')}. Nothing to do."); sys.exit(0)

print(f"=== POSITION ===")
print(f"  before: qty={pos['quantity']} entryPrice={pos['entryPrice']}")
pos['entryPrice'] = CORRECT_ENTRY
print(f"  after : qty={pos['quantity']} entryPrice={pos['entryPrice']}")

print(f"\n=== SNAPSHOTS ===")
touched = 0
for s in snapshots:
    pac = s.get('positionsAtClose') or []
    leg = next((x for x in pac if x.get('ticker') == TICKER), None)
    if not leg:
        continue
    # Only the corrupted leg: basis below cost AND post-sale qty (skip the pre-sale 800-share legs).
    if not (leg.get('entryPrice', 999) < 100 and leg.get('quantity') == pos['quantity']):
        continue
    close = leg.get('closingPrice')
    qty = leg.get('quantity')
    old_cap, old_unr, old_legpnl = s.get('capitalEngaged'), s.get('unrealizedPnL'), leg.get('pnl')
    leg['entryPrice'] = CORRECT_ENTRY
    leg['pnl'] = round((close - CORRECT_ENTRY) * qty, 4)
    leg['pnlPercent'] = (close - CORRECT_ENTRY) / CORRECT_ENTRY * 100
    new_cap = round(sum(p.get('entryPrice', 0) * p.get('quantity', 0) for p in pac), 2)
    s['capitalEngaged'] = new_cap
    s['unrealizedPnL'] = round(s.get('portfolioValue', 0) - new_cap, 2)
    touched += 1
    print(f"  {s['date']}:")
    print(f"    leg.entryPrice {leg.get('entryPrice')!r} (was <100)  leg.pnl {old_legpnl} -> {leg['pnl']}")
    print(f"    capitalEngaged {old_cap} -> {new_cap}")
    print(f"    unrealizedPnL  {old_unr} -> {s['unrealizedPnL']}")
    print(f"    portfolioValue {s.get('portfolioValue')} (unchanged)  dailyPnL {s.get('dailyPnL')} (unchanged)  realizedPnL {s.get('realizedPnL')} (unchanged)")

print(f"\nSnapshots touched: {touched}")

if not APPLY:
    print("\n[DRY-RUN] No write. Re-run with --apply to commit.")
    sys.exit(0)

ref.update({'positions': positions, 'snapshots': snapshots})
print("\n[APPLIED] Firestore updated.")

# ---- Verify ----
v = ref.get().to_dict()
vp = next(p for p in v['positions'] if p.get('ticker') == TICKER)
print(f"[VERIFY] position {TICKER}: qty={vp['quantity']} entryPrice={vp['entryPrice']}")
for s in v['snapshots']:
    leg = next((x for x in (s.get('positionsAtClose') or []) if x.get('ticker') == TICKER), None)
    if leg and leg.get('quantity') == vp['quantity']:
        print(f"[VERIFY] snap {s['date']}: leg.entry={leg['entryPrice']} capEng={s['capitalEngaged']} unrealized={s['unrealizedPnL']} pv={s['portfolioValue']}")
