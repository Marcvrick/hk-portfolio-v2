#!/usr/bin/env python3
"""
patch-aug10-fix-appel-ticker.py

positions[] holds the Apple position under ticker "APPEL" (typo for "AAPL"),
entered 2026-07-21, 20 sh @ 315.00. "APPEL" does not resolve on TradingView or
Yahoo, so every cron run since entry hit the "MISS"/"missing" path (update-us.py
L351-353, L216-219) and never updated it: positions[].currentPrice — and every
snapshot's closingPrices["APPEL"] / positionsAtClose entry — has been frozen at
327.96 across all 14 affected snapshots (2026-07-21 .. 2026-08-07). Because the
price never changed day-to-day, the (buggy) dailyPnL leg for this ticker was
exactly 0 on every day after entry, silently excluding AAPL's real moves from
the portfolio's daily P&L for 13 sessions. See wiki/incidents.md 2026-08-10.

Real close (2026-08-07) = 313.33 vs the frozen 327.96 — the position currently
shows +259.20 (+4.11%) when it should show roughly -33.40 (-1.06%): a sign flip.

Entry day (2026-07-21) is left untouched: 327.96 was plausibly the actual
browser-side fetch/fill at creation time (a real, small ~0.22 vs. Yahoo's raw
327.74 — ordinary source drift), and there's no transaction record to confirm
otherwise. Only 07-22 .. 08-07 (13 sessions, where the price provably never
moved) are backfilled with real Yahoo raw closes.

Per wiki/recording-a-sale.md:
  - dailyPnL      : ADD the leg to the stored value (immutability rule).
                    leg = (close_d - close_prevRecordedDay) x qty
                    First target day (07-22) bases off the STORED 07-21 close
                    (327.96, left as-is) so the record stays internally
                    consistent; every day after chains off the prior day's
                    freshly-corrected close.
  - pv/cap/unrealized/posCount : RECOMPUTE from the post-rename positionsAtClose,
                    never per-field delta subtraction (incidents 2026-06-10).
  - realizedPnL   : untouched (no sale involved).
  - capitalEngaged: numerically unchanged (same entryPrice x qty) — recomputed
                    anyway per convention, should be a no-op check.
  - Raw closes only (auto_adjust=False).

Dry-run by default. Writes only with --apply.
"""
import sys
import firebase_admin
from firebase_admin import credentials, firestore
import yfinance as yf

APPLY = '--apply' in sys.argv

CRED = 'hk-portfolio-v2/hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json'
DOC_ID = 'JJDY5whY9vNmCcRsi8kafMHZbmD2'
OLD_TICKER, NEW_TICKER, NAME = 'APPEL', 'AAPL', 'Apple'
QTY, ENTRY, ENTRY_DATE = 20, 315.0, '2026-07-21'
ENTRY_STORED_CLOSE = 327.96   # left untouched — see docstring
LAST = '2026-08-07'           # most recent snapshot as of this patch

cred = credentials.Certificate(CRED)
firebase_admin.initialize_app(cred)
db = firestore.client()
ref = db.collection('us-portfolios').document(DOC_ID)
doc = ref.get().to_dict()

# ---------------------------------------------------------------- idempotency
pos = [p for p in doc.get('positions', []) if p['ticker'].upper() == OLD_TICKER]
if not pos:
    sys.exit(f"ABORT: {OLD_TICKER} not in positions[] — already renamed, or nothing to fix.")
p0 = pos[0]
if p0.get('quantity') != QTY or abs(p0.get('entryPrice', 0) - ENTRY) > 1e-9 or p0.get('entryDate') != ENTRY_DATE:
    sys.exit(f"ABORT: live position disagrees with this script's constants: {p0}")
if any(p['ticker'].upper() == NEW_TICKER for p in doc.get('positions', [])):
    sys.exit(f"ABORT: {NEW_TICKER} already exists in positions[] — would collide.")
if any(t.get('ticker', '').upper() in (OLD_TICKER, NEW_TICKER) for t in doc.get('closedTrades', [])):
    sys.exit("ABORT: a closedTrade exists for APPEL/AAPL — this isn't a plain rename anymore, stop and diagnose.")

