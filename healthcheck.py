#!/usr/bin/env python3
"""
healthcheck.py — one read-only pass over everything that can be checked from the data.

Answers "is the system actually working" with evidence instead of assertion. Every check
prints what it measured, not just OK/FAIL, so a green line can be argued with.

  1. Snapshot freshness     — is the latest snapshot the session it should be?
  2. Cron provenance        — settledAt/sources/priceProvenance present (cron-written, not
                              browser-minted; wiki/incidents.md 2026-08-10 (b))
  3. Snapshot invariants    — pv/cap/unrealized/posCount/closingPrices agree with
                              positionsAtClose, on EVERY snapshot (wiki/snapshot-schema.md)
  4. Record completeness    — every live position appears in the latest snapshot
                              (wiki/incidents.md 2026-08-08: consistency != completeness)
  5. Stale prices           — a holding whose close never moves is not being priced
  6. Unexplained exits      — a ticker leaving the book with no sale in the interval
                              (wiki/incidents.md 2026-08-10 (d))
  7. realizedPnL vs ledger  — the stored cumulative equals the closedTrades sum
  8. Missing sessions       — trading days with no snapshot
  9. dailyPnL reconciliation— sum of dailyPnL vs the balance-sheet delta, and where they part

Usage: python3 healthcheck.py [hk|us|both]
"""
import sys, datetime as dt
from collections import defaultdict
import firebase_admin
from firebase_admin import credentials, firestore
from market_calendar import is_trading_day

CRED = 'hk-portfolio-v2/hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json'
BOOKS = {
    'hk': ('portfolios', 'cNcZwUx3nQMV96TbB1kSkQ62u8U2', 'HKD', 'HK'),
    'us': ('us-portfolios', 'JJDY5whY9vNmCcRsi8kafMHZbmD2', 'USD', 'US'),
}
# market_calendar keys are lowercase; the label above is only for display
MKT = {'HK': 'hk', 'US': 'us'}
D = dt.date.fromisoformat
FAILURES = []


def check(book_label, name, ok, detail):
    tag = 'OK  ' if ok else 'WARN'
    if not ok:
        FAILURES.append(f'{book_label}: {name}')
    print(f'  [{tag}] {name:<26} {detail}')


