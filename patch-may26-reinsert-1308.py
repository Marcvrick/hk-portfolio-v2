#!/usr/bin/env python3
"""
patch-may26-reinsert-1308.py
Re-inserts 1308.HK SITC International into the marccharnal portfolio after
the browser silently overwrote the original May 22 admin-script insert.

What this writes:
  - positions[]: append 1308.HK (qty 6000, entryPrice 34.92, entryDate 2026-05-21)
  - priceCache["1308.HK"]: backfill with May 22 close 34.32 / prevClose 33.90
  - snapshots[2026-05-21]: posCount 13->14, pv 783648->987048, dailyPnL -6985->-13105,
    append 1308 to positionsAtClose + closingPrices (close 33.90)
  - snapshots[2026-05-22]: posCount 13->14, pv 795704->1001624, dailyPnL 12056->14576,
    append 1308 to positionsAtClose + closingPrices (close 34.32)

Source of historical prices: README.md (May 22 cron settled values that were
overwritten by the browser).

Idempotent: refuses to run if 1308.HK is already in positions.
"""
import firebase_admin
from firebase_admin import credentials, firestore
import json
import sys

CRED = 'hk-portfolio-v2/hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json'
DOC_ID = 'cNcZwUx3nQMV96TbB1kSkQ62u8U2'

# 1308.HK specifics (from README + Firestore inspection)
TICKER = '1308.HK'
NAME = 'SITC International'
QUANTITY = 6000
ENTRY_PRICE = 34.92
ENTRY_DATE = '2026-05-21'
MAY21_CLOSE = 33.90
MAY22_CLOSE = 34.32

cred = credentials.Certificate(CRED)
firebase_admin.initialize_app(cred)
db = firestore.client()
ref = db.collection('portfolios').document(DOC_ID)
doc = ref.get().to_dict()

# Idempotency check
positions = doc.get('positions', [])
if any(p.get('ticker') == TICKER for p in positions):
    print(f"ABORT: {TICKER} already in positions. Nothing to do.")
    sys.exit(0)

# 1. Build the position object
new_position = {
    'id': 1779260000000,  # next-in-sequence integer, matches other recent IDs
    'ticker': TICKER,
    'name': NAME,
    'quantity': QUANTITY,
    'entryPrice': ENTRY_PRICE,
    'entryDate': ENTRY_DATE,
    'currentPrice': MAY22_CLOSE,
}
new_positions = positions + [new_position]

# 2. priceCache entry
from datetime import datetime, timezone, timedelta
HKT = timezone(timedelta(hours=8))
change_abs = round(MAY22_CLOSE - MAY21_CLOSE, 4)
change_pct = round((change_abs / MAY21_CLOSE) * 100, 4)

price_cache = dict(doc.get('priceCache', {}))
price_cache[TICKER] = {
    'success': True,
    'price': MAY22_CLOSE,
    'previousClose': MAY21_CLOSE,
    'change': change_abs,
    'changePercent': change_pct,
    'currency': 'HKD',
    'lastUpdated': datetime.now(HKT).isoformat(),
}

# 3. Patch snapshots
snapshots = list(doc.get('snapshots', []))
entry_mv = ENTRY_PRICE * QUANTITY  # 209,520

def make_pac_entry(close_price):
    pnl = round((close_price - ENTRY_PRICE) * QUANTITY, 2)
    return {
        'ticker': TICKER,
        'name': NAME,
        'quantity': QUANTITY,
        'entryPrice': ENTRY_PRICE,
        'entryDate': ENTRY_DATE,
        'closingPrice': close_price,
        'marketValue': round(close_price * QUANTITY, 2),
        'pnl': pnl,
        'pnlPercent': round((pnl / entry_mv) * 100, 4),
    }

def patch_snapshot(snap, close_price, prior_close):
    """Add 1308 to one snapshot; mutates and returns."""
    snap = dict(snap)
    snap['positionCount'] = snap.get('positionCount', 0) + 1
    snap['portfolioValue'] = round(snap.get('portfolioValue', 0) + close_price * QUANTITY, 2)
    snap['capitalEngaged'] = round(snap.get('capitalEngaged', 0) + entry_mv, 2)
    snap['unrealizedPnL'] = round(snap['portfolioValue'] - snap['capitalEngaged'], 2)
    # dailyPnL contribution: entry day uses (close - entryPrice), subsequent days use (close - prior_close)
    daily_contrib = (close_price - prior_close) * QUANTITY
    snap['dailyPnL'] = round(snap.get('dailyPnL', 0) + daily_contrib, 2)
    closing_prices = dict(snap.get('closingPrices') or {})
    closing_prices[TICKER] = close_price
    snap['closingPrices'] = closing_prices
    pac = list(snap.get('positionsAtClose') or [])
    pac.append(make_pac_entry(close_price))
    snap['positionsAtClose'] = pac
    return snap

patched_snapshots = []
for s in snapshots:
    d = s.get('date')
    if d == '2026-05-21':
        # Entry day: prior_close = entryPrice (so daily contrib = (close - entryPrice) * qty = -6120)
        patched_snapshots.append(patch_snapshot(s, MAY21_CLOSE, ENTRY_PRICE))
    elif d == '2026-05-22':
        # Day after entry: prior_close = May 21 close
        patched_snapshots.append(patch_snapshot(s, MAY22_CLOSE, MAY21_CLOSE))
    else:
        patched_snapshots.append(s)

# 4. Print preview
def fmt_snap(s):
    return (f"  {s.get('date')}: posCount={s.get('positionCount')} "
            f"pv={s.get('portfolioValue'):,} dailyPnL={s.get('dailyPnL')}")

print("=== Preview ===")
print(f"positions: {len(positions)} -> {len(new_positions)} (added {TICKER})")
print(f"priceCache: added entry for {TICKER}: price={MAY22_CLOSE} prevClose={MAY21_CLOSE}")
print("snapshots patched:")
for s in patched_snapshots:
    if s.get('date') in ('2026-05-21', '2026-05-22'):
        print(fmt_snap(s))

# 5. Write
if '--dry-run' in sys.argv:
    print("\nDRY RUN — no write")
    sys.exit(0)

ref.update({
    'positions': new_positions,
    'priceCache': price_cache,
    'snapshots': patched_snapshots,
    'lastUpdated': firestore.SERVER_TIMESTAMP,
})
print("\nWrote to Firestore.")
