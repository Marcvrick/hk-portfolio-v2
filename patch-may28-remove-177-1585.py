#!/usr/bin/env python3
"""
patch-may28-remove-177-1585.py
Record two sales executed 2026-05-28 that were never entered in the app:
  - 0177.HK exit 10.30 (6,000 sh, entry 9.997, 2025-10-13)  realized +1,818
  - 1585.HK exit 11.26 (8,000 sh, entry 13.04, 2026-04-15)  realized -14,240

Diagnosed 2026-06-11 (diagnose-resurrected.py / diagnose-presence-history.py):
  - both still OPEN in positions; NO closedTrades entry for either
  - cron gap: no snapshots between 2026-05-27 and 2026-06-03 — the sale date
    (May 28) has no snapshot; first affected snapshot is Jun 3
  - 5 snapshots wrongly count both as held: Jun 3, 8, 9, 10, 11
  - priceCache holds three stale keys: 0177.HK, 177.HK (stray), 1585.HK

What this writes (same method as patch-may29-remove-9988.py):
  - closedTrades[]: two entries, exitDate 2026-05-28
  - positions[]: remove both (13 -> 11)
  - priceCache: drop 0177.HK / 177.HK / 1585.HK
  - per affected snapshot:
      * remove both from positionsAtClose + closingPrices
      * RECOMPUTE portfolioValue / capitalEngaged / unrealizedPnL / positionCount
        from the resulting positionsAtClose (invariant-safe)
      * dailyPnL -= held-legs (close_date - close_prevTradingDay) x qty
        prevTD closes: Jun 2 + Jun 5 from yfinance raw (gap days),
        Jun 8/9/10 from the prior snapshot's stored closes
      * realizedPnL += -12,422 (both sales precede all five snapshots)

Held-legs removed from dailyPnL (0177 + 1585):
  Jun 3 : (10.50-11.01)*6000 + (11.56-11.60)*8000 = -3060 + -320  = -3380
  Jun 8 : (11.02-10.77)*6000 + (11.56-11.63)*8000 = +1500 + -560  = +940
  Jun 9 : (11.21-11.02)*6000 + (11.34-11.56)*8000 = +1140 + -1760 = -620
  Jun 10: (11.10-11.21)*6000 + (11.09-11.34)*8000 = -660  + -2000 = -2660
  Jun 11: (11.05-11.10)*6000 + (10.71-11.09)*8000 = -300  + -3040 = -3340

CAVEAT (Jun 3): the Jun 3 snapshot was not cron-written (no provenance/settledAt)
and its stored closes are stale May 27 prices (0177 10.50 = May 27 close; same for
1585 and 9988). Legs use the snapshot's own stored closes paired with yfinance
Jun 2 — Jun 3's session-P&L display is approximate; value fields are exact.

Idempotent: skips any ticker whose 2026-05-28 closedTrade already exists.

Usage:
  python3 patch-may28-remove-177-1585.py            # dry-run (default)
  python3 patch-may28-remove-177-1585.py --apply    # write to Firestore
"""
import sys
import firebase_admin
from firebase_admin import credentials, firestore

CRED = 'hk-portfolio-v2/hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json'
DOC_ID = 'cNcZwUx3nQMV96TbB1kSkQ62u8U2'

EXIT_DATE = '2026-05-28'

SALES = {
    '0177.HK': {'exit': 10.30, 'qty': 6000, 'entry': 9.997, 'entryDate': '2025-10-13'},
    '1585.HK': {'exit': 11.26, 'qty': 8000, 'entry': 13.04, 'entryDate': '2026-04-15'},
}
STALE_CACHE_KEYS = ('0177.HK', '177.HK', '1585.HK')

