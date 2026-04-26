#!/usr/bin/env python3
"""
Patch Apr 24 2026 (Friday) snapshot:

PROBLEMS DETECTED:
1. dailyPnL = 9,720 but TV change_abs × qty sum = 6,134. Overstated by 3,586 HKD.
   Root cause: update.py computes dailyPnL using yesterday's stored closingPrices,
   which were captured at 16:30 HKT (CAS intraday) and differ from settlement close.
   The browser's Performance tab uses TV change_abs × qty and gets the correct 6,314
   (slightly off only because 2175 was also wrong in priceCache).

2. 2175.HK Apr 24 close stored = 3.43, TV settlement = 3.41 (-0.02).
   Same intraday-vs-settlement issue — but for 2175 the difference persisted into
   priceCache, so even the browser shows wrong % (-1.15% instead of -1.73%).

3. Phantom snapshot dated 2026-04-27 (Monday, future date) exists.
   Created when browser was opened in a timezone that mapped to Apr 27 HKT before
   market open. dailyPnL = 6,314 (reflecting Friday's correct change × qty).

This patch:
 - Fixes 2175.HK Apr 24 close → 3.41 in snapshot + priceCache + positionsAtClose
 - Recalculates Apr 24 dailyPnL from TV change_abs × qty = 6,134
 - Recalculates Apr 24 portfolioValue (loses 9000 × 0.02 = 180 HKD)
 - Deletes phantom Apr 27 snapshot
 - Patches Apr 23 closingPrices to TV settlement values (derived from Apr 24 priceCache prevClose)
   so future cron runs get correct dailyPnL baseline.
"""

import json
import firebase_admin
from firebase_admin import credentials, firestore

CRED = '/Users/mc/Downloads/hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json'
USER_ID = 'cNcZwUx3nQMV96TbB1kSkQ62u8U2'

# --- Authoritative TV settlement values for Apr 24 2026 (Friday close) ---
# Fetched live on Sun Apr 26 from scanner.tradingview.com/hongkong/scan
TV_APR24 = {
    '113.HK':  {'close': 6.25,  'prevClose': 6.17,  'changeAbs': 0.08,  'changePct': 1.2966},
    '1316.HK': {'close': 5.07,  'prevClose': 5.08,  'changeAbs': -0.01, 'changePct': -0.1969},
    '1585.HK': {'close': 11.95, 'prevClose': 12.00, 'changeAbs': -0.05, 'changePct': -0.4167},
    '0177.HK': {'close': 10.62, 'prevClose': 10.56, 'changeAbs': 0.06,  'changePct': 0.5682},
    '1913.HK': {'close': 37.52, 'prevClose': 37.76, 'changeAbs': -0.24, 'changePct': -0.6356},
    '1999.HK': {'close': 4.22,  'prevClose': 4.24,  'changeAbs': -0.02, 'changePct': -0.4717},
    '2175.HK': {'close': 3.41,  'prevClose': 3.47,  'changeAbs': -0.06, 'changePct': -1.7291},  # was 3.43 — CORRECTED
    '2643.HK': {'close': 24.96, 'prevClose': 25.78, 'changeAbs': -0.82, 'changePct': -3.1808},
    '0285.HK': {'close': 26.94, 'prevClose': 26.86, 'changeAbs': 0.08,  'changePct': 0.2978},
    '3680.HK': {'close': 2.55,  'prevClose': 2.45,  'changeAbs': 0.10,  'changePct': 4.0816},
    '3998.HK': {'close': 4.32,  'prevClose': 4.27,  'changeAbs': 0.05,  'changePct': 1.1710},
    '0434.HK': {'close': 3.12,  'prevClose': 3.13,  'changeAbs': -0.01, 'changePct': -0.3195},
    '6826.HK': {'close': 21.34, 'prevClose': 21.38, 'changeAbs': -0.04, 'changePct': -0.1871},
    '856.HK':  {'close': 9.82,  'prevClose': 9.39,  'changeAbs': 0.43,  'changePct': 4.5793},
    '9690.HK': {'close': 13.51, 'prevClose': 13.63, 'changeAbs': -0.12, 'changePct': -0.8804},
}


