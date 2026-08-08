#!/usr/bin/env python3
"""
patch-aug8-backfill-2600.py

2600.HK (Chalco) was bought 2026-07-23 (12,000 sh @ 8.40) but is absent from every
snapshot until 2026-08-07 — no closedTrade, no transaction, simply never recorded.
See wiki/snapshot-record-gaps.md. This backfills the leg into the 11 snapshots
2026-07-23 .. 2026-08-06.

Per wiki/recording-a-sale.md:
  - dailyPnL      : ADD the leg to the stored value (immutability rule — never
                    rebuild dailyPnL from closingPrices).
                    leg = (close_d - close_prevTradingDay) x qty
                    entry day: leg = (close_d - entryPrice) x qty  (the cron's own
                    rule, update.py: `if p["entryDate"] == today`)
  - pv/cap/unrealized/posCount : RECOMPUTE from the post-insert positionsAtClose,
                    never per-field delta subtraction (incidents 2026-06-10).
  - realizedPnL   : untouched (no sale involved).
  - Raw closes only (auto_adjust=False).

Dry-run by default. Writes only with --apply.
"""
import sys
import firebase_admin
from firebase_admin import credentials, firestore
import yfinance as yf

APPLY = '--apply' in sys.argv

CRED = 'hk-portfolio-v2/hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json'
DOC_ID = 'cNcZwUx3nQMV96TbB1kSkQ62u8U2'
TICKER, NAME = '2600.HK', 'Chalco'
QTY, ENTRY, ENTRY_DATE = 12000, 8.40, '2026-07-23'
LAST = '2026-08-06'          # 08-07 already correct — do not touch

cred = credentials.Certificate(CRED)
firebase_admin.initialize_app(cred)
db = firestore.client()
ref = db.collection('portfolios').document(DOC_ID)
doc = ref.get().to_dict()

# ---------------------------------------------------------------- idempotency
pos = [p for p in doc.get('positions', []) if p['ticker'].replace('b.HK', '.HK') == TICKER]
if not pos:
    sys.exit(f"ABORT: {TICKER} not in positions[] — refusing to backfill a position that isn't held.")
p0 = pos[0]
if p0.get('quantity') != QTY or abs(p0.get('entryPrice', 0) - ENTRY) > 1e-9 or p0.get('entryDate') != ENTRY_DATE:
    sys.exit(f"ABORT: live position disagrees with this script's constants: {p0}")
if any(TICKER in (t.get('ticker') or '') for t in doc.get('closedTrades', [])):
    sys.exit(f"ABORT: a closedTrade exists for {TICKER} — the gap may be a sale, not a record loss.")

snaps = sorted(doc.get('snapshots', []), key=lambda s: s['date'])
targets = [s for s in snaps if ENTRY_DATE <= s['date'] <= LAST]
already = [s['date'] for s in targets if TICKER in (s.get('closingPrices') or {})]
if already:
    sys.exit(f"ABORT (idempotency): {TICKER} already present in snapshots {already}.")

# ------------------------------------------------------------------ raw closes
hist = yf.Ticker(TICKER).history(start='2026-07-21', end='2026-08-08', auto_adjust=False)
closes = {str(d.date()): round(float(r['Close']), 4) for d, r in hist.iterrows()}
sess = sorted(closes)                       # true consecutive trading days
print(f"raw closes (auto_adjust=False): {len(sess)} sessions {sess[0]} .. {sess[-1]}\n")

missing = [s['date'] for s in targets if s['date'] not in closes]
if missing:
    sys.exit(f"ABORT: no Yahoo close for snapshot date(s) {missing}.")

# ------------------------------------------------------------------ compute
print(f"{'date':<12}{'close':>8}{'prevClose':>11}{'leg':>10}"
      f"{'dailyPnL':>22}{'posCount':>12}{'pv drift':>10}")