def run(key):
    coll, uid, ccy, label = BOOKS[key]
    doc = firestore.client().collection(coll).document(uid).get().to_dict()
    snaps = sorted(doc.get('snapshots', []), key=lambda s: s['date'])
    closed = doc.get('closedTrades') or []
    positions = doc.get('positions') or []
    last = snaps[-1]
    print(f'\n===== {label} — {coll}/{uid[:8]}… — {len(snaps)} snapshots, '
          f'{len(positions)} open, {len(closed)} closed =====')

    # 1. freshness — measured in SESSIONS, not calendar days. A 3-calendar-day lag on a
    # Monday is nothing (weekend); one missed session is the thing worth knowing. The most
    # recent session's cron may legitimately not have fired yet: HK settles ~16:35 HKT, US
    # ~22:00 ET, so the current session is excused.
    expected = dt.date.today()
    while not is_trading_day(expected.isoformat(), MKT[label]):
        expected -= dt.timedelta(days=1)
    sessions_behind, d = 0, D(last['date']) + dt.timedelta(days=1)
    while d <= expected:
        if is_trading_day(d.isoformat(), MKT[label]):
            sessions_behind += 1
        d += dt.timedelta(days=1)
    check(label, 'snapshot freshness', sessions_behind <= 1,
          f"latest {last['date']}, last {label} session {expected.isoformat()} — "
          f"{sessions_behind} session(s) behind"
          + (" (today's cron may not have fired yet)" if sessions_behind == 1 else ''))

    # 2. cron provenance on the latest
    cron_written = all(last.get(f) for f in ('settledAt', 'sources', 'priceProvenance'))
    check(label, 'latest is cron-written', cron_written,
          'settledAt/sources/priceProvenance present' if cron_written
          else 'MISSING cron fields -> browser-minted, numbers unreconciled')

    # 3. invariants, every snapshot — CLASSIFIED, because one flag over three conditions
    # reads as "14 broken" when only 3 carry a wrong number. Verify values, not counts.
    empty, keys_only, numeric = [], [], []
    for s in snaps:
        pac = s.get('positionsAtClose') or []
        pv = sum(p.get('closingPrice', 0) * p.get('quantity', 0) for p in pac)
        cap = sum(p.get('entryPrice', 0) * p.get('quantity', 0) for p in pac)
        drift_cap = (s.get('capitalEngaged') or 0) - cap
        drift_pv = (s.get('portfolioValue') or 0) - pv
        count_bad = s.get('positionCount') != len(pac)
        keys_bad = set(s.get('closingPrices') or {}) != {p.get('ticker') for p in pac}
        if not pac:
            empty.append(s['date'])            # detail array absent; top-level totals are all there is
        elif abs(drift_cap) > 0.01 or abs(drift_pv) > 0.01 or count_bad:
            numeric.append((s['date'], drift_cap, drift_pv))
        elif keys_bad:
            keys_only.append(s['date'])        # numbers agree, a closingPrices key is stray/missing
    check(label, 'stored totals vs detail', not numeric,
          f'{len(snaps) - len(numeric)}/{len(snaps)} agree'
          + ('' if not numeric else ' — DRIFT: ' + ', '.join(
              f'{d} (cap {c:+,.0f}' + (f', pv {v:+,.0f}' if abs(v) > 0.01 else '') + ')'
              for d, c, v in numeric)))
    if empty:
        print(f'         note: {len(empty)} snapshot(s) carry no positionsAtClose array '
              f'({empty[0]}..{empty[-1]}) — pre-schema-stabilisation, top-level totals only')
    if keys_only:
        print(f'         note: {len(keys_only)} snapshot(s) have a closingPrices key mismatch '
              f'with correct numbers: {keys_only}')

    # 4. record completeness
    in_last = {p['ticker'] for p in (last.get('positionsAtClose') or [])}
    absent = [p['ticker'] for p in positions if p['ticker'] not in in_last]
    check(label, 'record completeness', not absent,
          f'{len(positions)} live positions, all in {last["date"]}' if not absent
          else f'HELD BUT UNRECORDED: {absent}')

    # 5. stale prices
    seen = defaultdict(set)
    for s in snaps[-15:]:
        for t, v in (s.get('closingPrices') or {}).items():
            seen[t].add(v)
    stale = [t for t in in_last if len(seen[t]) == 1 and len([s for s in snaps[-15:]
             if t in (s.get('closingPrices') or {})]) > 2]
    check(label, 'prices actually moving', not stale,
          f'{len(in_last)} holdings, all repriced over the last 15 snapshots' if not stale
          else f'FROZEN CLOSE: {stale}')

    # 6. unexplained exits
    orphans = []
    for i in range(1, len(snaps)):
        after = {p['ticker'] for p in (snaps[i].get('positionsAtClose') or [])}
        for p in (snaps[i - 1].get('positionsAtClose') or []):
            if p['ticker'] in after:
                continue
            if any(c.get('ticker') == p['ticker']
                   and snaps[i - 1]['date'] <= c.get('exitDate', '') <= snaps[i]['date']
                   for c in closed):
                continue
            orphans.append((snaps[i]['date'], p['ticker'],
                            (p.get('closingPrice', 0) - p.get('entryPrice', 0)) * p.get('quantity', 0)))
    opl = sum(o[2] for o in orphans)
    dates = sorted({o[0] for o in orphans})
    check(label, 'exits all explained', not orphans,
          'every position that left the book has a matching sale' if not orphans
          else f'{len(orphans)} unexplained on {dates}, {opl:+,.2f} {ccy} out of the curve')

    # 7. realizedPnL vs ledger
    ledger = sum((c['exitPrice'] - c['entryPrice']) * c['quantity'] for c in closed)
    check(label, 'realizedPnL = ledger', abs((last.get('realizedPnL') or 0) - ledger) < 0.01,
          f'stored {last.get("realizedPnL"):,.2f} vs closedTrades sum {ledger:,.2f}')

    # 8. missing sessions
    have = {s['date'] for s in snaps}
    d, missing = D(snaps[0]['date']), []
    end = D(last['date'])
    while d <= end:
        iso = d.isoformat()
        if is_trading_day(iso, MKT[label]) and iso not in have:
            missing.append(iso)
        d += dt.timedelta(days=1)
    check(label, 'session coverage', not missing,
          f'no gap over {snaps[0]["date"]}..{last["date"]}' if not missing
          else f'{len(missing)} session(s) with no snapshot: {missing}')

    # 9. dailyPnL vs balance-sheet delta
    eq = lambda s: (s.get('unrealizedPnL') or 0) + (s.get('realizedPnL') or 0)
    delta = eq(last) - eq(snaps[0])
    summed = sum(s.get('dailyPnL') or 0 for s in snaps[1:])
    days = [(snaps[i]['date'], eq(snaps[i]) - eq(snaps[i-1]) - (snaps[i].get('dailyPnL') or 0))
            for i in range(1, len(snaps))
            if abs(eq(snaps[i]) - eq(snaps[i-1]) - (snaps[i].get('dailyPnL') or 0)) > 1]
    check(label, 'dailyPnL reconciliation', abs(delta - summed) < 1,
          f'delta {delta:+,.0f} = sum {summed:+,.0f}' if abs(delta - summed) < 1
          else f'delta {delta:+,.0f} vs sum {summed:+,.0f} ({delta-summed:+,.0f}) over '
               f'{len(days)} day(s): {[(d, round(v)) for d, v in days]}')


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else 'both'
    firebase_admin.initialize_app(credentials.Certificate(CRED))
    for k in (['hk', 'us'] if which == 'both' else [which]):
        run(k)
    print('\n' + '=' * 70)
    if FAILURES:
        print(f'{len(FAILURES)} check(s) not clean:')
        for f in FAILURES:
            print(f'  - {f}')
        print('\nA WARN is a fact about the data, not necessarily a bug to fix today.')
    else:
        print('Every check clean on every book.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
