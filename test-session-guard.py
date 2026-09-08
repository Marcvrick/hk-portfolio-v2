#!/usr/bin/env python3
"""Regression test for the lost-session alarm and the cron drift coverage.

Hermetic on purpose: no Firestore, no network, no credentials, so it can be run
anywhere at any time. This project has shipped a rules suite that 403'd on every
invocation for 72 days (wiki/security-rules.md) — a test that cannot run is not
a test.

    python3 test-session-guard.py

Three things are pinned:

1. `previous_trading_day` — the session a drifted run has just lost.
2. `prior_session_gap` — which books count as having missed it. A browser-minted
   snapshot (no `settledAt`) counts as missed: its closes were never reconciled.
3. The workflow cron fan-out — that the scheduled slots tile the drift range
   from zero with NO GAP. The three sessions lost in Aug 2026 were lost because
   every slot sat inside the valid window, so the fleet's drift tolerance was
   just the earliest slot's headroom. A gap here re-opens that hole silently.

The branch wiring inside update.py / update-us.py (that the alarm is reached on
every skip path, and never on a healthy in-window run) was verified separately
against the live document on 2026-09-08, 12/12 cases — see wiki/incidents.md.
"""
import re
import sys
from pathlib import Path

from market_calendar import previous_trading_day
from session_guard import prior_session_gap

HERE = Path(__file__).parent
failures = []


def check(label, got, want):
    if got != want:
        failures.append(f"{label}\n      got  {got!r}\n      want {want!r}")
        print(f"FAIL  {label}")
    else:
        print(f"ok    {label}")


# ---------------------------------------------------------------- 1. calendar
check("prev trading day: Tue -> Mon",
      previous_trading_day("2026-09-01", "hk"), "2026-08-31")
check("prev trading day: Mon -> Fri (skips the weekend)",
      previous_trading_day("2026-08-31", "hk"), "2026-08-28")
check("prev trading day: Sat -> Fri (a drifted run landing on a Saturday)",
      previous_trading_day("2026-08-29", "hk"), "2026-08-28")
check("prev trading day: HK skips the 2026-10-01 National Day holiday",
      previous_trading_day("2026-10-02", "hk"), "2026-09-30")
check("prev trading day: US skips Labor Day 2026-09-07",
      previous_trading_day("2026-09-08", "us"), "2026-09-04")
check("prev trading day: US skips Thanksgiving 2026-11-26",
      previous_trading_day("2026-11-27", "us"), "2026-11-25")
check("prev trading day: HK crosses Lunar New Year 2027 (Feb 6/8/9 + weekend)",
      previous_trading_day("2027-02-10", "hk"), "2027-02-05")


# ------------------------------------------------------------ 2. gap detector
class FakeDoc:
    def __init__(self, doc_id, snapshots):
        self.id = doc_id
        self._d = {"snapshots": snapshots}

    def to_dict(self):
        return self._d


class FakeDB:
    def __init__(self, docs):
        self._docs = docs

    def collection(self, _name):
        return self

    def stream(self):
        return iter(self._docs)


def settled(date):
    return {"date": date, "settledAt": f"{date}T23:12:00+08:00"}


def minted(date):
    return {"date": date}  # browser-written: no settledAt, no priceProvenance


live = [settled("2026-08-26"), settled("2026-08-27"), settled("2026-08-28")]

check("healthy book: prior session settled -> no gap",
      prior_session_gap(FakeDB([FakeDoc("book", live)]), "portfolios", "hk", "2026-08-31"),
      ("2026-08-28", []))

check("prior session browser-minted -> counts as missed",
      prior_session_gap(FakeDB([FakeDoc("book", [settled("2026-08-26"), minted("2026-08-27")])]),
                        "portfolios", "hk", "2026-08-28"),
      ("2026-08-27", ["book"]))

check("prior session absent entirely -> missed (the US 2026-08-27 shape)",
      prior_session_gap(FakeDB([FakeDoc("book", [settled("2026-08-26")])]),
                        "us-portfolios", "us", "2026-08-28"),
      ("2026-08-27", ["book"]))

check("empty book never alarms",
      prior_session_gap(FakeDB([FakeDoc("empty", [])]), "portfolios", "hk", "2026-08-31"),
      ("2026-08-28", []))

check("dormant book (last snapshot > 30d old) never alarms",
      prior_session_gap(FakeDB([FakeDoc("old", [settled("2026-06-01")])]),
                        "portfolios", "hk", "2026-08-31"),
      ("2026-08-28", []))

check("two books, one broken -> only the broken one is named",
      prior_session_gap(FakeDB([FakeDoc("good", live),
                                FakeDoc("bad", [settled("2026-08-26"), minted("2026-08-28")])]),
                        "portfolios", "hk", "2026-08-31"),
      ("2026-08-28", ["bad"]))

check("weekend run looks back to Friday, not to the Saturday",
      prior_session_gap(FakeDB([FakeDoc("book", [settled("2026-08-26"), minted("2026-08-28")])]),
                        "portfolios", "hk", "2026-08-29"),
      ("2026-08-28", ["book"]))


# ----------------------------------------------------- 3. cron drift coverage
def drift_bands(workflow, window_start_utc, window_end_utc):
    """For each scheduled slot, the drift interval (minutes) that lands in-window.

    A slot scheduled at UTC minute T lands in the market's valid window iff
    window_start <= T + drift < window_end. Slots are quoted in UTC; the window
    is the same day's UTC span of the market-local [16:10, midnight) guard.
    """
    text = (HERE / ".github/workflows" / workflow).read_text()
    bands = []
    for minute, hour in re.findall(r"^\s*- cron: '(\d+) (\d+) ", text, re.M):
        t = int(hour) * 60 + int(minute)
        lo, hi = window_start_utc - t, window_end_utc - t
        if hi > 0:
            bands.append((max(lo, 0), hi))
    return sorted(bands)


def contiguous_from_zero(bands):
    """Highest drift covered with no gap starting at 0, or None if 0 is uncovered."""
    reach = None
    for lo, hi in bands:
        if reach is None:
            if lo > 0:
                return None
            reach = hi
        elif lo <= reach:
            reach = max(reach, hi)
        else:
            break  # a gap: drift between `reach` and `lo` lands nowhere
    return reach


# HK: valid window 16:10 HKT -> midnight HKT == 08:10 -> 16:00 UTC.
hk = contiguous_from_zero(drift_bands("daily-update-hk.yml", 8 * 60 + 10, 16 * 60))
check("HK slots tile drift from 0 with no gap, out to >= 13h",
      hk is not None and hk >= 13 * 60, True)
print(f"      HK  contiguous drift tolerance: {hk // 60}h{hk % 60:02d}m")

# US: valid window 16:10 ET -> midnight ET. EDT (UTC-4) is the tighter of the
# two, == 20:10 -> 28:00 UTC. EST would be an hour more generous.
us = contiguous_from_zero(drift_bands("daily-update-us.yml", 20 * 60 + 10, 28 * 60))
check("US slots tile drift from 0 with no gap, out to >= 12h (EDT, the tighter case)",
      us is not None and us >= 12 * 60, True)
print(f"      US  contiguous drift tolerance (EDT): {us // 60}h{us % 60:02d}m")


# -------------------------------------------------------------------- verdict
print()
if failures:
    print(f"=== FAIL — {len(failures)} of the checks above ===")
    for f in failures:
        print("  " + f)
    sys.exit(1)
print("=== PASS — session guard + cron drift coverage ===")
