#!/usr/bin/env python3
"""
Patch Apr 23 2026 closingPrices to TradingView settlement values.

The Performance tab during pre-market computes daily change as
  (yesterday_snap.closingPrices[t] - day_before_yesterday_snap.closingPrices[t]) * qty
not from cached.change. So Apr 23's CAS-time closingPrices propagate into
Friday's pre-market display even after we fixed the cron.

These Apr 23 settlement values are derived from Apr 24 priceCache previousClose,
which was set to (Apr 24 close - TV change_abs). They equal TV's official Apr 23
settlement close.

Apr 23 dailyPnL is intentionally NOT recomputed (README rule: stored dailyPnL is
immutable for past days). portfolioValue and positionsAtClose marketValues are
updated to keep the snapshot internally consistent for the closingPrices field.
"""

import firebase_admin
from firebase_admin import credentials, firestore

CRED = '/Users/mc/Downloads/hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json'
USER_ID = 'cNcZwUx3nQMV96TbB1kSkQ62u8U2'

# TV settlement Apr 23 closes (= Apr 24 priceCache previousClose values)
TV_APR23_CLOSE = {
    '113.HK':  6.17,
    '1316.HK': 5.08,
    '1585.HK': 12.00,
    '0177.HK': 10.56,
    '1913.HK': 37.76,
    '1999.HK': 4.24,
    '2175.HK': 3.47,
    '2643.HK': 25.78,
    '0285.HK': 26.86,
    '3680.HK': 2.45,
    '3998.HK': 4.27,
    '0434.HK': 3.13,
    '6826.HK': 21.38,
    '856.HK':  9.39,
    '9690.HK': 13.63,
}


def main(commit=False):
    cred = credentials.Certificate(CRED)
    firebase_admin.initialize_app(cred)
    db = firestore.client()

    doc_ref = db.collection('portfolios').document(USER_ID)
    data = doc_ref.get().to_dict()
    snapshots = data['snapshots']

    apr23 = next((s for s in snapshots if s['date'] == '2026-04-23'), None)
    if not apr23:
        print('Apr 23 snapshot not found!')
        return

    diffs = 0
    for ticker, tv_close in TV_APR23_CLOSE.items():
        old = apr23['closingPrices'].get(ticker)
        if old != tv_close:
            print(f'  {ticker:10s} {old} -> {tv_close}')
            apr23['closingPrices'][ticker] = tv_close
            diffs += 1

    # Sync positionsAtClose
    for pac in apr23.get('positionsAtClose', []):
        t = pac['ticker']
        if t in TV_APR23_CLOSE:
            pac['closingPrice'] = TV_APR23_CLOSE[t]
            pac['marketValue'] = TV_APR23_CLOSE[t] * pac['quantity']
            pac['pnl'] = (TV_APR23_CLOSE[t] - pac.get('entryPrice', 0)) * pac['quantity']
            if pac.get('entryPrice'):
                pac['pnlPercent'] = (TV_APR23_CLOSE[t] - pac['entryPrice']) / pac['entryPrice'] * 100

    # Sync portfolioValue (sum of closingPrices * qty per positionsAtClose)
    new_value = sum(pac['marketValue'] for pac in apr23.get('positionsAtClose', []))
    old_value = apr23['portfolioValue']
    apr23['portfolioValue'] = round(new_value, 2)
    apr23['unrealizedPnL'] = round(new_value - apr23.get('capitalEngaged', 0), 2)

    print(f'\nPatched {diffs}/{len(TV_APR23_CLOSE)} Apr 23 closingPrices to TV settlement')
    print(f'Apr 23 portfolioValue: {old_value:,.0f} -> {apr23["portfolioValue"]:,.0f}')
    print(f'Apr 23 dailyPnL preserved at {apr23["dailyPnL"]:+,.0f} (immutable per README rule)')

    if commit:
        doc_ref.update({'snapshots': snapshots})
        print('\n=== COMMITTED to Firestore ===')
    else:
        print('\n=== DRY RUN ===')


if __name__ == '__main__':
    import sys
    main(commit='--commit' in sys.argv)
