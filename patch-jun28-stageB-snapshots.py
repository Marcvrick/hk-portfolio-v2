#!/usr/bin/env python3
"""
patch-jun28-stageB-snapshots.py

Stage B: rebuild the Jun 22-26 daily snapshots so the calendar/performance tiles
include WuXi (2359) + Xiaomi (1810), wiped by the stale-tab overwrite, and the
corrected 6821 lot (500 @ 111.7, was 200 @ 110.7).

Method = wiki [[recording-a-sale]] Step 4 (invariant-safe ADD-to-stored, never a
full rebuild): keep the cron's values for the untouched tickers; add only the
missing legs' contributions. dailyPnL gets ONLY the added legs' session moves.
pv/capEngaged/unrealized/positionCount are adjusted by the added/corrected legs.

Raw (unadjusted) closes from yfinance:
  2359: 22=132.8 23=130.8 24=141.7 25=145.0 26=145.4   (no div, raw==adj)
  1810: 24=22.96 25=22.30 26=21.42                       (no div, raw==adj)
  6821: 25=108.5 26=111.3 (raw; stored Jun26 close 111.3 matches)

WuXi: bought 800 @128.7 on 22 (entry basis used on buy day), sold 500 @148.2 on 25
(intraday), 300 held after. Xiaomi: bought 2400 @22.9 on 24.

Dry-run by default. --apply to write. Idempotent (aborts if 2359 already in a leg).
"""
import sys
import firebase_admin
from firebase_admin import credentials, firestore

CRED = 'hk-portfolio-v2/hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json'
DOC_ID = 'cNcZwUx3nQMV96TbB1kSkQ62u8U2'
APPLY = '--apply' in sys.argv

# add = (ticker, name, qty, entry, entryDate, closeToday)
# daily_legs = list of (label, contribution) summed into dailyPnL
SPEC = {
  '2026-06-22': {
    'add': [('2359.HK', 'WuXi AppTec', 800, 128.7, '2026-06-22', 132.8)],
    'daily': [('2359 buy 800 (132.8-128.7)', (132.8 - 128.7) * 800)],
  },
  '2026-06-23': {
    'add': [('2359.HK', 'WuXi AppTec', 800, 128.7, '2026-06-22', 130.8)],
    'daily': [('2359 held 800 (130.8-132.8)', (130.8 - 132.8) * 800)],
  },
  '2026-06-24': {
    'add': [('2359.HK', 'WuXi AppTec', 800, 128.7, '2026-06-22', 141.7),
            ('1810.HK', 'Xiaomi', 2400, 22.9, '2026-06-24', 22.96)],
    'daily': [('2359 held 800 (141.7-130.8)', (141.7 - 130.8) * 800),
              ('1810 buy 2400 (22.96-22.9)', (22.96 - 22.9) * 2400)],
  },
  '2026-06-25': {
    'add': [('2359.HK', 'WuXi AppTec', 300, 128.7, '2026-06-22', 145.0),
            ('1810.HK', 'Xiaomi', 2400, 22.9, '2026-06-24', 22.30)],
    'daily': [('2359 sold 500 (148.2-141.7)', (148.2 - 141.7) * 500),
              ('2359 held 300 (145.0-141.7)', (145.0 - 141.7) * 300),
              ('1810 held 2400 (22.30-22.96)', (22.30 - 22.96) * 2400)],
  },
  '2026-06-26': {
    'add': [('2359.HK', 'WuXi AppTec', 300, 128.7, '2026-06-22', 145.4),
            ('1810.HK', 'Xiaomi', 2400, 22.9, '2026-06-24', 21.42)],
    'fix6821': (500, 111.7, 111.3),   # newQty, newEntry, close (was 200 @ 110.7)
    'daily': [('2359 held 300 (145.4-145.0)', (145.4 - 145.0) * 300),
              ('1810 held 2400 (21.42-22.30)', (21.42 - 22.30) * 2400),
              ('6821 fix: true buyday (111.3-111.7)*500 minus cron (111.3-108.5)*200',
               (111.3 - 111.7) * 500 - (111.3 - 108.5) * 200)],
  },
}

