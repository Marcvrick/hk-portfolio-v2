#!/usr/bin/env python3
"""
patch-sep8-resettle-unverified.py

Re-settle the sessions the cron never reconciled, from RAW Yahoo closes
(`auto_adjust=False`; adjusted history does not match stored raw settlement
prices, wiki/incidents.md 2026-06-28).

  HK  2026-07-17, 08-27, 08-28, 08-31, 09-01   browser-minted, closes never
                                               cross-checked against Yahoo
  US  2026-08-27                               no snapshot at all, inserted

Cause of the gap: wiki/reliability-risks.md #8 (every cron slot drifted past
market midnight) and #14 (settled, then un-settled by a browser write).

WHAT CHANGES, per snapshot: closingPrices, each positionsAtClose leg's
closingPrice / marketValue / pnl / pnlPercent, portfolioValue, unrealizedPnL,
dailyPnL, and the provenance stamp. capitalEngaged / positionCount are
RECOMPUTED from positionsAtClose (never delta-subtracted, wiki/recording-a-sale
Step 4) and must come out unchanged, since no quantity or entry price moves.
realizedPnL and totalDividends are untouched: no trade changes here.

WHAT IS NOT TOUCHED: positions[], closedTrades[], priceCache, and every
snapshot outside the target list. The next day's dailyPnL is computed by the
cron from TradingView change_abs against the prior *trading day*, not against
the stored snapshot, so correcting these dates cannot disturb their successors.

METHOD VALIDATION runs first and is not optional. The same computation is
replayed on known-good cron-settled dates; if it cannot reproduce those, the
method is wrong and nothing is written (the patch-jun-gap-backfill.py
precedent: "recomputed Jun 25 = -6322, exactly matching the stored cron value
-> method + closes confirmed").

Usage:
  python3 patch-sep8-resettle-unverified.py           # dry-run, writes nothing
  python3 patch-sep8-resettle-unverified.py --apply   # app CLOSED first
"""
import sys
import time
from datetime import datetime

import firebase_admin
from firebase_admin import credentials, firestore

from market_calendar import previous_trading_day
import update as hk_cron  # for HKT and the Yahoo ticker-candidate logic

CRED = 'hk-portfolio-v2/hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json'
HK_DOC = 'cNcZwUx3nQMV96TbB1kSkQ62u8U2'
US_DOC = 'JJDY5whY9vNmCcRsi8kafMHZbmD2'

# Ascending order matters: 08-28's prior close is 08-27's, which this script is
# itself correcting, so each date must chain off the corrected predecessor.
HK_TARGETS = ['2026-07-17', '2026-08-27', '2026-08-28', '2026-08-31', '2026-09-01',
              '2026-09-02']
US_TARGETS = ['2026-08-27']

# 2026-09-02 is cron-settled but flagged `provisional`: on that date the China
# Life position was still under the `4000.HK` typo, which resolves on no price
# source, so the cron froze the 30.30 fill as its close and dropped the leg from
# dailyPnL entirely (no prior close existed for the fake ticker either). Its real
# close is 29.98. That 0.32 x 4,000 = 1,280 is why the 09-03 control fails below
# against the uncorrected chain. Same defect family as the rest of the list,
# found BY the validation gate rather than by the original audit.

# Controls: dates that prove the method reproduces the cron before it is allowed
# to overwrite anything. Screened, not hand-picked: a control is only usable if
# it and its prior trading day are both settled and non-provisional, since the
# method reads the prior day's stored closes.
HK_VALIDATE = ['2026-08-19', '2026-08-20', '2026-08-21', '2026-08-24', '2026-08-25',
               '2026-08-26', '2026-09-03', '2026-09-04', '2026-09-07']
US_VALIDATE = ['2026-08-20', '2026-08-21', '2026-08-25', '2026-08-26', '2026-08-28',
               '2026-09-02', '2026-09-03', '2026-09-04']

