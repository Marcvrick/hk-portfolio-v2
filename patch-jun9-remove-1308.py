#!/usr/bin/env python3
"""
patch-jun9-remove-1308.py
Record the 1308.HK (SITC International) sale that happened on 2026-06-04 at
HK$34.60 but was never entered in the app.

Actual state 2026-06-09 (diagnosed):
  - 1308.HK still OPEN in positions (qty 6000, entry 34.92, entryDate 2026-05-21)
  - no closedTrades entry for 1308
  - No Jun 4 / Jun 5 snapshots exist (cron likely did not run those days)
  - Jun 8 and Jun 9 snapshots still count 1308 as a held position

What this writes:
  - closedTrades[]: append 1308.HK sale
      qty 6000, entry 34.92 -> exit 34.60, exitDate 2026-06-04
      realized = (34.60 - 34.92) * 6000 = -1920
  - positions[]: remove 1308.HK
  - priceCache: drop the stale 1308.HK entry
  - snapshots[2026-06-08]:
      1308 contribution to dailyPnL was (35.30 - 34.80)*6000 = +3000 -> remove it
      portfolioValue  -= 35.30 * 6000 = 211800
      unrealizedPnL   -= (35.30 - 34.92) * 6000 = +2280
      realizedPnL     += -1920 (sale happened on Jun 4, before this snapshot)
      positionCount   -= 1
      remove 1308 from positionsAtClose + closingPrices
  - snapshots[2026-06-09]:
      1308 contribution to dailyPnL was (33.88 - 35.30)*6000 = -8520 -> remove it
      portfolioValue  -= 33.88 * 6000 = 203280
      unrealizedPnL   -= (33.88 - 34.92) * 6000 = -6240
      realizedPnL     += -1920 (sale happened on Jun 4, before this snapshot)
      positionCount   -= 1
      remove 1308 from positionsAtClose + closingPrices

Idempotent: aborts if a 1308.HK closedTrade dated 2026-06-04 already exists.

Usage:
  python3 patch-jun9-remove-1308.py            # dry-run (default)
  python3 patch-jun9-remove-1308.py --apply    # write to Firestore
"""
import sys
import firebase_admin
from firebase_admin import credentials, firestore

CRED = 'hk-portfolio-v2/hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json'
DOC_ID = 'cNcZwUx3nQMV96TbB1kSkQ62u8U2'

TICKER = '1308.HK'
NAME = 'SITC International'
QTY = 6000
ENTRY_PRICE = 34.92
ENTRY_DATE = '2026-05-21'
EXIT_PRICE = 34.60
EXIT_DATE = '2026-06-04'

JUN3_CLOSE = 34.80   # last known close before the sale (Jun 3 snapshot)
JUN8_CLOSE = 35.30   # Jun 8 snapshot — 1308 wrongly counted as held
JUN9_CLOSE = 33.88   # Jun 9 snapshot — 1308 wrongly counted as held

REALIZED_DELTA = round((EXIT_PRICE - ENTRY_PRICE) * QTY, 2)  # -1920.0

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

# --- 2. positions: remove 1308 ---
new_positions = [p for p in positions if p.get('ticker') != TICKER]
removed_count = len(positions) - len(new_positions)

# --- 3. priceCache: drop stale 1308 ---
price_cache.pop(TICKER, None)

# --- 4. Snapshot helpers ---
def strip_1308_from_snap(snap):
    """Remove 1308 from positionsAtClose + closingPrices; posCount -1."""
    snap = dict(snap)
    pac = list(snap.get('positionsAtClose') or [])
    snap['positionsAtClose'] = [p for p in pac if p.get('ticker') != TICKER]
    cp = dict(snap.get('closingPrices') or {})
    cp.pop(TICKER, None)
    snap['closingPrices'] = cp
    snap['positionCount'] = snap.get('positionCount', 0) - 1
    return snap

# --- 5. Patch snapshots ---
new_snapshots = []
preview = []

for s in snapshots:
    d = s.get('date')

    if d == '2026-06-08':
        old = {k: s.get(k) for k in ('positionCount', 'dailyPnL', 'portfolioValue', 'unrealizedPnL', 'realizedPnL')}
        snap = strip_1308_from_snap(s)
        held_leg_jun8 = (JUN8_CLOSE - JUN3_CLOSE) * QTY           # +3000
        snap['dailyPnL']      = round(s.get('dailyPnL', 0) - held_leg_jun8, 2)
        snap['portfolioValue']= round(s.get('portfolioValue', 0) - JUN8_CLOSE * QTY, 2)
        snap['unrealizedPnL'] = round(s.get('unrealizedPnL', 0) - (JUN8_CLOSE - ENTRY_PRICE) * QTY, 2)
        snap['realizedPnL']   = round((s.get('realizedPnL') or 0) + REALIZED_DELTA, 2)
        new_snapshots.append(snap)
        preview.append((d, old, {k: snap.get(k) for k in old},
                        f'remove held-leg ({JUN8_CLOSE}-{JUN3_CLOSE})*{QTY}={held_leg_jun8:+.0f}'))

    elif d == '2026-06-09':
        old = {k: s.get(k) for k in ('positionCount', 'dailyPnL', 'portfolioValue', 'unrealizedPnL', 'realizedPnL')}
        snap = strip_1308_from_snap(s)
        held_leg_jun9 = (JUN9_CLOSE - JUN8_CLOSE) * QTY           # -8520
        snap['dailyPnL']      = round(s.get('dailyPnL', 0) - held_leg_jun9, 2)
        snap['portfolioValue']= round(s.get('portfolioValue', 0) - JUN9_CLOSE * QTY, 2)
        snap['unrealizedPnL'] = round(s.get('unrealizedPnL', 0) - (JUN9_CLOSE - ENTRY_PRICE) * QTY, 2)
        snap['realizedPnL']   = round((s.get('realizedPnL') or 0) + REALIZED_DELTA, 2)
        new_snapshots.append(snap)
        preview.append((d, old, {k: snap.get(k) for k in old},
                        f'remove held-leg ({JUN9_CLOSE}-{JUN8_CLOSE})*{QTY}={held_leg_jun9:+.0f}'))

    else:
        new_snapshots.append(s)

# --- Preview ---
print("=== closedTrades ===")
print(f"  append id={next_id}: {TICKER} {QTY} shares @ entry {ENTRY_PRICE} -> exit {EXIT_PRICE} "
      f"on {EXIT_DATE}  (realized {REALIZED_DELTA})")

print(f"\n=== positions: {len(positions)} -> {len(new_positions)} (removed {removed_count}x {TICKER}) ===")

print(f"\n=== priceCache: dropped {TICKER} ===")

print("\n=== snapshots ===")
for d, old, new, note in preview:
    print(f"  {d}  ({note})")
    for k in old:
        print(f"    {k:16s}  {old[k]}  ->  {new[k]}")

if not preview:
    print("  (no Jun 8 / Jun 9 snapshots found — nothing to patch)")

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
print(f"[VERIFY] 1308 still open:      {still_open}  (expect False)")
print(f"[VERIFY] closedTrade present:  {ct is not None}  (expect True)")
for s in after.get('snapshots', []):
    if s.get('date') in ('2026-06-08', '2026-06-09'):
        has = any(p.get('ticker') == TICKER for p in (s.get('positionsAtClose') or []))
        print(f"[VERIFY] {s['date']}  posCount={s.get('positionCount')} "
              f"dailyPnL={s.get('dailyPnL')}  pv={s.get('portfolioValue')}  "
              f"realizedPnL={s.get('realizedPnL')}  1308_in_pac={has}")
