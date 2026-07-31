#!/usr/bin/env python3
"""
verify-jun8-full.py

The cron uses tv_change_abs × qty (i.e. prev-trading-day change, not prev-snapshot change).
For Jun 8 (Monday), prevTradingDay = Jun 5 (Friday). No Jun 5 snapshot exists.
This script:
  1. Fetches Jun 4 and Jun 5 closes for all held tickers via yfinance
  2. Recomputes Jun 8 dailyPnL correctly (using Jun 5 as prevClose)
  3. Isolates 1308's actual contribution on Jun 8
  4. Shows whether my patch was correct
  5. Also verifies Jun 9 (verifiable via stored Jun 8 closes)
"""
import sys
import firebase_admin
from firebase_admin import credentials, firestore
import yfinance as yf
from datetime import date

CRED = 'hk-portfolio-v2/hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json'
DOC_ID  = 'cNcZwUx3nQMV96TbB1kSkQ62u8U2'

TICKER_1308 = '1308.HK'
QTY_1308    = 6000
ENTRY_1308  = 34.92

cred = credentials.Certificate(CRED)
firebase_admin.initialize_app(cred)
db  = firestore.client()
ref = db.collection('portfolios').document(DOC_ID)
doc = ref.get().to_dict()

snaps = {s['date']: s for s in doc.get('snapshots', []) if s.get('date')}

jun3 = snaps.get('2026-06-03', {})
jun8 = snaps.get('2026-06-08', {})
jun9 = snaps.get('2026-06-09', {})

jun3_closes = jun3.get('closingPrices', {})
jun8_closes = jun8.get('closingPrices', {})
jun9_closes = jun9.get('closingPrices', {})

jun8_pac = {p['ticker']: p for p in (jun8.get('positionsAtClose') or [])}
jun9_pac = {p['ticker']: p for p in (jun9.get('positionsAtClose') or [])}

# All tickers that were in positions on Jun 8 (including 1308 before patch, now 13)
# 1308 was held by the cron on Jun 8 even though already sold
all_tickers_jun8 = list(jun8_closes.keys()) + [TICKER_1308]

# --- 1. Fetch Jun 4 + Jun 5 closes via yfinance ---
print("Fetching Jun 4-5 closes via yfinance (may take 20-30s)...")
jun5_closes = {}
jun4_closes = {}
yf_errors   = []
for ticker in set(all_tickers_jun8):
    try:
        t = yf.Ticker(ticker)
        hist = t.history(start='2026-06-03', end='2026-06-09')
        if hist.empty:
            yf_errors.append(ticker)
            continue
        closes = {str(d.date()): round(float(c), 4)
                  for d, c in zip(hist.index, hist['Close'])}
        if '2026-06-05' in closes:
            jun5_closes[ticker] = closes['2026-06-05']
        if '2026-06-04' in closes:
            jun4_closes[ticker] = closes['2026-06-04']
    except Exception as e:
        yf_errors.append(f"{ticker}:{e}")

print(f"  Fetched Jun 5 close for {len(jun5_closes)}/{len(set(all_tickers_jun8))} tickers")
if yf_errors:
    print(f"  Errors: {yf_errors}")

# --- 2. Recompute Jun 8 dailyPnL using Jun 5 as prevClose ---
print("\n=== Jun 8 recomputed (Jun 5 prevClose, all 14 tickers incl 1308) ===")
total_with_1308 = 0.0
total_without_1308 = 0.0
contrib_1308 = None

all_tickers_in_cron = list(jun8_closes.keys()) + [TICKER_1308]

for ticker in sorted(set(all_tickers_in_cron)):
    close_jun8 = jun8_closes.get(ticker) or (35.30 if ticker == TICKER_1308 else None)
    prev_close  = jun5_closes.get(ticker) or jun3_closes.get(ticker)
    pac = jun8_pac.get(ticker, {})
    qty = pac.get('quantity', 0) if ticker != TICKER_1308 else QTY_1308

    if close_jun8 is None or prev_close is None or qty == 0:
        print(f"  {ticker:12s}  SKIP (close={close_jun8} prev={prev_close} qty={qty})")
        continue

    contrib = round((close_jun8 - prev_close) * qty, 2)
    src = 'jun5' if ticker in jun5_closes else 'jun3-fallback'
    print(f"  {ticker:12s}  prev={prev_close:.2f} ({src})  close={close_jun8:.2f}  qty={qty}  contrib={contrib:+.2f}")
    total_with_1308 += contrib
    if ticker != TICKER_1308:
        total_without_1308 += contrib
    else:
        contrib_1308 = contrib

print(f"\n  sum WITH 1308    : {round(total_with_1308, 2)}  (original cron value should be: -9654)")
print(f"  contribution 1308: {round(contrib_1308, 2) if contrib_1308 is not None else 'n/a'}")
print(f"  sum WITHOUT 1308 : {round(total_without_1308, 2)}  (correct Jun 8 dailyPnL)")
print(f"  stored Jun 8 PnL : {jun8.get('dailyPnL')}  (after my patch: was -9654)")
drift_jun8 = round(total_without_1308 - (jun8.get('dailyPnL') or 0), 2)
print(f"  DRIFT            : {drift_jun8}")

# --- 3. Verify Jun 9 using Jun 8 closes as prevClose ---
print("\n=== Jun 9 recomputed (Jun 8 prevClose, 13 tickers) ===")
total_jun9 = 0.0
for ticker in sorted(jun9_closes.keys()):
    close_jun9 = jun9_closes[ticker]
    prev_close  = jun8_closes.get(ticker)
    pac = jun9_pac.get(ticker, {})
    qty = pac.get('quantity', 0)

    if prev_close is None or qty == 0:
        print(f"  {ticker:12s}  SKIP")
        continue

    contrib = round((close_jun9 - prev_close) * qty, 2)
    print(f"  {ticker:12s}  prev={prev_close:.2f}  close={close_jun9:.2f}  qty={qty}  contrib={contrib:+.2f}")
    total_jun9 += contrib

print(f"\n  RECOMPUTED total : {round(total_jun9, 2)}")
print(f"  STORED Jun 9 PnL : {jun9.get('dailyPnL')}")
drift_jun9 = round(total_jun9 - (jun9.get('dailyPnL') or 0), 2)
print(f"  DRIFT            : {drift_jun9}  (expect ~0)")
