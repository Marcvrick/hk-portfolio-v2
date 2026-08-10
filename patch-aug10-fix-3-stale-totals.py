#!/usr/bin/env python3
"""
patch-aug10-fix-3-stale-totals.py

The three HK snapshots whose stored totals disagree with their own `positionsAtClose`,
open since the 2026-08-08 Check-6 sweep (wiki/snapshot-record-gaps.md "Still open").

Diagnosis — in all three, `positionsAtClose` is CORRECT and the top-level totals were
never updated. Each is the delta-subtraction signature (wiki/incidents.md 2026-06-10),
not the 2600 family:

  2026-03-31  1167.HK bought that day, 14,100 @ 7.25 = 102,225.00, which is EXACTLY the
              capitalEngaged shortfall. unrealizedPnL is short by its 4,794 leg too.
              portfolioValue and positionCount already correct.

  2026-04-13  Three changes that day, none of which reached the totals: 113.HK bought
              (20,000 @ 6.10 = 122,000), 3680.HK bought (24,000 @ 2.20 = 52,800), and
              1913.HK topped up (1,000 @ 50.30 -> 2,300 @ 43.597, cost +49,973.10).
              808,801 + 122,000 + 52,800 + 49,973.10 = 1,033,574.10, the pac figure to
              the cent. The stored capitalEngaged is verbatim the 2026-04-10 value —
              never touched. portfolioValue is short by 1913's added 1,300 shares
              (49,088). The 04-14 snapshot is clean, so the cron recovered by itself.

  2026-05-15  1999.HK, 2013.HK and 2382.HK were SOLD that day (closedTrades confirm),
              cost basis 99,200 + 50,490 + 100,425 = 250,115.00, EXACTLY the
              capitalEngaged excess. So the 13-entry pac is right; capitalEngaged still
              carries the three, positionCount still says 16, and closingPrices still
              holds their three keys. portfolioValue and unrealizedPnL already correct.
              NOTE: wiki/snapshot-record-gaps.md called this "the same family as 2600"
              (positions dropped from the record). That reading is wrong — they were
              sold, the record is right, the totals are stale. Corrected in the wiki.

The fix is therefore one rule for all three, the one wiki/recording-a-sale.md already
mandates: RECOMPUTE portfolioValue / capitalEngaged / unrealizedPnL / positionCount from
`positionsAtClose`, never delta-subtract. Plus drop the three orphan `closingPrices` keys
on 05-15.

NOT touched: `positionsAtClose` itself (asserted byte-identical), `dailyPnL` (immutability
rule — it came from the cron's tv_change_abs and does not depend on these totals),
`realizedPnL`, and every other snapshot.

Dry-run by default. Writes only with --apply.
"""
import sys
import firebase_admin
from firebase_admin import credentials, firestore

APPLY = '--apply' in sys.argv

CRED = 'hk-portfolio-v2/hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json'
DOC_ID = 'cNcZwUx3nQMV96TbB1kSkQ62u8U2'
TARGETS = ['2026-03-31', '2026-04-13', '2026-05-15']

firebase_admin.initialize_app(credentials.Certificate(CRED))
db = firestore.client()
ref = db.collection('portfolios').document(DOC_ID)
doc = ref.get().to_dict()
snaps = sorted(doc.get('snapshots', []), key=lambda s: s['date'])
closed = doc.get('closedTrades') or []
by_date = {s['date']: s for s in snaps}

plan = []
for d in TARGETS:
    if d not in by_date:
        sys.exit(f"ABORT: no snapshot for {d}.")
    s = by_date[d]
    pac = s.get('positionsAtClose') or []
    if not pac:
        sys.exit(f"ABORT: {d} has no positionsAtClose — nothing to recompute from.")

    # --- the guard that matters: never recompute totals around an INCOMPLETE array.
    # Every ticker held on the prior snapshot and not sold in the interval must still be
    # here. This is the 2600 check (wiki/snapshot-record-gaps.md): a missing holding
    # leaves a snapshot internally consistent and wrong, and recomputing would bake the
    # omission into the totals as if it were correct.
    i = next(i for i, x in enumerate(snaps) if x['date'] == d)
    prev = snaps[i - 1]
    prev_t = {p['ticker'] for p in (prev.get('positionsAtClose') or [])}
    sold = {c['ticker'] for c in closed if prev['date'] < c.get('exitDate', '') <= d}
    here = {p['ticker'] for p in pac}
    missing = (prev_t - sold) - here
    if missing:
        sys.exit(f"ABORT: {d} is missing held position(s) {sorted(missing)} — this is a "
                 f"record gap, not a stale total. Backfill the position first.")

    for p in pac:
        for f in ('ticker', 'quantity', 'entryPrice', 'closingPrice'):
            if p.get(f) is None:
                sys.exit(f"ABORT: {d} {p.get('ticker')} has no {f} — cannot recompute.")

    pv = round(sum(p['closingPrice'] * p['quantity'] for p in pac), 2)
    cap = round(sum(p['entryPrice'] * p['quantity'] for p in pac), 2)
    cp = s.get('closingPrices') or {}
    orphan_keys = sorted(set(cp) - here)

    changes = {}
    if abs((s.get('portfolioValue') or 0) - pv) > 0.01:
        changes['portfolioValue'] = (s.get('portfolioValue'), pv)
    if abs((s.get('capitalEngaged') or 0) - cap) > 0.01:
        changes['capitalEngaged'] = (s.get('capitalEngaged'), cap)
    if abs((s.get('unrealizedPnL') or 0) - (pv - cap)) > 0.01:
        changes['unrealizedPnL'] = (s.get('unrealizedPnL'), round(pv - cap, 2))
    if s.get('positionCount') != len(pac):
        changes['positionCount'] = (s.get('positionCount'), len(pac))
    if orphan_keys:
        changes['closingPrices'] = (f'{len(cp)} keys', f'{len(cp)-len(orphan_keys)} keys, dropping {orphan_keys}')

    if not changes:
        print(f"  {d}: already consistent, nothing to do.")
        continue
    plan.append({'date': d, 'pv': pv, 'cap': cap, 'unreal': round(pv - cap, 2),
                 'count': len(pac), 'orphans': orphan_keys, 'changes': changes,
                 'dailyPnL': s.get('dailyPnL'), 'realizedPnL': s.get('realizedPnL')})