snaps = sorted(doc.get('snapshots', []), key=lambda s: s['date'])
targets = [s for s in snaps if ENTRY_DATE < s['date'] <= LAST]  # entry day excluded, untouched
entry_snap = next((s for s in snaps if s['date'] == ENTRY_DATE), None)
if not entry_snap or OLD_TICKER not in (entry_snap.get('closingPrices') or {}):
    sys.exit(f"ABORT: entry-day snapshot {ENTRY_DATE} missing or doesn't hold {OLD_TICKER}.")
if abs(entry_snap['closingPrices'][OLD_TICKER] - ENTRY_STORED_CLOSE) > 1e-6:
    sys.exit(f"ABORT: entry-day stored close {entry_snap['closingPrices'][OLD_TICKER]} != expected {ENTRY_STORED_CLOSE}.")
already_renamed = [s['date'] for s in targets if NEW_TICKER in (s.get('closingPrices') or {})]
if already_renamed:
    sys.exit(f"ABORT (idempotency): {NEW_TICKER} already present in snapshots {already_renamed}.")
not_frozen = [s['date'] for s in targets
              if (s.get('closingPrices') or {}).get(OLD_TICKER) not in (None, ENTRY_STORED_CLOSE)]
if not_frozen:
    sys.exit(f"ABORT: {OLD_TICKER} close isn't frozen at {ENTRY_STORED_CLOSE} on {not_frozen} — re-diagnose before patching.")

# ------------------------------------------------------------------ raw closes
hist = yf.Ticker(NEW_TICKER).history(start='2026-07-19', end='2026-08-08', auto_adjust=False)
closes = {str(d.date()): round(float(r['Close']), 4) for d, r in hist.iterrows()}
sess = sorted(closes)
print(f"raw AAPL closes (auto_adjust=False): {len(sess)} sessions {sess[0]} .. {sess[-1]}\n")

missing = [s['date'] for s in targets if s['date'] not in closes]
if missing:
    sys.exit(f"ABORT: no Yahoo close for snapshot date(s) {missing}.")

# ------------------------------------------------------------------ compute
print(f"{'date':<12}{'close':>8}{'prevClose':>11}{'leg':>10}"
      f"{'dailyPnL':>22}{'posCount':>12}{'pv drift':>10}")
print('-' * 85)
plan, tot_leg = [], 0.0
prev_close = ENTRY_STORED_CLOSE  # chains: 07-22 bases off the untouched 07-21 stored close
for s in targets:
    d = s['date']
    c = closes[d]
    base = prev_close
    leg = (c - base) * QTY
    tot_leg += leg
    prev_close = c  # next iteration chains off this (now-corrected) close

    pac = list(s.get('positionsAtClose') or [])
    if not pac:
        sys.exit(f"ABORT: snapshot {d} has no positionsAtClose — cannot recompute safely.")
    pv_from_pac = sum(q.get('closingPrice', 0) * q.get('quantity', 0) for q in pac)
    drift = pv_from_pac - s.get('portfolioValue', 0)

    new_entry = {'ticker': NEW_TICKER, 'name': NAME, 'quantity': QTY, 'entryPrice': ENTRY,
                 'entryDate': ENTRY_DATE, 'closingPrice': c, 'marketValue': c * QTY,
                 'pnl': (c - ENTRY) * QTY,
                 'pnlPercent': (c - ENTRY) / ENTRY * 100}
    new_pac = [q for q in pac if q.get('ticker', '').upper() != OLD_TICKER] + [new_entry]
    new_pv = sum(q.get('closingPrice', 0) * q.get('quantity', 0) for q in new_pac)
    new_cap = sum(q.get('entryPrice', 0) * q.get('quantity', 0) for q in new_pac)
    new_daily = s.get('dailyPnL', 0) + leg

    plan.append({'date': d, 'close': c, 'leg': leg, 'pac': new_pac, 'pv': new_pv,
                 'cap': new_cap, 'unreal': new_pv - new_cap, 'daily': new_daily,
                 'old_daily': s.get('dailyPnL', 0), 'count': len(new_pac),
                 'old_count': s.get('positionCount'), 'old_pv': s.get('portfolioValue', 0)})
    flip = ' FLIP' if (s.get('dailyPnL', 0) >= 0) != (new_daily >= 0) else ''
    print(f"{d:<12}{c:>8.2f}{base:>11.2f}{leg:>10,.2f}"
          f"{s.get('dailyPnL',0):>11,.0f} ->{new_daily:>8,.0f}{flip:<5}"
          f"{str(s.get('positionCount')):>5} ->{len(new_pac):>4}{drift:>10,.2f}")