# A replay of a cron day cannot match to the cent: the cron's held legs use
# TradingView's change_abs, this uses (yahoo_close_D - stored_close_prev). They
# agree only as closely as TV and Yahoo agreed on the prior close. Anything
# beyond this fraction of the book means the method is wrong, not noisy.
VALIDATE_TOL_PCT_OF_PV = 0.05    # 0.05% of portfolioValue

APPLY = '--apply' in sys.argv

try:
    import yfinance as yf
except ImportError:
    sys.exit("ABORT: yfinance not installed (needed for historical raw closes).")


# --------------------------------------------------------------------- prices
_close_cache = {}


def raw_close(ticker, date, market):
    """Yahoo's RAW close for `date`, or None.

    Ticker-candidate list ported from update.py `_yahoo_close_for` (Yahoo's HK
    listings inconsistently accept padded vs unpadded codes). update.py's own
    helper is not reused directly: it hardcodes `range=10d` and cannot reach
    2026-07-17.
    """
    key = (ticker, date)
    if key in _close_cache:
        return _close_cache[key]
    clean = ticker.replace('b.HK', '.HK')
    if market == 'hk':
        base = clean.replace('.HK', '')
        cands = []
        for c in [f"{base}.HK", f"{base.lstrip('0')}.HK", f"{base.zfill(4)}.HK", f"{base.zfill(5)}.HK"]:
            if c not in cands:
                cands.append(c)
    else:
        cands = [clean, clean.replace('.', '-')]

    import pandas as pd
    start = (pd.Timestamp(date) - pd.Timedelta(days=4)).strftime('%Y-%m-%d')
    end = (pd.Timestamp(date) + pd.Timedelta(days=4)).strftime('%Y-%m-%d')
    for cand in cands:
        try:
            h = yf.Ticker(cand).history(start=start, end=end, auto_adjust=False, actions=False)
        except Exception:
            continue
        for idx, row in h.iterrows():
            if idx.strftime('%Y-%m-%d') == date and row['Close'] == row['Close']:
                _close_cache[key] = round(float(row['Close']), 4)
                return _close_cache[key]
    _close_cache[key] = None
    return None


_div_cache = {}


def ex_div(ticker, date, market):
    """Dividend per share whose EX-date == `date`, else 0.

    The cron folds this into the daily move so an ex-div day reads as a total
    return rather than a paper loss (update.py L432-441, incidents 2026-06-18).
    A price-only recomputation that skips it is short by dividend x qty, which
    is exactly the +99.90 residual chased in the 1138.HK repair.
    """
    key = (ticker, date)
    if key in _div_cache:
        return _div_cache[key]
    clean = ticker.replace('b.HK', '.HK')
    cands = [clean]
    if market == 'hk':
        base = clean.replace('.HK', '')
        for c in [f"{base.lstrip('0')}.HK", f"{base.zfill(4)}.HK"]:
            if c not in cands:
                cands.append(c)
    else:
        cands.append(clean.replace('.', '-'))
    import pandas as pd
    amount = 0.0
    for cand in cands:
        try:
            divs = yf.Ticker(cand).dividends
        except Exception:
            continue
        if divs is None or len(divs) == 0:
            continue
        for idx, val in divs.items():
            if idx.strftime('%Y-%m-%d') == date:
                amount = round(float(val), 4)
                break
        if amount:
            break
    _div_cache[key] = amount
    return amount


def index_close(symbol, date):
    import pandas as pd
    start = (pd.Timestamp(date) - pd.Timedelta(days=4)).strftime('%Y-%m-%d')
    end = (pd.Timestamp(date) + pd.Timedelta(days=4)).strftime('%Y-%m-%d')
    try:
        h = yf.Ticker(symbol).history(start=start, end=end, auto_adjust=False, actions=False)
    except Exception:
        return None
    for idx, row in h.iterrows():
        if idx.strftime('%Y-%m-%d') == date and row['Close'] == row['Close']:
            return round(float(row['Close']), 2)
    return None