# prior-trading-day closes per snapshot date {date: {ticker: prevTD_close}}
# Jun 2 / Jun 5 from yfinance raw (cron gap); Jun 8/9/10 from prior snapshots
PREV_CLOSES = {
    '2026-06-03': {'0177.HK': 11.01, '1585.HK': 11.60},   # Jun 2, yfinance
    '2026-06-08': {'0177.HK': 10.77, '1585.HK': 11.63},   # Jun 5, yfinance
    '2026-06-09': {'0177.HK': 11.02, '1585.HK': 11.56},   # Jun 8 snapshot
    '2026-06-10': {'0177.HK': 11.21, '1585.HK': 11.34},   # Jun 9 snapshot
    '2026-06-11': {'0177.HK': 11.10, '1585.HK': 11.09},   # Jun 10 snapshot
}

REALIZED_TOTAL = round(sum((s['exit'] - s['entry']) * s['qty'] for s in SALES.values()), 2)  # -12422.0

APPLY = '--apply' in sys.argv

cred = credentials.Certificate(CRED)
firebase_admin.initialize_app(cred)
db = firestore.client()
ref = db.collection('portfolios').document(DOC_ID)
doc = ref.get().to_dict()

positions = list(doc.get('positions', []))
closed = list(doc.get('closedTrades', []))
snapshots = list(doc.get('snapshots', []))
price_cache = dict(doc.get('priceCache', {}))

# --- Idempotency: only process tickers not yet recorded ---
todo = {}
for t, s in SALES.items():
    if any(c.get('ticker') == t and c.get('exitDate') == EXIT_DATE for c in closed):
        print(f"SKIP: {t} sale dated {EXIT_DATE} already in closedTrades.")
    else:
        todo[t] = s
if not todo:
    print("ABORT: all sales already recorded. Nothing to do.")
    sys.exit(0)

# --- 1. closedTrades entries (name taken from the live position record) ---
pos_by_ticker = {p.get('ticker'): p for p in positions}
next_id = max([c.get('id', 0) for c in closed] or [0]) + 1
new_entries = []
for t, s in todo.items():
    pos = pos_by_ticker.get(t)
    new_entries.append({
        'id': next_id,
        'ticker': t,
        'name': (pos or {}).get('name', t),
        'quantity': s['qty'],
        'entryPrice': s['entry'],
        'entryDate': s['entryDate'],
        'exitPrice': s['exit'],
        'exitDate': EXIT_DATE,
    })
    next_id += 1
new_closed = closed + new_entries

# --- 2. positions: remove sold tickers ---
new_positions = [p for p in positions if p.get('ticker') not in todo]
removed = [t for t in todo if t in pos_by_ticker]

# --- 3. priceCache: drop stale keys ---
dropped_keys = [k for k in STALE_CACHE_KEYS if k in price_cache]
for k in dropped_keys:
    price_cache.pop(k)

# --- 4. Patch snapshots ---
new_snapshots = []
preview = []

for s in snapshots:
    d = s.get('date')
    if d not in PREV_CLOSES:
        new_snapshots.append(s)
        continue

    pac_old = s.get('positionsAtClose') or []
    present = [t for t in todo if any(p.get('ticker') == t for p in pac_old)]
    if not present:
        new_snapshots.append(s)
        continue

    old = {k: s.get(k) for k in ('positionCount', 'dailyPnL', 'portfolioValue',
                                 'capitalEngaged', 'unrealizedPnL', 'realizedPnL')}
    snap = dict(s)

    new_pac = [p for p in pac_old if p.get('ticker') not in todo]
    snap['positionsAtClose'] = new_pac
    cp = dict(s.get('closingPrices') or {})
    stored_closes = {t: cp.get(t) for t in present}
    for t in present:
        cp.pop(t, None)
    snap['closingPrices'] = cp

    # recompute value fields from the resulting pac (invariant-safe)
    snap['portfolioValue'] = round(sum(p['closingPrice'] * p['quantity'] for p in new_pac), 2)
    snap['capitalEngaged'] = round(sum(p['entryPrice'] * p['quantity'] for p in new_pac), 2)
    snap['unrealizedPnL']  = round(snap['portfolioValue'] - snap['capitalEngaged'], 2)
    snap['positionCount']  = len(new_pac)

    # dailyPnL: subtract per-ticker held-legs
    leg_total = 0.0
    leg_detail = []
    for t in present:
        leg = (stored_closes[t] - PREV_CLOSES[d][t]) * todo[t]['qty']
        leg_total += leg
        leg_detail.append(f"{t} ({stored_closes[t]}-{PREV_CLOSES[d][t]})x{todo[t]['qty']}={leg:+.0f}")
    snap['dailyPnL'] = round((s.get('dailyPnL') or 0) - leg_total, 2)

    # realizedPnL: cumulative add for the tickers being processed
    realized_add = round(sum((todo[t]['exit'] - todo[t]['entry']) * todo[t]['qty'] for t in present), 2)
    snap['realizedPnL'] = round((s.get('realizedPnL') or 0) + realized_add, 2)

    new_snapshots.append(snap)
    new = {k: snap.get(k) for k in old}
    preview.append((d, old, new, leg_detail, leg_total))