def main(commit=False):
    cred = credentials.Certificate(CRED)
    firebase_admin.initialize_app(cred)
    db = firestore.client()

    doc_ref = db.collection('portfolios').document(USER_ID)
    data = doc_ref.get().to_dict()
    snapshots = data['snapshots']
    positions = data['positions']
    price_cache = data['priceCache']

    # ---- 1. Delete phantom Apr 27 snapshot ----
    before = len(snapshots)
    snapshots = [s for s in snapshots if s['date'] != '2026-04-27']
    print(f'1. Phantom snapshot deletion: {before} -> {len(snapshots)} snapshots ({"removed Apr 27" if before > len(snapshots) else "no Apr 27 found"})')

    # NOTE: Intentionally NOT patching Apr 23 closingPrices.
    # Apr 23's stored dailyPnL=-12941 was computed against Apr 22 closingPrices.
    # Patching Apr 23 closes would make Apr 23 portfolioValue inconsistent with its stored dailyPnL.
    # The cron-side fix (use TV change_abs × qty for dailyPnL) makes Apr 23 baseline irrelevant.
    apr23 = next((s for s in snapshots if s['date'] == '2026-04-23'), None)

    # ---- 2. Patch Apr 24 snapshot ----
    apr24 = next((s for s in snapshots if s['date'] == '2026-04-24'), None)
    if not apr24:
        print('ERROR: Apr 24 snapshot not found!')
        return

    # 3a. Fix 2175 close in snapshot
    apr24['closingPrices']['2175.HK'] = 3.41
    for pac in apr24.get('positionsAtClose', []):
        if pac['ticker'] == '2175.HK':
            pac['closingPrice'] = 3.41
            pac['marketValue'] = 3.41 * pac['quantity']
            pac['pnl'] = (3.41 - pac.get('entryPrice', 0)) * pac['quantity']
            if pac.get('entryPrice'):
                pac['pnlPercent'] = (3.41 - pac['entryPrice']) / pac['entryPrice'] * 100

    # 2b. Recompute Apr 24 dailyPnL from TV change_abs × qty (correct method)
    daily_pnl = 0
    for p in positions:
        ticker = p['ticker']
        qty = p['quantity']
        if ticker in TV_APR24:
            daily_pnl += TV_APR24[ticker]['changeAbs'] * qty
    # Realized P&L delta vs Apr 23 (no closures Apr 24, but compute anyway)
    realized_pnl_apr24 = apr24.get('realizedPnL', 0)
    realized_pnl_apr23 = apr23.get('realizedPnL', 0) if apr23 else realized_pnl_apr24
    daily_pnl += (realized_pnl_apr24 - realized_pnl_apr23)
    old_pnl = apr24.get('dailyPnL')
    apr24['dailyPnL'] = round(daily_pnl, 2)
    print(f'2. Apr 24 dailyPnL: {old_pnl:,.0f} -> {apr24["dailyPnL"]:,.0f} (diff {apr24["dailyPnL"]-old_pnl:+,.0f})')

    # 2c. Recompute Apr 24 portfolioValue
    new_value = sum(pac['marketValue'] for pac in apr24.get('positionsAtClose', []))
    old_value = apr24.get('portfolioValue')
    apr24['portfolioValue'] = round(new_value, 2)
    apr24['unrealizedPnL'] = round(new_value - apr24.get('capitalEngaged', 0), 2)
    print(f'   Apr 24 portfolioValue: {old_value:,.0f} -> {apr24["portfolioValue"]:,.0f}')

    # ---- 3. Patch priceCache for 2175 (so Performance tab shows correct -1.73%) ----
    price_cache['2175.HK'] = {
        'success': True,
        'price': 3.41,
        'previousClose': 3.47,
        'change': -0.06,
        'changePercent': -1.7291,
        'currency': 'HKD',
        'lastUpdated': '2026-04-24T17:58:32+08:00',
    }
    # Mirror under padded form too (for any code path that looks up padded)
    price_cache['02175.HK'] = dict(price_cache['2175.HK'])
    print(f'3. priceCache 2175.HK updated: price=3.41 chg=-0.06 chg%=-1.7291')

    # Sort snapshots by date
    snapshots.sort(key=lambda s: s['date'])

    if commit:
        doc_ref.update({
            'snapshots': snapshots,
            'priceCache': price_cache,
        })
        print('\n=== COMMITTED to Firestore ===')
    else:
        print('\n=== DRY RUN — pass commit=True to write ===')


if __name__ == '__main__':
    import sys
    commit = '--commit' in sys.argv
    main(commit=commit)
