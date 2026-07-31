#!/usr/bin/env python3
"""
patch-may29-remove-9988.py
Record the 9988.HK (Alibaba) sale that happened on 2026-05-29 at HK$121.40 but
was never entered in the app. Full position exit (800 shares).

Actual state 2026-06-10 (diagnosed via diagnose-9988*.py):
  - 9988.HK still OPEN in positions (id 1777963042149, qty 800, entry 131,
    entryDate 2026-05-05)
  - no closedTrades entry for 9988
  - cron gap: NO snapshots between 2026-05-28 and 2026-06-02. The sale (May 29)
    falls in that gap, so the first affected snapshot is Jun 3.
  - 4 snapshots wrongly count 9988 as held: Jun 3, Jun 8, Jun 9, Jun 10.

What this writes:
  - closedTrades[]: append 9988.HK sale
      qty 800, entry 131 -> exit 121.40, exitDate 2026-05-29
      realized = (121.40 - 131) * 800 = -7680
  - positions[]: remove 9988.HK
  - priceCache: drop the stale 9988.HK entry
  - For each affected snapshot:
      * remove 9988 from positionsAtClose + closingPrices
      * RECOMPUTE portfolioValue / capitalEngaged / unrealizedPnL / positionCount
        from the resulting positionsAtClose (enforces invariants; this also
        repairs Jun 8's stale capitalEngaged left behind by patch-jun9-remove-1308,
        which removed 1308 from pac but never reduced capitalEngaged).
      * dailyPnL -= 9988 held-leg  (leg = (close_date - close_prevTradingDay)*qty,
        prevTradingDay close from yfinance for gap days Jun 3/Jun 8, from the prior
        snapshot for Jun 9/Jun 10)
      * realizedPnL += -7680  (sale May 29 precedes all four snapshots)

9988 held-legs removed from dailyPnL:
  Jun 3 : (124.3 - 130.9)*800 = -5280   (prevTD Jun 2 close 130.9, yfinance, gap)
  Jun 8 : (118.8 - 122.4)*800 = -2880   (prevTD Jun 5 close 122.4, yfinance, gap)
  Jun 9 : (117.1 - 118.8)*800 = -1360   (prevTD Jun 8 close 118.8, snapshot)
  Jun 10: (111.8 - 117.1)*800 = -4240   (prevTD Jun 9 close 117.1, snapshot)

CAVEAT (Jun 3): the Jun 3 snapshot stored close 124.3 has no priceProvenance and
disagrees with yfinance raw (126.6). The leg uses the snapshot's own stored close
(what the cron baked in) paired with yfinance Jun 2 (130.9). If TradingView's Jun 2
differed from yfinance, the Jun 3 leg carries small uncertainty. Only Jun 3's
session-P&L display is affected; all value/realized/unrealized fields are exact.

Idempotent: aborts if a 9988.HK closedTrade dated 2026-05-29 already exists.

Usage:
  python3 patch-may29-remove-9988.py            # dry-run (default)
  python3 patch-may29-remove-9988.py --apply     # write to Firestore
"""
import sys
import firebase_admin
from firebase_admin import credentials, firestore

CRED = 'hk-portfolio-v2/hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json'
DOC_ID = 'cNcZwUx3nQMV96TbB1kSkQ62u8U2'

TICKER = '9988.HK'
NAME = 'Alibaba'
QTY = 800
ENTRY_PRICE = 131
ENTRY_DATE = '2026-05-05'
EXIT_PRICE = 121.40
EXIT_DATE = '2026-05-29'

REALIZED_DELTA = round((EXIT_PRICE - ENTRY_PRICE) * QTY, 2)  # -7680.0

# 9988 held-leg to remove from each snapshot's dailyPnL: (close_date - prevTD_close) * qty
LEGS = {
    '2026-06-03': round((124.3 - 130.9) * QTY, 2),   # -5280.0  (prevTD Jun 2, yfinance)
    '2026-06-08': round((118.8 - 122.4) * QTY, 2),   # -2880.0  (prevTD Jun 5, yfinance)
    '2026-06-09': round((117.1 - 118.8) * QTY, 2),   # -1360.0  (prevTD Jun 8, snapshot)
    '2026-06-10': round((111.8 - 117.1) * QTY, 2),   # -4240.0  (prevTD Jun 9, snapshot)
}

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

# --- Idempotency ---
if any(c.get('ticker') == TICKER and c.get('exitDate') == EXIT_DATE for c in closed):
    print(f"ABORT: {TICKER} sale dated {EXIT_DATE} already in closedTrades. Nothing to do.")
    sys.exit(0)

