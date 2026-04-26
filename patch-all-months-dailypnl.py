#!/usr/bin/env python3
"""
Align ALL stored dailyPnL fields with current totalPnL deltas.

For every snapshot in Firestore, set
    dailyPnL = (today.unrealizedPnL + today.realizedPnL)
             - (predecessor.unrealizedPnL + predecessor.realizedPnL)

Skips snapshots with no predecessor (the first one). Every patched month's
calendar monthTotal will then equal that month's P&L chart endpoint.

Why this is safe: the stored unrealizedPnL/realizedPnL fields are derived
from positionsAtClose × closingPrices and from closedTrades — both already
reflect any retroactive corrections we've made. The dailyPnL field is the
only one that was frozen at create time and never reconciled.
"""

import firebase_admin
from firebase_admin import credentials, firestore

CRED = '/Users/mc/Downloads/hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json'
USER_ID = 'cNcZwUx3nQMV96TbB1kSkQ62u8U2'


def total_pnl(s):
    return (s.get('unrealizedPnL', 0) or 0) + (s.get('realizedPnL', 0) or 0)


def main(commit=False):
    cred = credentials.Certificate(CRED)
    firebase_admin.initialize_app(cred)
    db = firestore.client()

    doc_ref = db.collection('portfolios').document(USER_ID)
    data = doc_ref.get().to_dict()
    snapshots = sorted(data['snapshots'], key=lambda s: s['date'])

    by_month = {}  # 'YYYY-MM' -> {'patches': [...], 'old_sum': float, 'new_sum': float}
    patched_count = 0

    for i, s in enumerate(snapshots):
        if i == 0:
            continue
        prev = snapshots[i - 1]
        truthful = round(total_pnl(s) - total_pnl(prev), 2)
        stored = s.get('dailyPnL', 0)
        diff = stored - truthful
        ym = s['date'][:7]
        bucket = by_month.setdefault(ym, {'patches': [], 'old_sum': 0.0, 'new_sum': 0.0})
        bucket['old_sum'] += stored
        bucket['new_sum'] += truthful
        if abs(diff) > 0.5:
            bucket['patches'].append((s['date'], stored, truthful, diff))
            s['dailyPnL'] = truthful
            patched_count += 1

    print(f"{'Month':<8}{'Days patched':>14}{'Old monthTotal':>18}{'New monthTotal':>18}{'Net swing':>14}")
    print('-' * 75)
    for ym in sorted(by_month):
        b = by_month[ym]
        if not b['patches'] and abs(b['old_sum'] - b['new_sum']) < 0.5:
            line_marker = ''
        else:
            line_marker = '   ◀'
        print(f"{ym:<8}{len(b['patches']):>14}{b['old_sum']:>+18,.0f}{b['new_sum']:>+18,.0f}{b['new_sum']-b['old_sum']:>+14,.0f}{line_marker}")

    print()
    print(f"Total snapshots scanned: {len(snapshots)}")
    print(f"Total snapshots to patch: {patched_count}")

    if commit and patched_count:
        doc_ref.update({'snapshots': snapshots})
        print('\n=== COMMITTED ===')
    elif not commit:
        print('\n=== DRY RUN — pass --commit to write ===')
    else:
        print('\nNothing to commit')


if __name__ == '__main__':
    import sys
    main(commit='--commit' in sys.argv)
