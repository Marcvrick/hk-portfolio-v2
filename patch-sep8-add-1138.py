#!/usr/bin/env python3
"""
patch-sep8-add-1138.py

Retroactively add 1138.HK (COSCO SHIPPING Energy Transportation) — bought 6000 @ 17.55
on 2026-09-04, never recorded in the app (see wiki/reliability-risks.md #11-bis /
security-rules.md residual: a stale tab differing by exactly 1 position with no
matching closedTrades growth passes the rules unchanged — the add landed, then a
stale open tab's ~15s republish reverted positions 15->14 with no sale, which the
rules explicitly allow). Backfills every SETTLED snapshot from the entry date onward.

2026-09-08 is NOT patched here: market was still open (15:59 HKT) when this was
written, that day's snapshot is an unsettled pre-cron placeholder, and the day's
16:35 HKT cron will pick up 1138.HK correctly on its own via TradingView change_abs
once positions[] carries it. If this runs after today's cron has already settled,
STOP and patch 2026-09-08 the same way as the others below instead of relying on it.

Writes:
  - positions[]: append 1138.HK (qty 6000, entry 17.55, entryDate 2026-09-04)
  - priceCache["1138.HK"]: latest close 17.33 (09-07) / prevClose 17.49 (next cron overwrites)
  - snapshots 2026-09-04 and 2026-09-07 (the only two settled snapshots >= entry date):
      * positionsAtClose += 1138 leg (that date's raw close)
      * closingPrices["1138.HK"] = that date's close
      * positionCount += 1
      * portfolioValue  += close*qty
      * capitalEngaged  += 17.55*qty (constant 105,300)
      * unrealizedPnL    = portfolioValue - capitalEngaged   (recomputed)
      * dailyPnL        += (close - priorTradingDayClose)*qty
                          (entry day 2026-09-04 uses entryPrice 17.55 as baseline)

Raw (auto_adjust=False) Yahoo daily closes embedded below, verified 2026-09-08.
No HK holiday between 09-04 (Fri) and 09-07 (Mon) — clean weekend gap.

Dry-run by default. Pass --apply to write.
"""
import sys
from datetime import datetime, timezone, timedelta
import firebase_admin
from firebase_admin import credentials, firestore

CRED = 'hk-portfolio-v2/hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json'
DOC_ID = 'cNcZwUx3nQMV96TbB1kSkQ62u8U2'
TICKER = '1138.HK'
NAME = 'Cosco Shipping Energy'
QTY = 6000
ENTRY_PRICE = 17.55
ENTRY_DATE = '2026-09-04'
ENTRY_MV = ENTRY_PRICE * QTY            # 105,300
APPLY = '--apply' in sys.argv

# Yahoo daily closes (auto_adjust=False), verified 2026-09-08
CLOSES = {
    '2026-09-03': 17.55,  # prior trading day, baseline reference only (not patched)
    '2026-09-04': 17.49,
    '2026-09-07': 17.33,
}
SETTLED_DATES = ['2026-09-04', '2026-09-07']   # only settled snapshots get patched

def prior_trading_close(d):
    order = ['2026-09-03', '2026-09-04', '2026-09-07']
    i = order.index(d)
    return CLOSES[order[i - 1]]

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
    'id': int(datetime(2026, 9, 4, 9, 30, tzinfo=HKT).timestamp() * 1000),
    'ticker': TICKER, 'name': NAME, 'quantity': QTY,
    'entryPrice': ENTRY_PRICE, 'entryDate': ENTRY_DATE,
    'currentPrice': CLOSES['2026-09-07'],
}
new_positions = positions + [new_position]

# 2. priceCache
prev = prior_trading_close('2026-09-07')
latest = CLOSES['2026-09-07']
change = round(latest - prev, 4)
price_cache = dict(doc.get('priceCache', {}))
price_cache[TICKER] = {
    'success': True, 'price': latest, 'previousClose': prev,
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
print(f"\n=== Snapshots patched ({SETTLED_DATES}) ===")
print(f"  {'date':12} {'close':>6} {'base':>6} {'dLeg':>9}  posCount  capEng(+105300)        pv            dailyPnL")
patched = []
touched = 0
for s in snapshots:
    d = s.get('date', '')
    if d not in SETTLED_DATES:
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
if touched != len(SETTLED_DATES):
    print(f"[!] WARNING: expected {len(SETTLED_DATES)} snapshots, touched {touched}. Investigate before applying.")

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
    if s['date'] not in SETTLED_DATES:
        continue
    pac = s.get('positionsAtClose') or []
    cap = round(sum(p.get('entryPrice', 0) * p.get('quantity', 0) for p in pac), 2)
    pv = round(sum(p.get('closingPrice', 0) * p.get('quantity', 0) for p in pac), 2)
    has = any(p.get('ticker') == TICKER for p in pac)
    cap_ok = abs(cap - s['capitalEngaged']) < 1
    pv_ok = abs(pv - s['portfolioValue']) < 1
    if not (has and cap_ok and pv_ok):
        ok = False
        print(f"[VERIFY][!] {s['date']}: has1138={has} capEng stored={s['capitalEngaged']} recomputed={cap} pv stored={s['portfolioValue']} recomputed={pv}")
print(f"[VERIFY] all patched snapshots self-consistent (capEng=Σentry*qty, pv=Σclose*qty): {ok}")
