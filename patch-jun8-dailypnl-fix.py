#!/usr/bin/env python3
"""
patch-jun8-dailypnl-fix.py

Corrects the Jun 8 dailyPnL which was over-corrected in the 1308 removal patch.

Root cause:
  The original patch subtracted (35.30 - 34.80) * 6000 = 3000 for 1308's held-leg,
  using Jun 3 as prevClose. But the cron uses TradingView change_abs, which reflects
  the prev-TRADING-DAY close. For Jun 8 (Monday), prevTradingDay = Jun 5 (Friday).
  1308's Jun 5 close (verified via yfinance): 34.98
  Correct 1308 contribution: (35.30 - 34.98) * 6000 = +1920
  Amount to have subtracted: 1920 (not 3000)
  Over-subtracted by: 1080

Fix:
  dailyPnL: -12654 + 1080 = -11574
  portfolioValue, unrealizedPnL, positionCount, closingPrices: already correct
  realizedPnL: already correct

Verified:
  Jun 8 recomputed (all 14 tickers, Jun 5 prevClose):  -9654 (matches original cron)
  1308 contribution: +1920
  Correct Jun 8 without 1308: -9654 - 1920 = -11574
  Jun 9 drift: 0 (Jun 9 was correctly patched)

Usage:
  python3 patch-jun8-dailypnl-fix.py           # dry-run
  python3 patch-jun8-dailypnl-fix.py --apply
"""
import sys
import firebase_admin
from firebase_admin import credentials, firestore

CRED   = 'hk-portfolio-v2/hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json'
DOC_ID = 'cNcZwUx3nQMV96TbB1kSkQ62u8U2'

APPLY = '--apply' in sys.argv

cred = credentials.Certificate(CRED)
firebase_admin.initialize_app(cred)
db  = firestore.client()
ref = db.collection('portfolios').document(DOC_ID)
doc = ref.get().to_dict()

snapshots = list(doc.get('snapshots', []))

CORRECT_DAILY_PNL = -11574.0
OVERCORRECTION    =  1080.0  # (3000 - 1920)

new_snapshots = []
patched = False

for s in snapshots:
    if s.get('date') == '2026-06-08':
        old = s.get('dailyPnL')
        s = dict(s)
        s['dailyPnL'] = CORRECT_DAILY_PNL
        print(f"Jun 8 dailyPnL: {old}  ->  {CORRECT_DAILY_PNL}  (adding back overcorrection of {OVERCORRECTION})")
        patched = True
        new_snapshots.append(s)
    else:
        new_snapshots.append(s)

if not patched:
    print("ERROR: Jun 8 snapshot not found.")
    sys.exit(1)

if not APPLY:
    print("[DRY-RUN] No write. Re-run with --apply to commit.")
    sys.exit(0)

ref.update({'snapshots': new_snapshots, 'lastUpdated': firestore.SERVER_TIMESTAMP})
print("[APPLIED] Firestore updated.")

after = ref.get().to_dict()
for s in after.get('snapshots', []):
    if s.get('date') == '2026-06-08':
        print(f"[VERIFY] Jun 8 dailyPnL = {s.get('dailyPnL')}  (expect {CORRECT_DAILY_PNL})")
