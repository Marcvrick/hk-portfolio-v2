#!/usr/bin/env python3
"""
patch-jun4-1308-sale.py
Record the 1308.HK (SITC International) sale that happened on 2026-06-04 at
HK$34.60 but was never entered in the app.

Current (wrong) state inspected 2026-06-05:
  - 1308.HK still OPEN in positions (qty 6000, entry 34.92, entryDate 2026-05-21)
  - no closedTrades entry for 1308
  - Jun 4 & Jun 5 snapshots still count 1308 as a held position

What this writes:
  - closedTrades[]: append 1308.HK sale (qty 6000, entry 34.92 -> exit 34.60, exitDate 2026-06-04)
  - positions[]: remove 1308.HK
  - priceCache: drop the stale 1308.HK entry
  - snapshots[2026-06-04] (sale day):
        held-leg (34.50-34.80)*6000 = -1800  replaced by
        closed-leg (34.60-34.80)*6000 = -1200   => dailyPnL +600
        realizedPnL += (34.60-34.92)*6000 = -1920
        remove 1308 from positionsAtClose + closingPrices, posCount -1
        portfolioValue -= 34.50*6000, unrealizedPnL -= (34.50-34.92)*6000
  - snapshots[2026-06-05] (today, 1308 no longer held):
        remove 1308 held-leg (35.18-34.50)*6000 = +4080  => dailyPnL -4080
        realizedPnL carries the -1920 (cumulative)
        remove 1308 from positionsAtClose + closingPrices, posCount -1
        portfolioValue -= 35.18*6000, unrealizedPnL -= (35.18-34.92)*6000

Idempotent: aborts if a 1308.HK closedTrade dated 2026-06-04 already exists.

Usage:
  python3 patch-jun4-1308-sale.py            # dry-run (default)
  python3 patch-jun4-1308-sale.py --apply    # write to Firestore
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

JUN3_CLOSE = 34.80   # prior close for the sale-day session move
JUN4_CLOSE = 34.50   # held close that is being removed from Jun 4 snapshot
JUN5_CLOSE = 35.18   # held close that is being removed from Jun 5 snapshot

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
realized_delta = round((EXIT_PRICE - ENTRY_PRICE) * QTY, 2)  # -1920

# --- 2. positions: remove 1308 ---
new_positions = [p for p in positions if p.get('ticker') != TICKER]
removed_from_positions = len(positions) - len(new_positions)

# --- 3. priceCache: drop stale 1308 ---
price_cache.pop(TICKER, None)

# --- 4. snapshot patchers ---
def strip_1308(snap):
    """Remove 1308 from positionsAtClose + closingPrices, posCount -1. Returns (new_snap, found)."""
    snap = dict(snap)
    pac = list(snap.get('positionsAtClose') or [])
    found = any(p.get('ticker') == TICKER for p in pac)
    snap['positionsAtClose'] = [p for p in pac if p.get('ticker') != TICKER]
    cp = dict(snap.get('closingPrices') or {})
    cp.pop(TICKER, None)
    snap['closingPrices'] = cp
    if found:
        snap['positionCount'] = snap.get('positionCount', 0) - 1
    return snap, found

new_snapshots = []
preview = []
for s in snapshots:
    d = s.get('date')
    if d == EXIT_DATE:
        old = {k: s.get(k) for k in ('positionCount','dailyPnL','portfolioValue','unrealizedPnL','realizedPnL')}
        snap, _ = strip_1308(s)
        # dailyPnL: swap held-leg for closed-leg
        held_leg = (JUN4_CLOSE - JUN3_CLOSE) * QTY      # -1800
        closed_leg = (EXIT_PRICE - JUN3_CLOSE) * QTY    # -1200
        snap['dailyPnL'] = round(s.get('dailyPnL', 0) - held_leg + closed_leg, 2)
        snap['portfolioValue'] = round(s.get('portfolioValue', 0) - JUN4_CLOSE * QTY, 2)
        snap['unrealizedPnL'] = round(s.get('unrealizedPnL', 0) - (JUN4_CLOSE - ENTRY_PRICE) * QTY, 2)
        snap['realizedPnL'] = round((s.get('realizedPnL', 0) or 0) + realized_delta, 2)
        new_snapshots.append(snap)
        new = {k: snap.get(k) for k in old}
        preview.append((d, old, new, 'held-leg -1800 -> closed-leg -1200'))
    elif d == '2026-06-05':
        old = {k: s.get(k) for k in ('positionCount','dailyPnL','portfolioValue','unrealizedPnL','realizedPnL')}
        snap, _ = strip_1308(s)
        held_leg = (JUN5_CLOSE - JUN4_CLOSE) * QTY      # +4080
        snap['dailyPnL'] = round(s.get('dailyPnL', 0) - held_leg, 2)
        snap['portfolioValue'] = round(s.get('portfolioValue', 0) - JUN5_CLOSE * QTY, 2)
        snap['unrealizedPnL'] = round(s.get('unrealizedPnL', 0) - (JUN5_CLOSE - ENTRY_PRICE) * QTY, 2)
        snap['realizedPnL'] = round((s.get('realizedPnL', 0) or 0) + realized_delta, 2)
        new_snapshots.append(snap)
        new = {k: snap.get(k) for k in old}
        preview.append((d, old, new, 'remove held-leg +4080'))
    else:
        new_snapshots.append(s)

# --- Preview ---
print("=== closedTrades ===")
print(f"  append id={next_id}: {TICKER} {QTY} @ {ENTRY_PRICE} -> {EXIT_PRICE} on {EXIT_DATE} "
      f"(realized {realized_delta})")
print(f"=== positions: {len(positions)} -> {len(new_positions)} (removed {removed_from_positions} x {TICKER}) ===")
print(f"=== priceCache: dropped {TICKER} ===")
print("=== snapshots ===")
for d, old, new, note in preview:
    print(f"  {d}  ({note})")
    for k in old:
        print(f"    {k:16s} {old[k]}  ->  {new[k]}")

if not APPLY:
    print("\n[DRY-RUN] No write. Re-run with --apply to commit.")
    sys.exit(0)

ref.update({
    'closedTrades': new_closed,
    'positions': new_positions,
    'priceCache': price_cache,
    'snapshots': new_snapshots,
    'lastUpdated': firestore.SERVER_TIMESTAMP,
})
print("\n[APPLIED] Firestore updated.")

# --- Verify ---
after = ref.get().to_dict()
still_open = any(p.get('ticker') == TICKER for p in after.get('positions', []))
ct = next((c for c in after.get('closedTrades', []) if c.get('ticker') == TICKER and c.get('exitDate') == EXIT_DATE), None)
print(f"[VERIFY] 1308 still open: {still_open}  (expect False)")
print(f"[VERIFY] closedTrade present: {ct is not None}")
for s in after.get('snapshots', []):
    if s.get('date') in (EXIT_DATE, '2026-06-05'):
        has = any(p.get('ticker') == TICKER for p in (s.get('positionsAtClose') or []))
        print(f"[VERIFY] {s['date']} posCount={s.get('positionCount')} dailyPnL={s.get('dailyPnL')} "
              f"pv={s.get('portfolioValue')} realizedPnL={s.get('realizedPnL')} 1308_in_pac={has}")
