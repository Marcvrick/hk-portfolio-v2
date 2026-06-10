#!/usr/bin/env python3
"""
Remove snapshots dated on non-trading days (weekends / market holidays).

No legitimate snapshot can exist on a day the market was closed. They appear via:
  - the browser minting a snapshot on a holiday (no settledAt), or
  - the pre-Jun-10-2026 update-us.py, which had no holiday guard at all and on
    NYSE holidays wrote a settled snapshot duplicating the prior session's
    change_abs as a fresh dailyPnL tile (confirmed: 2026-05-25 Memorial Day).

Phantom tiles corrupt weekTotal / monthTotal sums in the calendar.

Only the `snapshots` array is touched. Idempotent — re-running finds nothing.

Usage:
    GOOGLE_APPLICATION_CREDENTIALS=... python3 patch-remove-nontrading-snapshots.py --dry-run
    GOOGLE_APPLICATION_CREDENTIALS=... python3 patch-remove-nontrading-snapshots.py --apply

Found on 2026-06-10:
    portfolios/cNcZ…        2026-02-01 (Sunday, dailyPnL −4500, browser-minted)
    us-portfolios/JJDY…     2026-02-16 + 2026-04-03 (browser, dailyPnL 0)
                            2026-05-25 (CRON-settled, dailyPnL −387.85)
"""

import sys
import firebase_admin
from firebase_admin import firestore

from market_calendar import is_trading_day

MODE = sys.argv[1] if len(sys.argv) > 1 else "--dry-run"
if MODE not in ("--dry-run", "--apply"):
    print("Usage: patch-remove-nontrading-snapshots.py [--dry-run|--apply]")
    sys.exit(2)

firebase_admin.initialize_app()
db = firestore.client()

for coll, mkt in [("portfolios", "hk"), ("us-portfolios", "us")]:
    for doc in db.collection(coll).stream():
        data = doc.to_dict()
        snaps = data.get("snapshots", [])
        if not snaps:
            continue
        keep, drop = [], []
        for s in snaps:
            (keep if is_trading_day(s["date"], mkt) else drop).append(s)
        if not drop:
            print(f"{coll}/{doc.id}: clean ({len(snaps)} snapshots)")
            continue
        for s in drop:
            print(f"{coll}/{doc.id}: DROP {s['date']}  dailyPnL={s.get('dailyPnL')}  "
                  f"pv={s.get('portfolioValue')}  settledAt={s.get('settledAt', '-')}")
        if MODE == "--apply":
            db.collection(coll).document(doc.id).update({"snapshots": keep})
            print(f"{coll}/{doc.id}: APPLIED — {len(snaps)} -> {len(keep)} snapshots")
        else:
            print(f"{coll}/{doc.id}: dry-run — would go {len(snaps)} -> {len(keep)} snapshots")