# --- 1. closedTrades entry ---
next_id = max([c.get('id', 0) for c in closed] or [0]) + 1
new_closed_entry = {
    'id': next_id,
    'ticker': TICKER,
    'name': NAME,
    'quantity': QTY,
    'entryPrice': ENTRY_PRICE,
    'entryDate': ENTRY_DATE,
    'exitPrice': EXIT_PRICE,
    'exitDate': EXIT_DATE,
}
new_closed = closed + [new_closed_entry]

# --- 2. positions: remove 9988 ---
new_positions = [p for p in positions if p.get('ticker') != TICKER]
removed_count = len(positions) - len(new_positions)

# --- 3. priceCache: drop stale 9988 ---
had_cache = TICKER in price_cache
price_cache.pop(TICKER, None)

# --- 4. Patch snapshots ---
new_snapshots = []
preview = []

for s in snapshots:
    d = s.get('date')
    if d not in LEGS:
        new_snapshots.append(s)
        continue

    has = any(p.get('ticker') == TICKER for p in (s.get('positionsAtClose') or []))
    if not has:
        new_snapshots.append(s)
        continue

    old = {k: s.get(k) for k in ('positionCount', 'dailyPnL', 'portfolioValue',
                                 'capitalEngaged', 'unrealizedPnL', 'realizedPnL')}
    snap = dict(s)

    # remove 9988 from pac + closingPrices
    new_pac = [p for p in (s.get('positionsAtClose') or []) if p.get('ticker') != TICKER]
    snap['positionsAtClose'] = new_pac
    cp = dict(s.get('closingPrices') or {})
    cp.pop(TICKER, None)
    snap['closingPrices'] = cp

    # recompute value fields from the resulting pac (enforces invariants)
    snap['portfolioValue'] = round(sum(p['closingPrice'] * p['quantity'] for p in new_pac), 2)
    snap['capitalEngaged'] = round(sum(p['entryPrice'] * p['quantity'] for p in new_pac), 2)
    snap['unrealizedPnL']  = round(snap['portfolioValue'] - snap['capitalEngaged'], 2)
    snap['positionCount']  = len(new_pac)

    # dailyPnL: subtract the 9988 held-leg (immutability rule: do not rebuild from closes)
    leg = LEGS[d]
    snap['dailyPnL'] = round((s.get('dailyPnL') or 0) - leg, 2)

    # realizedPnL: cumulative add (sale precedes this snapshot)
    snap['realizedPnL'] = round((s.get('realizedPnL') or 0) + REALIZED_DELTA, 2)

    new_snapshots.append(snap)
    new = {k: snap.get(k) for k in old}
    preview.append((d, old, new, leg))

# --- Preview ---
print("=== closedTrades ===")
print(f"  append id={next_id}: {TICKER} ({NAME}) {QTY} sh @ entry {ENTRY_PRICE} "
      f"-> exit {EXIT_PRICE} on {EXIT_DATE}  (realized {REALIZED_DELTA})")
print(f"\n=== positions: {len(positions)} -> {len(new_positions)} "
      f"(removed {removed_count}x {TICKER}) ===")
print(f"\n=== priceCache: {'dropped 9988.HK' if had_cache else 'no 9988 entry'} ===")
print("\n=== snapshots (capEngaged/unrealized recomputed from pac; dailyPnL -= 9988 leg) ===")
for d, old, new, leg in preview:
    print(f"  {d}   9988 dailyPnL leg removed = {leg:+.0f}")
    for k in old:
        print(f"    {k:16s} {old[k]}  ->  {new[k]}")
if not preview:
    print("  (no affected snapshots found — nothing to patch)")

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
still_open = any(p.get('ticker') == TICKER for p in after.get('positions', []))
ct = next((c for c in after.get('closedTrades', [])
           if c.get('ticker') == TICKER and c.get('exitDate') == EXIT_DATE), None)
print(f"[VERIFY] 9988 still open:       {still_open}  (expect False)")
print(f"[VERIFY] closedTrade present:   {ct is not None}  (expect True)")
print(f"[VERIFY] 9988 in priceCache:    {TICKER in (after.get('priceCache') or {})}  (expect False)")
for s in after.get('snapshots', []):
    if s.get('date') in LEGS:
        pac = s.get('positionsAtClose') or []
        has = any(p.get('ticker') == TICKER for p in pac)
        pv_chk = round(sum(p['closingPrice']*p['quantity'] for p in pac), 2)
        inv = round(s['portfolioValue'] - s['capitalEngaged'], 2)
        print(f"[VERIFY] {s['date']}  posCount={s.get('positionCount')}(len pac {len(pac)}) "
              f"dailyPnL={s.get('dailyPnL')} pv={s.get('portfolioValue')}(Σ {pv_chk}) "
              f"capEng={s.get('capitalEngaged')} unreal={s.get('unrealizedPnL')}(pv-cap {inv}) "
              f"realized={s.get('realizedPnL')} 9988_in_pac={has}")
