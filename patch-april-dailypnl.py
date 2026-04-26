#!/usr/bin/env python3
"""
Align April 2026 dailyPnL fields with current totalPnL deltas.

For each April 2026 trading-day snapshot, set
    dailyPnL = (today.unrealizedPnL + today.realizedPnL)
             - (yesterday.unrealizedPnL + yesterday.realizedPnL)
where "yesterday" is the latest snapshot strictly before today.

This makes the calendar's monthTotal (sum of stored dailyPnL) equal the
P&L Avril chart endpoint (Apr 24 totalPnL - Mar 31 totalPnL). They diverged
because past closingPrices were patched (Apr 13 incident scripts, the Apr 23
settlement patch tonight) without re-aligning the dailyPnL field, which the
README originally guarded as "immutable" — but immutable was meant to mean
"don't auto-recompute on every render," not "never patch when the inputs
underneath have been corrected."
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

    # Walk every April snapshot, find its predecessor, recompute dailyPnL
    print(f"{'Date':<12}{'Stored':>10}{'Should be':>12}{'Diff':>10}{'Action':>12}")
    print('-' * 60)
    patched = 0
    sum_stored = 0
    sum_truthful = 0
    for i, s in enumerate(snapshots):
        if not s['date'].startswith('2026-04'):
            continue
        # Predecessor = previous snapshot (already sorted)
        prev = snapshots[i - 1] if i > 0 else None
        if prev is None:
            continue
        truthful = round(total_pnl(s) - total_pnl(prev), 2)
        stored = s.get('dailyPnL', 0)
        sum_stored += stored
        sum_truthful += truthful
        diff = stored - truthful
        action = 'PATCH' if abs(diff) > 0.5 else 'keep'
        print(f"{s['date']:<12}{stored:>+10,.0f}{truthful:>+12,.0f}{diff:>+10,.0f}{action:>12}")
        if action == 'PATCH':
            s['dailyPnL'] = truthful
            patched += 1

    print()
    print(f"Stored sum   : {sum_stored:+,.0f} HKD")
    print(f"Truthful sum : {sum_truthful:+,.0f} HKD  (= chart endpoint after patching)")
    print(f"Patched {patched} day(s)")

    if commit and patched:
        doc_ref.update({'snapshots': snapshots})
        print('\n=== COMMITTED ===')
    elif not commit:
        print('\n=== DRY RUN — pass --commit to write ===')
    else:
        print('\nNothing to commit')


if __name__ == '__main__':
    import sys
    main(commit='--commit' in sys.argv)
