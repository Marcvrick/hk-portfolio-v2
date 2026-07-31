#!/usr/bin/env python3
"""
patch-jun3-add-1167.py

Retroactively add 1167.HK (Jacobio Pharmaceuticals) — bought 5100 @ 4.5 on 2026-06-03,
never recorded in the app. Backfills every snapshot from the entry date onward so the
position reads as if it had been held since Jun 3.

Writes:
  - positions[]: append 1167.HK (qty 5100, entry 4.5, entryDate 2026-06-03)
  - priceCache["1167.HK"]: latest close 4.43 / prevClose 4.29 (next cron overwrites with live)
  - every snapshot with date >= 2026-06-03:
      * positionsAtClose += 1167 leg (that date's close)
      * closingPrices["1167.HK"] = that date's close
      * positionCount += 1
      * portfolioValue  += close*qty
      * capitalEngaged  += 4.5*qty (constant 22,950)
      * unrealizedPnL    = portfolioValue - capitalEngaged   (recomputed)
      * dailyPnL        += (close - priorTradingDayClose)*qty
                          (entry day 2026-06-03 uses entryPrice as the baseline)

Daily closes are embedded (Yahoo, verified 2026-06-25) so the patch is deterministic and
reviewable. priorTradingDayClose is the trading day immediately before each snapshot date
(gap-proof: Jun 4/5 have no snapshot but are still the baseline chain), per wiki
recording-a-sale Step 4.

Dry-run by default. Pass --apply to write.
"""
import sys
from datetime import datetime, timezone, timedelta
import firebase_admin
from firebase_admin import credentials, firestore

CRED = 'hk-portfolio-v2/hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json'
DOC_ID = 'cNcZwUx3nQMV96TbB1kSkQ62u8U2'
TICKER = '1167.HK'
NAME = 'Jacobio'
QTY = 5100
ENTRY_PRICE = 4.5
ENTRY_DATE = '2026-06-03'
ENTRY_MV = ENTRY_PRICE * QTY            # 22,950
APPLY = '--apply' in sys.argv

# Yahoo daily closes (auto_adjust=False), verified 2026-06-25
CLOSES = {
    '2026-06-02': 4.5,  '2026-06-03': 4.3,  '2026-06-04': 4.12, '2026-06-05': 4.14,
    '2026-06-08': 4.32, '2026-06-09': 4.33, '2026-06-10': 4.45, '2026-06-11': 4.81,
    '2026-06-12': 4.65, '2026-06-15': 4.49, '2026-06-16': 4.43, '2026-06-17': 4.53,
    '2026-06-18': 4.41, '2026-06-22': 4.44, '2026-06-23': 4.59, '2026-06-24': 4.29,
    '2026-06-25': 4.43,
}
CLOSE_DATES = sorted(CLOSES)
LATEST = '2026-06-25'

def prior_trading_close(d):
    """Close of the trading day immediately before d (gap-proof)."""
    i = CLOSE_DATES.index(d)
    return CLOSES[CLOSE_DATES[i - 1]]

firebase_admin.initialize_app(credentials.Certificate(CRED))
db = firestore.client()
ref = db.collection('portfolios').document(DOC_ID)
doc = ref.get().to_dict()
positions = list(doc.get('positions', []))

# ---- Idempotency ----
if any(p.get('ticker') == TICKER for p in positions):
    print(f"ABORT: {TICKER} already in positions. Nothing to do."); sys.exit(0)

# 1. Position
HKT = timezone(timedelta(hours=8))
new_position = {
    'id': int(datetime(2026, 6, 3, 9, 30, tzinfo=HKT).timestamp() * 1000),
    'ticker': TICKER, 'name': NAME, 'quantity': QTY,
    'entryPrice': ENTRY_PRICE, 'entryDate': ENTRY_DATE,
    'currentPrice': CLOSES[LATEST],
}
new_positions = positions + [new_position]

# 2. priceCache
prev = CLOSES['2026-06-24']
change = round(CLOSES[LATEST] - prev, 4)
price_cache = dict(doc.get('priceCache', {}))
price_cache[TICKER] = {
    'success': True, 'price': CLOSES[LATEST], 'previousClose': prev,
    'change': change, 'changePercent': round(change / prev * 100, 4),
    'currency': 'HKD', 'lastUpdated': datetime.now(HKT).isoformat(),
}