print('-' * 85)
print(f"{len(plan)} snapshots to patch ({targets[0]['date']} .. {targets[-1]['date']}). "
      f"Entry day {ENTRY_DATE} untouched (close stays {ENTRY_STORED_CLOSE}).")
print(f"Sum of legs = {tot_leg:,.2f} USD added to the cumulative dailyPnL series "
      f"(this is the P&L that was silently excluded for 13 sessions).")
print(f"Final (08-07) position value: {plan[-1]['close']*QTY:,.2f} vs frozen "
      f"{ENTRY_STORED_CLOSE*QTY:,.2f} -> unrealizedPnL for this leg goes from "
      f"{(ENTRY_STORED_CLOSE-ENTRY)*QTY:+,.2f} to {(plan[-1]['close']-ENTRY)*QTY:+,.2f}.")
print("capitalEngaged: numerically unchanged (same entryPrice x qty), recomputed anyway.")
print("realizedPnL: UNCHANGED (no sale). positions[].currentPrice will be updated to the "
      f"08-07 close ({plan[-1]['close']}) so the browser stops showing the frozen price.\n")

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
        cp = {k: v for k, v in (s.get('closingPrices') or {}).items() if k.upper() != OLD_TICKER}
        cp[NEW_TICKER] = p['close']
        s['closingPrices'] = cp
        prov = {k: v for k, v in (s.get('priceProvenance') or {}).items() if k.upper() != OLD_TICKER}
        prov[NEW_TICKER] = {'source': 'yahoo-backfill', 'chosen': p['close'],
                             'yahooClose': p['close'], 'tvClose': None, 'drift': None,
                             'provisional': False, 'backfilledOn': '2026-08-10',
                             'note': 'ticker typo (APPEL->AAPL) repaired — see wiki/incidents.md 2026-08-10'}
        s['priceProvenance'] = prov
        s['provisional'] = any(v.get('provisional') for v in prov.values())
    new_snaps.append(s)

new_positions = []
for p in doc.get('positions', []):
    if p['ticker'].upper() == OLD_TICKER:
        p = dict(p)
        p['ticker'] = NEW_TICKER
        p['currentPrice'] = plan[-1]['close']
    new_positions.append(p)

ref.update({'snapshots': new_snaps, 'positions': new_positions})
print("[APPLIED] snapshots[] + positions[] updated.\n")

# ------------------------------------------------------------------ verify
fresh = ref.get().to_dict()
fresh_snaps = {s['date']: s for s in fresh.get('snapshots', [])}
fresh_pos = [p for p in fresh.get('positions', []) if p['ticker'].upper() == NEW_TICKER]
ok = bool(fresh_pos) and not any(p['ticker'].upper() == OLD_TICKER for p in fresh.get('positions', []))
print("[VERIFY]")
print(f"  positions[] renamed: {'OK' if ok else 'FAIL'} (currentPrice={fresh_pos[0].get('currentPrice') if fresh_pos else None})")
for p in plan:
    s = fresh_snaps[p['date']]
    pac = s.get('positionsAtClose') or []
    cp = s.get('closingPrices') or {}
    pv = sum(q.get('closingPrice', 0) * q.get('quantity', 0) for q in pac)
    cap = sum(q.get('entryPrice', 0) * q.get('quantity', 0) for q in pac)
    checks = {
        'has AAPL in pac, no APPEL': (any(q.get('ticker') == NEW_TICKER for q in pac)
                                       and not any(q.get('ticker') == OLD_TICKER for q in pac)),
        'closingPrices has AAPL, no APPEL': (cp.get(NEW_TICKER) == p['close'] and OLD_TICKER not in cp),
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