print('-' * 85)
plan, tot_leg = [], 0.0
for s in targets:
    d = s['date']
    c = closes[d]
    i = sess.index(d)
    if d == ENTRY_DATE:
        base, base_lbl = ENTRY, f'entry {ENTRY}'
    else:
        base, base_lbl = closes[sess[i - 1]], f'{closes[sess[i-1]]:.3f}'
    leg = (c - base) * QTY
    tot_leg += leg

    pac = list(s.get('positionsAtClose') or [])
    if not pac:
        sys.exit(f"ABORT: snapshot {d} has no positionsAtClose — cannot recompute safely.")
    # invariant drift BEFORE the patch (recompute repairs it; surface it, never hide it)
    pv_from_pac = sum(q.get('closingPrice', 0) * q.get('quantity', 0) for q in pac)
    drift = pv_from_pac - s.get('portfolioValue', 0)

    entry = {'ticker': TICKER, 'name': NAME, 'quantity': QTY, 'entryPrice': ENTRY,
             'entryDate': ENTRY_DATE, 'closingPrice': c, 'marketValue': c * QTY,
             'pnl': (c - ENTRY) * QTY,
             'pnlPercent': (c - ENTRY) / ENTRY * 100}
    new_pac = pac + [entry]
    new_pv = sum(q.get('closingPrice', 0) * q.get('quantity', 0) for q in new_pac)
    new_cap = sum(q.get('entryPrice', 0) * q.get('quantity', 0) for q in new_pac)
    new_daily = s.get('dailyPnL', 0) + leg

    plan.append({'date': d, 'close': c, 'leg': leg, 'pac': new_pac, 'pv': new_pv,
                 'cap': new_cap, 'unreal': new_pv - new_cap, 'daily': new_daily,
                 'old_daily': s.get('dailyPnL', 0), 'count': len(new_pac),
                 'old_count': s.get('positionCount'), 'old_pv': s.get('portfolioValue', 0)})
    flip = ' FLIP' if (s.get('dailyPnL', 0) >= 0) != (new_daily >= 0) else ''
    print(f"{d:<12}{c:>8.3f}{base_lbl:>11}{leg:>10,.0f}"
          f"{s.get('dailyPnL',0):>11,.0f} ->{new_daily:>8,.0f}{flip:<5}"
          f"{str(s.get('positionCount')):>5} ->{len(new_pac):>4}{drift:>10,.2f}")

print('-' * 85)
print(f"{len(plan)} snapshots to patch. Sum of legs = {tot_leg:,.2f} HKD "
      f"(net effect on the cumulative curve).")
print(f"capitalEngaged rises by {ENTRY*QTY:,.0f} on every patched day; "
      f"portfolioValue by close x {QTY:,}.")
print(f"realizedPnL: UNCHANGED (no sale). 2026-08-07 and later: UNTOUCHED.\n")

if not APPLY:
    print("[DRY-RUN] No write performed. Re-run with --apply to write.")
    sys.exit(0)

# ------------------------------------------------------------------ apply
by_date = {p['date']: p for p in plan}
new_snaps = []
for s in snaps:
    if s['date'] in by_date:
        p = by_date[s['date']]
        s = dict(s)
        s['positionsAtClose'] = p['pac']
        s['portfolioValue'] = p['pv']
        s['capitalEngaged'] = p['cap']
        s['unrealizedPnL'] = p['unreal']
        s['dailyPnL'] = p['daily']
        s['positionCount'] = p['count']
        cp = dict(s.get('closingPrices') or {})
        cp[TICKER] = p['close']
        s['closingPrices'] = cp
        prov = dict(s.get('priceProvenance') or {})
        prov[TICKER] = {'source': 'yahoo-backfill', 'chosen': p['close'],
                        'yahooClose': p['close'], 'tvClose': None, 'drift': None,
                        'provisional': False, 'backfilledOn': '2026-08-08',
                        'note': 'record gap repaired — see wiki/snapshot-record-gaps.md'}
        s['priceProvenance'] = prov
    new_snaps.append(s)

ref.update({'snapshots': new_snaps})
print("[APPLIED] snapshots[] updated.\n")

# ------------------------------------------------------------------ verify
fresh = {s['date']: s for s in ref.get().to_dict().get('snapshots', [])}
ok = True
print("[VERIFY]")
for p in plan:
    s = fresh[p['date']]
    pac = s.get('positionsAtClose') or []
    cp = s.get('closingPrices') or {}
    pv = sum(q.get('closingPrice', 0) * q.get('quantity', 0) for q in pac)
    cap = sum(q.get('entryPrice', 0) * q.get('quantity', 0) for q in pac)
    checks = {
        'has 2600 in pac': any(q.get('ticker') == TICKER for q in pac),
        'has 2600 in closingPrices': cp.get(TICKER) == p['close'],
        'dailyPnL': abs(s.get('dailyPnL', 0) - p['daily']) < 0.01,
        'pv = S(close x qty)': abs(s.get('portfolioValue', 0) - pv) < 0.01,
        'cap = S(entry x qty)': abs(s.get('capitalEngaged', 0) - cap) < 0.01,
        'unreal = pv - cap': abs(s.get('unrealizedPnL', 0) - (pv - cap)) < 0.01,
        'posCount = len(pac)': s.get('positionCount') == len(pac),
        'cp keys = pac tickers': set(cp) == {q.get('ticker') for q in pac},
    }
    bad = [k for k, v in checks.items() if not v]
    ok &= not bad
    print(f"  {p['date']}  {'OK' if not bad else 'FAIL -> ' + ', '.join(bad)}")
print("\n[VERIFY] all invariants hold." if ok else "\n[VERIFY] FAILURES ABOVE.")
sys.exit(0 if ok else 1)