def make_leg(close):
    pnl = round((close - ENTRY_PRICE) * QTY, 2)
    return {
        'ticker': TICKER, 'name': NAME, 'quantity': QTY,
        'entryPrice': ENTRY_PRICE, 'entryDate': ENTRY_DATE,
        'closingPrice': close, 'marketValue': round(close * QTY, 2),
        'pnl': pnl, 'pnlPercent': round((close - ENTRY_PRICE) / ENTRY_PRICE * 100, 4),
    }

# 3. Patch snapshots
snapshots = list(doc.get('snapshots', []))
print(f"=== Position ===\n  add {TICKER} ({NAME}) qty={QTY} entry={ENTRY_PRICE} entryDate={ENTRY_DATE}")
print(f"  positions {len(positions)} -> {len(new_positions)}")
print(f"\n=== Snapshots patched (>= {ENTRY_DATE}) ===")
print(f"  {'date':12} {'close':>6} {'prev':>6} {'dLeg':>9}  posCount  capEng(+22950)        pv            dailyPnL")
patched = []
touched = 0
for s in snapshots:
    d = s.get('date', '')
    if d < ENTRY_DATE or d not in CLOSES:
        patched.append(s); continue
    close = CLOSES[d]
    base = ENTRY_PRICE if d == ENTRY_DATE else prior_trading_close(d)
    daily_leg = (close - base) * QTY
    s = dict(s)
    old_pv, old_cap, old_dp, old_pc = (s.get('portfolioValue', 0), s.get('capitalEngaged', 0),
                                       s.get('dailyPnL', 0), s.get('positionCount', 0))
    s['positionCount'] = old_pc + 1
    s['portfolioValue'] = round(old_pv + close * QTY, 2)
    s['capitalEngaged'] = round(old_cap + ENTRY_MV, 2)
    s['unrealizedPnL'] = round(s['portfolioValue'] - s['capitalEngaged'], 2)
    s['dailyPnL'] = round(old_dp + daily_leg, 2)
    cp = dict(s.get('closingPrices') or {}); cp[TICKER] = close; s['closingPrices'] = cp
    pac = list(s.get('positionsAtClose') or []); pac.append(make_leg(close)); s['positionsAtClose'] = pac
    patched.append(s); touched += 1
    print(f"  {d:12} {close:6.2f} {base:6.2f} {daily_leg:+9.0f}  {old_pc}->{s['positionCount']:<3}  "
          f"{old_cap:.1f}->{s['capitalEngaged']:.1f}  {old_pv:.0f}->{s['portfolioValue']:.0f}  "
          f"{old_dp:.0f}->{s['dailyPnL']:.0f}")

print(f"\nSnapshots touched: {touched}  |  capital engaged added: {ENTRY_MV:,.0f} HKD")

if not APPLY:
    print("\n[DRY-RUN] No write. Re-run with --apply to commit."); sys.exit(0)

ref.update({'positions': new_positions, 'priceCache': price_cache,
            'snapshots': patched, 'lastUpdated': firestore.SERVER_TIMESTAMP})
print("\n[APPLIED] Firestore updated.")

# ---- Verify ----
v = ref.get().to_dict()
vp = next((p for p in v['positions'] if p.get('ticker') == TICKER), None)
print(f"[VERIFY] position: {vp['ticker']} qty={vp['quantity']} entry={vp['entryPrice']} entryDate={vp['entryDate']}")
ok = True
for s in sorted(v['snapshots'], key=lambda x: x['date']):
    if s['date'] < ENTRY_DATE:
        continue
    pac = s.get('positionsAtClose') or []
    cap = round(sum(p.get('entryPrice', 0) * p.get('quantity', 0) for p in pac), 2)
    pv = round(sum(p.get('closingPrice', 0) * p.get('quantity', 0) for p in pac), 2)
    has = any(p.get('ticker') == TICKER for p in pac)
    cap_ok = abs(cap - s['capitalEngaged']) < 1
    pv_ok = abs(pv - s['portfolioValue']) < 1
    if not (has and cap_ok and pv_ok):
        ok = False
        print(f"[VERIFY][!] {s['date']}: has1167={has} capEng stored={s['capitalEngaged']} recomputed={cap} pv stored={s['portfolioValue']} recomputed={pv}")
print(f"[VERIFY] all patched snapshots self-consistent (capEng=Σentry*qty, pv=Σclose*qty): {ok}")
