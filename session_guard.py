#!/usr/bin/env python3
"""Shared "did we just lose a session?" check for update.py / update-us.py.

Why this exists (wiki/reliability-risks.md #8, reopened 2026-09-08):

GitHub free-tier schedules drift by hours. When every run scheduled for a
session drifts past market-local midnight, each one wakes up holding the NEXT
date, fails the WINDOW_START guard, prints "Skipping", and **exits green**.
`verify-daily.py` mirrors the same guard and also skips green. So the session
is simply never written, and nothing anywhere says so.

That silence lost five sessions before anyone noticed, eleven days later:
HK 2026-08-27 / 08-28 / 08-31, US 2026-08-27 (no snapshot at all). The guard
itself was right to refuse — writing yesterday's prices under tomorrow's date
would be worse. What was missing is the alarm.

A run that cannot settle its own date asks this module whether the previous
trading day got settled. If it did, the skip is routine (an early or late slot
firing on a healthy day) and the run stays green. If it did not, that session
is over, no later run can reach it, and the caller exits non-zero so the run
goes red and GitHub emails.
"""

from datetime import datetime, timedelta

from market_calendar import previous_trading_day

# A book whose newest snapshot is older than this many days before the session
# under test is dormant, not broken. Without it, an abandoned portfolio would
# turn every skipped run red forever. Thirty days of red email is more than
# enough to act on a book that is still in use.
DORMANT_DAYS = 30


def _newest_date(snapshots):
    return max((s.get("date", "") for s in snapshots), default="")


def prior_session_gap(db, collection, market, today):
    """Return (prev_trading_day, [doc_ids lacking a cron-settled snapshot for it]).

    An empty id list means nothing was lost. A snapshot that exists but carries
    no `settledAt` counts as missing: it is browser-minted, so its closes were
    never reconciled against Yahoo and no `priceProvenance` records where they
    came from (wiki/snapshot-schema.md, incidents 2026-08-10 (b)).
    """
    prev = previous_trading_day(today, market)
    cutoff = (datetime.strptime(prev, "%Y-%m-%d")
              - timedelta(days=DORMANT_DAYS)).strftime("%Y-%m-%d")

    missing = []
    for doc in db.collection(collection).stream():
        snapshots = (doc.to_dict() or {}).get("snapshots") or []
        if not snapshots or _newest_date(snapshots) < cutoff:
            continue  # never used, or dormant
        snap = next((s for s in snapshots if s.get("date") == prev), None)
        if snap is None or not snap.get("settledAt"):
            missing.append(doc.id)
    return prev, missing


def report_prior_session_gap(db, collection, market, today, tz_label):
    """Print the verdict for a run that could not settle `today`. True = lost session.

    The caller turns True into `sys.exit(1)`. Kept here rather than in each
    updater so the HK and US wording can never drift apart.
    """
    prev, missing = prior_session_gap(db, collection, market, today)
    if not missing:
        print(f"  Prior session {prev} is cron-settled — nothing lost by this skip.")
        return False
    print(f"  ERROR: {prev} has no cron-settled snapshot ({', '.join(missing)}).")
    print(f"  Every run scheduled for {prev} drifted past midnight {tz_label}, so that")
    print("  session is lost — no later run can reach it (each run only settles its own date).")
    print("  Backfill it from raw Yahoo closes (auto_adjust=False) the way")
    print("  patch-jun-gap-backfill.py does, or accept the gap deliberately.")
    print("  See wiki/reliability-risks.md #8.")
    return True