if not plan:
    sys.exit("Nothing to patch — all three already satisfy the invariants.")

for p in plan:
    print(f"\n{p['date']}   ({len(p['changes'])} field(s) to correct)")
    for f, (old, new) in p['changes'].items():
        if isinstance(old, str):
            print(f"    {f:<16} {old:>18}  ->  {new}")
        else:
            print(f"    {f:<16} {old:>18,.2f}  ->  {new:>15,.2f}   ({new-old:+,.2f})")
    print(f"    {'dailyPnL':<16} {p['dailyPnL']:>18,.2f}      UNTOUCHED (immutability rule)")
    print(f"    {'realizedPnL':<16} {p['realizedPnL']:>18,.2f}      UNTOUCHED (no sale involved)")
    print(f"    {'positionsAtClose':<16} {'':>18}      UNTOUCHED (asserted identical after write)")

print(f"\n{len(plan)} snapshot(s) to patch. Every other snapshot untouched.")

if not APPLY:
    print("\n[DRY-RUN] No write performed. Re-run with --apply to write.")
    sys.exit(0)

before_pac = {p['date']: by_date[p['date']].get('positionsAtClose') for p in plan}
by_plan = {p['date']: p for p in plan}
new_snaps = []
for s in snaps:
    if s['date'] in by_plan:
        p = by_plan[s['date']]
        s = dict(s)
        s['portfolioValue'] = p['pv']
        s['capitalEngaged'] = p['cap']
        s['unrealizedPnL'] = p['unreal']
        s['positionCount'] = p['count']
        if p['orphans']:
            s['closingPrices'] = {k: v for k, v in (s.get('closingPrices') or {}).items()
                                  if k not in p['orphans']}
    new_snaps.append(s)

ref.update({'snapshots': new_snaps})
print("\n[APPLIED] snapshots[] updated (totals only).\n")

# ------------------------------------------------------------------ verify
fresh = {s['date']: s for s in ref.get().to_dict()['snapshots']}
print("[VERIFY]")
ok = True
for p in plan:
    s = fresh[p['date']]
    pac = s.get('positionsAtClose') or []
    cp = s.get('closingPrices') or {}
    pv = sum(x['closingPrice'] * x['quantity'] for x in pac)
    cap = sum(x['entryPrice'] * x['quantity'] for x in pac)
    checks = {
        'pv = S(close x qty)': abs(s.get('portfolioValue', 0) - pv) < 0.01,
        'cap = S(entry x qty)': abs(s.get('capitalEngaged', 0) - cap) < 0.01,
        'unreal = pv - cap': abs(s.get('unrealizedPnL', 0) - (pv - cap)) < 0.01,
        'posCount = len(pac)': s.get('positionCount') == len(pac),
        'cp keys = pac tickers': set(cp) == {x['ticker'] for x in pac},
        'positionsAtClose identical': pac == before_pac[p['date']],
        'dailyPnL untouched': s.get('dailyPnL') == p['dailyPnL'],
        'realizedPnL untouched': s.get('realizedPnL') == p['realizedPnL'],
    }
    bad = [k for k, v in checks.items() if not v]
    ok &= not bad
    print(f"  {p['date']}  {'OK' if not bad else 'FAIL -> ' + ', '.join(bad)}")

# and nothing else moved
others = [d for d in fresh if d not in by_plan]
moved = [d for d in others
         if any(fresh[d].get(f) != by_date[d].get(f)
                for f in ('portfolioValue', 'capitalEngaged', 'unrealizedPnL',
                          'positionCount', 'dailyPnL', 'realizedPnL'))]
print(f"  {len(others)} untargeted snapshot(s): {'unchanged' if not moved else 'MOVED -> ' + str(moved)}")
ok &= not moved
print("\n[VERIFY] all invariants hold, nothing else touched." if ok else "\n[VERIFY] FAILURES ABOVE.")
sys.exit(0 if ok else 1)
