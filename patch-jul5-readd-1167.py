#!/usr/bin/env python3
"""
patch-jul5-readd-1167.py

RE-ADD 1167.HK (Jacobio Pharmaceuticals) — bought 5100 @ 4.5 on 2026-06-03.

Context: this was already backfilled once on 2026-06-25 (patch-jun3-add-1167.py,
snapshots Jun 3->25). Live diagnose on 2026-07-05 shows 1167 is GONE again — absent
from positions[] AND has1167=no in every snapshot Jun 3->Jul 3 — i.e. the whole Jun 25
backfill was reverted by a stale-tab full-document overwrite (the position was likely
dropped as a "shrink by exactly 1", which the Security Rules still permit, and the
snapshot legs reverted with it). This script re-applies the backfill and extends it
through the latest snapshot (Jul 3), superseding patch-jun3-add-1167.py (kept for history).

Writes (admin SDK — bypasses Security Rules):
  - positions[]: append 1167.HK (qty 5100, entry 4.5, entryDate 2026-06-03)
  - priceCache["1167.HK"]: latest close 5.20 / prevClose 4.94 (next cron overwrites with live)
  - every snapshot with date >= 2026-06-03 (add-to-stored, never full-rebuild):
      * positionsAtClose += 1167 leg (that date's close)
      * closingPrices["1167.HK"] = that date's close
      * positionCount += 1
      * portfolioValue  += close*qty
      * capitalEngaged  += 4.5*qty (constant 22,950)
      * unrealizedPnL    = portfolioValue - capitalEngaged   (recomputed)
      * dailyPnL        += (close - priorTradingDayClose)*qty
                          (entry day 2026-06-03 uses entryPrice 4.5 as the baseline)

Daily closes embedded from yfinance auto_adjust=False (raw settlement, verified 2026-07-05;
no dividends/splits in the window). priorTradingDayClose is the trading day immediately
before each snapshot date (gap-proof: Jun 4/5 have no snapshot, Jun 19 Tuen Ng + Jul 1 SAR
Day are holidays — the chain still uses the real prior trading day), per wiki
recording-a-sale Step 4 / dailypnl-formula.

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

# Yahoo daily closes (auto_adjust=False), verified 2026-07-05. No corporate actions in window.
CLOSES = {
    '2026-06-02': 4.5,  '2026-06-03': 4.3,  '2026-06-04': 4.12, '2026-06-05': 4.14,
    '2026-06-08': 4.32, '2026-06-09': 4.33, '2026-06-10': 4.45, '2026-06-11': 4.81,
    '2026-06-12': 4.65, '2026-06-15': 4.49, '2026-06-16': 4.43, '2026-06-17': 4.53,
    '2026-06-18': 4.41, '2026-06-22': 4.44, '2026-06-23': 4.59, '2026-06-24': 4.29,
    '2026-06-25': 4.40, '2026-06-26': 4.27, '2026-06-29': 4.65, '2026-06-30': 4.78,
    '2026-07-02': 4.94, '2026-07-03': 5.20,
}
CLOSE_DATES = sorted(CLOSES)
LATEST = '2026-07-03'

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
prev = prior_trading_close(LATEST)      # Jul 2 close = 4.94
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
print(f"=== Position ===\n  add {TICKER} ({NAME}) qty={QTY} entry={ENTRY_PRICE} entryDate={ENTRY_DATE}  currentPrice={CLOSES[LATEST]}")
print(f"  positions {len(positions)} -> {len(new_positions)}")
print(f"\n=== Snapshots patched (>= {ENTRY_DATE}) ===")
print(f"  {'date':12} {'close':>6} {'prev':>6} {'dLeg':>9}  posCount  capEng(+22950)          pv               dailyPnL")
patched = []
touched = 0
missing_close = []
for s in snapshots:
    d = s.get('date', '')
    if d < ENTRY_DATE:
        patched.append(s); continue
    if d not in CLOSES:
        missing_close.append(d); patched.append(s); continue
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
if missing_close:
    print(f"[!] snapshots >= {ENTRY_DATE} with NO embedded close (NOT patched): {missing_close}")
print(f"Current unrealized on 1167 @ {CLOSES[LATEST]}: {(CLOSES[LATEST]-ENTRY_PRICE)*QTY:+,.0f} HKD "
      f"({(CLOSES[LATEST]-ENTRY_PRICE)/ENTRY_PRICE*100:+.1f}%)")

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
    if s['date'] < ENTRY_DATE or s['date'] not in CLOSES:
        continue
    pac = s.get('positionsAtClose') or []
    cap = round(sum(p.get('entryPrice', 0) * p.get('quantity', 0) for p in pac), 2)
    pv = round(sum(p.get('closingPrice', 0) * p.get('quantity', 0) for p in pac), 2)
    has = any(p.get('ticker') == TICKER for p in pac)
    cap_ok = abs(cap - s['capitalEngaged']) < 1
    pv_ok = abs(pv - s['portfolioValue']) < 1
    unreal_ok = abs(round(s['portfolioValue'] - s['capitalEngaged'], 2) - s['unrealizedPnL']) < 1
    pc_ok = s['positionCount'] == len(pac)
    if not (has and cap_ok and pv_ok and unreal_ok and pc_ok):
        ok = False
        print(f"[VERIFY][!] {s['date']}: has1167={has} capEng {s['capitalEngaged']}/{cap} pv {s['portfolioValue']}/{pv} pc {s['positionCount']}/{len(pac)}")
print(f"[VERIFY] all patched snapshots self-consistent (pv=Sigma close*qty, cap=Sigma entry*qty, unreal=pv-cap, pc=len): {ok}")