firebase_admin.initialize_app(credentials.Certificate(CRED))
db = firestore.client()
ref = db.collection('portfolios').document(DOC_ID)
doc = ref.get().to_dict()
snaps = {s['date']: s for s in doc['snapshots']}

# idempotency: if any target snapshot already has a 2359 leg, abort
for d in SPEC:
    s = snaps.get(d)
    if s and any(x.get('ticker') == '2359.HK' for x in (s.get('positionsAtClose') or [])):
        print(f"ABORT: {d} already has a 2359 leg — Stage B already applied?"); sys.exit(1)

def leg(ticker, name, qty, entry, entryDate, close):
    return {'ticker': ticker, 'name': name, 'quantity': qty, 'entryPrice': entry,
            'entryDate': entryDate, 'closingPrice': close,
            'marketValue': round(close * qty, 2), 'pnl': round((close - entry) * qty, 4),
            'pnlPercent': (close - entry) / entry * 100}

for d, spec in SPEC.items():
    s = snaps.get(d)
    if not s:
        print(f"WARN: snapshot {d} missing — skipped"); continue
    pac = s.get('positionsAtClose') or []
    cp = s.get('closingPrices') or {}
    pv0, cap0, pc0, dp0 = s['portfolioValue'], s['capitalEngaged'], s['positionCount'], s['dailyPnL']

    add_mv = add_cap = 0
    for (tk, nm, qty, entry, ed, close) in spec['add']:
        L = leg(tk, nm, qty, entry, ed, close)
        pac.append(L); cp[tk] = close
        add_mv += L['marketValue']; add_cap += round(entry * qty, 2)
    n_added = len(spec['add'])

    six_mv_d = six_cap_d = 0
    if spec.get('fix6821'):
        nq, ne, cl = spec['fix6821']
        six = next((x for x in pac if x.get('ticker') == '6821.HK'), None)
        if six:
            old_mv = (six.get('closingPrice') or cl) * six.get('quantity', 0)
            old_cap = six.get('entryPrice', 0) * six.get('quantity', 0)
            six['quantity'] = nq; six['entryPrice'] = ne
            six['closingPrice'] = cl
            six['marketValue'] = round(cl * nq, 2)
            six['pnl'] = round((cl - ne) * nq, 4); six['pnlPercent'] = (cl - ne) / ne * 100
            six_mv_d = round(cl * nq - old_mv, 2); six_cap_d = round(ne * nq - old_cap, 2)
            cp['6821.HK'] = cl

    daily_delta = round(sum(c for _, c in spec['daily']), 2)
    pv1 = round(pv0 + add_mv + six_mv_d, 2)
    cap1 = round(cap0 + add_cap + six_cap_d, 2)
    unr1 = round(pv1 - cap1, 2)
    pc1 = pc0 + n_added
    dp1 = round(dp0 + daily_delta, 2)

    s['portfolioValue'] = pv1; s['capitalEngaged'] = cap1
    s['unrealizedPnL'] = unr1; s['positionCount'] = pc1
    s['dailyPnL'] = dp1; s['closingPrices'] = cp; s['positionsAtClose'] = pac

    print(f"\n=== {d} ===")
    for lbl, c in spec['daily']:
        print(f"    dailyPnL leg: {lbl} = {round(c,2):+,.0f}")
    print(f"  dailyPnL  {dp0:+,.0f} -> {dp1:+,.0f}  (delta {daily_delta:+,.0f})")
    print(f"  posCount  {pc0} -> {pc1}   pv {pv0:,.0f} -> {pv1:,.0f}   "
          f"cap {cap0:,.0f} -> {cap1:,.0f}   unrealizedPnL -> {unr1:,.0f}")

if not APPLY:
    print("\n[DRY-RUN] No write. Re-run with --apply.")
    sys.exit(0)

ref.update({'snapshots': list(snaps.values())})
print("\n[APPLIED] Stage B snapshots updated.")
v = {s['date']: s for s in ref.get().to_dict()['snapshots']}
for d in SPEC:
    s = v[d]
    has = sorted(x['ticker'] for x in s['positionsAtClose'] if x['ticker'] in ('2359.HK', '1810.HK', '6821.HK'))
    print(f"[VERIFY] {d}: dailyPnL={s['dailyPnL']:+,.0f} posCount={s['positionCount']} legs={has}")