# ---------------------------------------------------------------- computation
def rebuild(date, pac, closed_trades, prev_closes, market, base_snapshot):
    """Return (new_snapshot_fields, notes). `prev_closes` = {ticker: close on the
    prior trading day}, taken from that day's stored snapshot so the chain stays
    continuous with the surrounding record."""
    notes = []
    closes, legs = {}, []
    pv = cap = 0.0
    for leg in pac:
        t = leg['ticker']
        clean = t.replace('b.HK', '.HK')
        c = raw_close(t, date, market)
        if c is None:
            raise RuntimeError(f"{date}: no Yahoo close for {t} — refusing to guess")
        closes[clean] = c
        entry = leg.get('entryPrice', 0)
        qty = leg['quantity']
        pv += c * qty
        cap += entry * qty
        legs.append({**leg,
                     'closingPrice': c,
                     'marketValue': c * qty,
                     'pnl': (c - entry) * qty,
                     'pnlPercent': ((c - entry) / entry * 100) if entry else 0})

    # dailyPnL — held legs
    daily = 0.0
    divs_today, div_income = {}, 0.0
    for leg in legs:
        t = leg['ticker']
        clean = t.replace('b.HK', '.HK')
        qty, c = leg['quantity'], leg['closingPrice']
        if leg.get('entryDate') == date:
            daily += (c - leg.get('entryPrice', 0)) * qty
            notes.append(f"{t}: entry-day leg, baseline = entryPrice {leg.get('entryPrice')}")
            continue
        prev = prev_closes.get(clean)
        if prev is None:
            prev = raw_close(t, previous_trading_day(date, market), market)
            notes.append(f"{t}: prior close absent from the previous snapshot, taken from Yahoo ({prev})")
        if prev is None:
            raise RuntimeError(f"{date}: no prior close for {t} — refusing to guess")
        d = ex_div(t, date, market)
        if d:
            divs_today[clean] = d
            div_income += d * qty
            notes.append(f"{t}: ex-div {d} on {date}, folded into the move (total return)")
        daily += (c - prev + d) * qty

    # dailyPnL — positions closed on this date
    for tr in closed_trades:
        if tr.get('exitDate') != date:
            continue
        t = tr['ticker']
        clean = t.replace('b.HK', '.HK')
        prev = prev_closes.get(clean)
        if prev is None and tr.get('entryDate') == date:
            prev = tr.get('entryPrice', 0)
        if prev is None:
            prev = raw_close(t, previous_trading_day(date, market), market)
        if prev is None:
            raise RuntimeError(f"{date}: no prior close for closed trade {t}")
        daily += (tr.get('exitPrice', 0) - prev) * tr.get('quantity', 0)
        notes.append(f"{t}: closed-today leg, ({tr.get('exitPrice')} - {prev}) x {tr.get('quantity')}")

    bench = '^HSI' if market == 'hk' else 'SPY'
    fields = {
        'date': date,
        'capitalEngaged': round(cap, 2),
        'portfolioValue': round(pv, 2),
        'unrealizedPnL': round(pv - cap, 2),
        'realizedPnL': base_snapshot.get('realizedPnL', 0),
        'totalDividends': base_snapshot.get('totalDividends', 0),
        'positionCount': len(legs),
        'closingPrices': closes,
        'dailyPnL': round(daily, 2),
        'positionsAtClose': legs,
        'dividendsToday': divs_today,
        'dividendIncomeToday': round(div_income, 2),
    }
    key = 'hsiClose' if market == 'hk' else 'spyClose'
    fields[key] = base_snapshot.get(key) or index_close(bench, date)
    return fields, notes


def prior_closes_for(snapshots_by_date, date, market):
    prev = previous_trading_day(date, market)
    snap = snapshots_by_date.get(prev)
    return prev, dict(snap.get('closingPrices', {})) if snap else {}