# --- Preview ---
print("=== closedTrades ===")
for e in new_entries:
    r = round((e['exitPrice'] - e['entryPrice']) * e['quantity'], 2)
    print(f"  append id={e['id']}: {e['ticker']} ({e['name']}) {e['quantity']} sh "
          f"@ entry {e['entryPrice']} -> exit {e['exitPrice']} on {EXIT_DATE}  (realized {r:+.0f})")
print(f"  total realized delta: {REALIZED_TOTAL:+.0f}")

print(f"\n=== positions: {len(positions)} -> {len(new_positions)} (removed {removed}) ===")
print(f"\n=== priceCache: dropped {dropped_keys} ===")

print("\n=== snapshots (value fields recomputed from pac; dailyPnL -= legs) ===")
for d, old, new, detail, leg_total in preview:
    print(f"  {d}   legs removed: {'; '.join(detail)}  (total {leg_total:+.0f})")
    for k in old:
        print(f"    {k:16s} {old[k]}  ->  {new[k]}")
if not preview:
    print("  (no affected snapshots found)")

if not APPLY:
    print("\n[DRY-RUN] No write. Re-run with --apply to commit.")
    sys.exit(0)

ref.update({
    'closedTrades': new_closed,
    'positions':    new_positions,
    'priceCache':   price_cache,
    'snapshots':    new_snapshots,
    'lastUpdated':  firestore.SERVER_TIMESTAMP,
})
print("\n[APPLIED] Firestore updated.")

# --- Verify ---
after = ref.get().to_dict()
for t in todo:
    still_open = any(p.get('ticker') == t for p in after.get('positions', []))
    ct = any(c.get('ticker') == t and c.get('exitDate') == EXIT_DATE
             for c in after.get('closedTrades', []))
    in_cache = t in (after.get('priceCache') or {})
    print(f"[VERIFY] {t}: still_open={still_open} (expect False)  "
          f"closedTrade={ct} (expect True)  in_priceCache={in_cache} (expect False)")
print(f"[VERIFY] stray '177.HK' in priceCache: {'177.HK' in (after.get('priceCache') or {})} (expect False)")
for s in after.get('snapshots', []):
    if s.get('date') in PREV_CLOSES:
        pac = s.get('positionsAtClose') or []
        has = any(p.get('ticker') in SALES for p in pac)
        pv_chk = round(sum(p['closingPrice']*p['quantity'] for p in pac), 2)
        inv = round(s['portfolioValue'] - s['capitalEngaged'], 2)
        print(f"[VERIFY] {s['date']}  posCount={s.get('positionCount')}(len pac {len(pac)}) "
              f"dailyPnL={s.get('dailyPnL')} pv={s.get('portfolioValue')}(Σ {pv_chk}) "
              f"unreal={s.get('unrealizedPnL')}(pv-cap {inv}) realized={s.get('realizedPnL')} "
              f"sold_in_pac={has}")
