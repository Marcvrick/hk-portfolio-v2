#!/usr/bin/env python3
"""
patch-jun28-restore-wuxi-xiaomi.py

Restore the two positions + the WuXi partial-sale realized trade wiped by a
stale-tab full-document overwrite (see wiki incidents 2026-06-28).

Ground truth from Dany (2026-06-28):
  - WuXi 2359.HK : BUY  800 @ 128.70 on 2026-06-22
  - WuXi 2359.HK : SELL 500 @ 148.20 on 2026-06-24  -> 300 remaining @ 128.70
                   (NB: wiki incident said 2026-06-25; Dany's word = 24. CONFIRM.)
  - Xiaomi 1810.HK : BUY 2400 @ 22.90  (entryDate PLACEHOLDER 2026-06-23 — CONFIRM)

Restores (Stage A — live view + realized profit):
  1. open position 2359.HK : 300 @ 128.70
  2. open position 1810.HK : 2400 @ 22.90
  3. closedTrade  2359.HK  : qty 500, entry 128.70, exit 148.20, exit 2026-06-24
       -> realized +9,750
  4. snapshots dated >= 2026-06-24 with realizedPnL == 9979 -> 19729 (+9750)

NOT done here (Stage B, after dates confirmed): rebuild Jun 22-26 positionsAtClose
legs + dailyPnL for these two tickers. dailyPnL tiles for those days stay as-is
until Stage B.

Dry-run by default. --apply to write. Idempotent (aborts if 2359 already present).
"""
import sys
import firebase_admin
from firebase_admin import credentials, firestore

CRED = 'hk-portfolio-v2/hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json'
DOC_ID = 'cNcZwUx3nQMV96TbB1kSkQ62u8U2'
APPLY = '--apply' in sys.argv

WUXI_BUY_DATE = '2026-06-22'
WUXI_SELL_DATE = '2026-06-25'    # Dany confirmed 2026-06-28: sold on the 25th
XIAOMI_BUY_DATE = '2026-06-24'   # Dany confirmed 2026-06-28: bought on the 24th
# 6821.HK correction (Dany confirmed: 500 @ 111.70 on 26/06; app wrongly had 200 @ 110.70)
SIX821_QTY, SIX821_ENTRY = 500, 111.70
WUXI_EXIT, WUXI_ENTRY = 148.20, 128.70
WUXI_SOLD_QTY, WUXI_REMAIN_QTY = 500, 300
XIAOMI_QTY, XIAOMI_ENTRY = 2400, 22.90
WUXI_REALIZED = round((WUXI_EXIT - WUXI_ENTRY) * WUXI_SOLD_QTY, 2)  # 9750.0

firebase_admin.initialize_app(credentials.Certificate(CRED))
db = firestore.client()
ref = db.collection('portfolios').document(DOC_ID)
doc = ref.get().to_dict()
positions = doc.get('positions', [])
closed = doc.get('closedTrades', [])
snapshots = doc.get('snapshots', [])

# ---- idempotency ----
if any(p.get('ticker') == '2359.HK' for p in positions):
    print("ABORT: 2359.HK already in positions — not re-running."); sys.exit(1)
if any(c.get('ticker') == '2359.HK' for c in closed):
    print("ABORT: 2359.HK already in closedTrades — not re-running."); sys.exit(1)

existing_ids = {p.get('id') for p in positions} | {c.get('id') for c in closed}
def new_id(seed):
    while seed in existing_ids:
        seed += 1
    existing_ids.add(seed)
    return seed

wuxi_pos = {'ticker': '2359.HK', 'name': 'WuXi AppTec', 'quantity': WUXI_REMAIN_QTY,
            'entryPrice': WUXI_ENTRY, 'entryDate': WUXI_BUY_DATE,
            'currentPrice': 145.4, 'id': new_id(1782600000001)}
xiaomi_pos = {'ticker': '1810.HK', 'name': 'Xiaomi', 'quantity': XIAOMI_QTY,
              'entryPrice': XIAOMI_ENTRY, 'entryDate': XIAOMI_BUY_DATE,
              'currentPrice': 21.42, 'id': new_id(1782600000002)}
wuxi_trade = {'ticker': '2359.HK', 'name': 'WuXi AppTec', 'quantity': WUXI_SOLD_QTY,
              'entryPrice': WUXI_ENTRY, 'exitPrice': WUXI_EXIT,
              'entryDate': WUXI_BUY_DATE, 'exitDate': WUXI_SELL_DATE,
              'id': new_id(1782600000003)}

# ---- 6821.HK correction (existing position has wrong qty + entry) ----
six = next((p for p in positions if p.get('ticker') == '6821.HK'), None)
print("=== 6821.HK correction ===")
if six is None:
    print("  WARN: 6821.HK not in positions — skipping correction.")
else:
    print(f"  before: qty={six.get('quantity')} entry={six.get('entryPrice')}")
    print(f"  after : qty={SIX821_QTY} entry={SIX821_ENTRY}")

print("=== POSITIONS to add ===")
print(" ", wuxi_pos)
print(" ", xiaomi_pos)
print("=== CLOSEDTRADE to add ===")
print(f"  {wuxi_trade}  -> realized +{WUXI_REALIZED}")

print("\n=== SNAPSHOT realizedPnL updates (>= {} & ==9979) ===".format(WUXI_SELL_DATE))
snap_touch = []
for s in snapshots:
    if s.get('date', '') >= WUXI_SELL_DATE and abs((s.get('realizedPnL') or 0) - 9979) < 1:
        snap_touch.append(s)
        print(f"  {s['date']}: realizedPnL 9979 -> {9979 + WUXI_REALIZED:.0f}")
if not snap_touch:
    print("  (none matched — check dates/values)")

print(f"\nSummary: +2 positions ({len(positions)} -> {len(positions)+2}), "
      f"+1 closedTrade ({len(closed)} -> {len(closed)+1}), "
      f"{len(snap_touch)} snapshot realizedPnL bumped.")

if not APPLY:
    print("\n[DRY-RUN] No write. Re-run with --apply after Dany confirms dates.")
    sys.exit(0)

positions += [wuxi_pos, xiaomi_pos]
if six is not None:
    six['quantity'] = SIX821_QTY
    six['entryPrice'] = SIX821_ENTRY
closed += [wuxi_trade]
for s in snap_touch:
    s['realizedPnL'] = 9979 + WUXI_REALIZED
ref.update({'positions': positions, 'closedTrades': closed, 'snapshots': snapshots})
print("\n[APPLIED] Firestore updated.")
v = ref.get().to_dict()
print("[VERIFY] open tickers:", ", ".join(sorted(p['ticker'] for p in v['positions'])))
print("[VERIFY] 2359 closedTrade present:", any(c['ticker'] == '2359.HK' for c in v['closedTrades']))
print("[VERIFY] Σ closedTrades realized:",
      round(sum((c['exitPrice'] - c['entryPrice']) * c['quantity'] for c in v['closedTrades']), 0))