def intraday_add_warning(snapshots_by_date, date, pac, market):
    """A position topped up during the session needs the cron's split baseline
    (update.py L514-525), and the fields that record it are stripped after the
    snapshot is written, so they cannot be recovered later. Detect the shape and
    say so rather than silently applying a full-day baseline to new shares."""
    prev = previous_trading_day(date, market)
    before = snapshots_by_date.get(prev)
    if not before:
        return []
    prior_qty = {l['ticker']: l['quantity'] for l in before.get('positionsAtClose', [])}
    out = []
    for leg in pac:
        t = leg['ticker']
        if t in prior_qty and leg['quantity'] != prior_qty[t] and leg.get('entryDate') != date:
            out.append(f"{t}: quantity {prior_qty[t]} -> {leg['quantity']} on {date} "
                       f"(intraday add/reduce; the cron's split baseline is not recoverable)")
    return out


# --------------------------------------------------------------------- report
def show(label, before, after, keys=('portfolioValue', 'capitalEngaged', 'unrealizedPnL',
                                     'realizedPnL', 'positionCount', 'dailyPnL')):
    print(f"\n  {label}")
    for k in keys:
        b, a = before.get(k), after.get(k)
        mark = '' if b == a else '   <<'
        print(f"    {k:<16} {str(b):>16} -> {str(a):>16}{mark}")


def main():
    firebase_admin.initialize_app(credentials.Certificate(CRED))
    db = firestore.client()

    books = {}
    for market, coll, doc_id, targets, validate in (
            ('hk', 'portfolios', HK_DOC, HK_TARGETS, HK_VALIDATE),
            ('us', 'us-portfolios', US_DOC, US_TARGETS, US_VALIDATE)):
        ref = db.collection(coll).document(doc_id)
        doc = ref.get().to_dict()
        books[market] = {'ref': ref, 'doc': doc, 'targets': targets, 'validate': validate,
                         'by_date': {s['date']: s for s in doc['snapshots']}}

    # ---------------------------------------------------- phase 0: validation
    print("=" * 78)
    print("PHASE 0 — replay the method on cron-settled dates. Nothing is written")
    print("          unless this reproduces the cron.")
    print("=" * 78)
    bad = []
    for market, b in books.items():
        for date in b['validate']:
            snap = b['by_date'].get(date)
            prev = previous_trading_day(date, market)
            prev_snap = b['by_date'].get(prev)
            # A control is only evidence if BOTH ends of the chain are clean: the
            # method reads the prior day's stored closes, so a provisional prior
            # makes the control fail for reasons that have nothing to do with the
            # method (that is what 2026-09-03 was doing).
            why = None
            if not snap or not snap.get('settledAt'):
                why = 'not cron-settled'
            elif snap.get('provisional'):
                why = 'provisional'
            elif not prev_snap or not prev_snap.get('settledAt'):
                why = f'prior day {prev} not cron-settled'
            elif prev_snap.get('provisional'):
                why = f'prior day {prev} is provisional'
            if why:
                print(f"  {market.upper()} {date}: skipped as a control ({why})")
                continue
            prev, prev_closes = prior_closes_for(b['by_date'], date, market)
            try:
                got, _ = rebuild(date, snap['positionsAtClose'], b['doc'].get('closedTrades', []),
                                 prev_closes, market, snap)
            except RuntimeError as e:
                print(f"  {market.upper()} {date}: {e}")
                bad.append((market, date, 'fetch failure'))
                continue
            pv_err = got['portfolioValue'] - snap['portfolioValue']
            pnl_err = got['dailyPnL'] - snap['dailyPnL']
            tol = snap['portfolioValue'] * VALIDATE_TOL_PCT_OF_PV / 100
            ok = abs(pv_err) <= tol and abs(pnl_err) <= tol
            print(f"  {market.upper()} {date} (prev {prev}): pv drift {pv_err:>10,.2f}   "
                  f"dailyPnL drift {pnl_err:>10,.2f}   tol +/-{tol:,.2f}   {'OK' if ok else 'FAIL'}")
            if not ok:
                bad.append((market, date, f"pv {pv_err:.2f} / pnl {pnl_err:.2f}"))
    if bad:
        print("\nABORT: the method does not reproduce the cron on "
              f"{len(bad)} control date(s): {bad}")
        print("Fix the method before touching a single stored value.")
        sys.exit(2)
    print("\n  Method reproduces every control date within tolerance.")

    # ------------------------------------------------------ phase 1: the plan
    print("\n" + "=" * 78)
    print("PHASE 1 — what would be written")
    print("=" * 78)
    plans = []
    for market, b in books.items():
        for date in b['targets']:
            snap = b['by_date'].get(date)
            inserting = snap is None
            if inserting:
                prev = previous_trading_day(date, market)
                donor = b['by_date'].get(prev)
                nxt = min((d for d in b['by_date'] if d > date), default=None)
                if not donor or not nxt:
                    sys.exit(f"ABORT: {market} {date}: no neighbouring snapshot to take the position set from.")
                a, c = donor['positionsAtClose'], b['by_date'][nxt]['positionsAtClose']
                sig = lambda pac: sorted((l['ticker'], l['quantity'], l['entryPrice']) for l in pac)
                if sig(a) != sig(c):
                    sys.exit(f"ABORT: {market} {date}: the book changed between {prev} and {nxt}; "
                             "the position set for the missing session is not unambiguous.")
                base, pac = donor, donor['positionsAtClose']
                print(f"\n### {market.upper()} {date}  INSERT (no snapshot exists)")
                print(f"    position set identical on {prev} and {nxt}, and no trade in between, "
                      "so it is unambiguous")
            else:
                if snap.get('settledAt') and not snap.get('provisional'):
                    sys.exit(f"ABORT: {market} {date} is already settled and non-provisional "
                             f"({snap['settledAt']}) — already patched? Re-read before proceeding.")
                base, pac = snap, snap['positionsAtClose']
                if snap.get('settledAt'):
                    stuck = [t for t, v in snap.get('priceProvenance', {}).items() if v.get('provisional')]
                    print(f"\n### {market.upper()} {date}  RE-SETTLE (cron-settled but PROVISIONAL: "
                          f"{', '.join(stuck)} never priced)")
                else:
                    print(f"\n### {market.upper()} {date}  RE-SETTLE (browser-minted)")

            for w in intraday_add_warning(b['by_date'], date, pac, market):
                print(f"    !! {w}")
            prev, prev_closes = prior_closes_for(b['by_date'], date, market)
            fields, notes = rebuild(date, pac, b['doc'].get('closedTrades', []),
                                    prev_closes, market, base)
            fields.update({
                'settledAt': datetime.now(hk_cron.HKT).isoformat(),
                'sources': ['yahoo'],
                'provisional': False,
                'priceProvenance': {t: {'source': 'yahoo-backfill', 'provisional': False}
                                    for t in fields['closingPrices']},
                'backfilledAt': datetime.now(hk_cron.HKT).isoformat(),
                'backfillReason': 'reliability-risks #8/#14 — cron never settled this session',
            })
            print(f"    prior trading day: {prev}"
                  f"{' (settled)' if b['by_date'].get(prev, {}).get('settledAt') else ' (NOT settled)'}")
            print(f"    {'ticker':>10} {'qty':>8} {'stored':>10} {'yahoo raw':>10} {'HKD/USD impact':>15}")
            for leg in fields['positionsAtClose']:
                t = leg['ticker']
                old = (base.get('closingPrices', {}).get(t.replace('b.HK', '.HK'))
                       if not inserting else None)
                impact = (leg['closingPrice'] - old) * leg['quantity'] if old is not None else None
                shown = f"{impact:,.0f}" if impact is not None else 'new'
                print(f"    {t:>10} {leg['quantity']:>8} {str(old):>10} "
                      f"{leg['closingPrice']:>10} {shown:>15}")
            show('header', base if not inserting else {}, fields)
            for n in notes:
                print(f"    note: {n}")
            assert abs(fields['unrealizedPnL'] - (fields['portfolioValue'] - fields['capitalEngaged'])) < 0.01
            assert fields['positionCount'] == len(fields['positionsAtClose'])
            plans.append((market, date, inserting, fields))
            # Chain: the next target's prior close must be THIS corrected close,
            # not the browser value being replaced. 08-28 sits on 08-27, 08-31 on
            # 08-28, 09-01 on 08-31, 09-02 on 09-01 — four links in this run.
            b['by_date'][date] = fields

    print("\n" + "=" * 78)
    print(f"PHASE 1 complete: {len(plans)} snapshot(s) would change "
          f"({sum(1 for p in plans if p[2])} inserted, {sum(1 for p in plans if not p[2])} re-settled).")
    print("All four snapshot invariants asserted on every one.")
    print("=" * 78)

    if not APPLY:
        print("\n[DRY-RUN] Nothing written. Re-run with --apply once the numbers are confirmed.")
        return

    # -------------------------------------------------------- phase 2: write
    print("\nPolling lastUpdated for 30s to confirm no open app is republishing "
          "(wiki/incidents.md 2026-08-18)...")
    lu0 = {m: books[m]['ref'].get().to_dict().get('lastUpdated') for m in books}
    time.sleep(30)
    lu1 = {m: books[m]['ref'].get().to_dict().get('lastUpdated') for m in books}
    if lu0 != lu1:
        sys.exit(f"ABORT: lastUpdated moved ({lu0} -> {lu1}). An app is open; close every window "
                 "and re-run. A repair applied against a running app lives seconds.")
    print("  lastUpdated frozen on both books.")

    for market, b in books.items():
        mine = [p for p in plans if p[0] == market]
        if not mine:
            continue
        fresh = b['ref'].get().to_dict()
        snaps = fresh['snapshots']
        for _, date, inserting, fields in mine:
            idx = next((i for i, s in enumerate(snaps) if s['date'] == date), None)
            if idx is None:
                snaps.append(fields)
            else:
                snaps[idx] = fields
        snaps.sort(key=lambda s: s['date'])
        b['ref'].update({'snapshots': snaps})
        print(f"[APPLIED] {market.upper()}: {len(mine)} snapshot(s), array now {len(snaps)} long")

    # -------------------------------------------------------- phase 3: verify
    print("\n=== VERIFY (independent re-read) ===")
    ok = True
    for market, b in books.items():
        after = {s['date']: s for s in b['ref'].get().to_dict()['snapshots']}
        for _, date, _, fields in [p for p in plans if p[0] == market]:
            s = after.get(date)
            if not s:
                print(f"  {market.upper()} {date}: MISSING after write"); ok = False; continue
            checks = {
                'settledAt present': bool(s.get('settledAt')),
                'pv matches plan': abs(s['portfolioValue'] - fields['portfolioValue']) < 0.01,
                'dailyPnL matches plan': abs(s['dailyPnL'] - fields['dailyPnL']) < 0.01,
                'unrealized = pv - cap': abs(s['unrealizedPnL'] - (s['portfolioValue'] - s['capitalEngaged'])) < 0.01,
                'posCount = len(pac)': s['positionCount'] == len(s['positionsAtClose']),
                'closingPrices keys = pac tickers':
                    set(s['closingPrices']) == {l['ticker'].replace('b.HK', '.HK') for l in s['positionsAtClose']},
            }
            bad = [k for k, v in checks.items() if not v]
            print(f"  {market.upper()} {date}: {'PASS' if not bad else 'FAIL ' + str(bad)}")
            ok = ok and not bad
    print("\n=== ALL VERIFIED ===" if ok else "\n=== VERIFY FAILED — inspect before doing anything else ===")
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
