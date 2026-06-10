#!/usr/bin/env python3
"""
Shared trading calendar for update.py / update-us.py / verify-daily.py.

One source of truth for market holidays so the three scripts can never drift
apart again (pre-Jun-2026 state: update.py had HKEX holidays, update-us.py had
none at all, verify-daily.py only knew weekends — every NYSE holiday wrote a
phantom snapshot and every HKEX holiday produced a false-alarm red run).

Holiday sources:
  HKEX 2026: HKEX circular ce_SEHK_CT_075_2025 (carried over from update.py)
  HKEX 2027: HK Government Gazette via gov.hk/en/about/abouthk/holiday/2027.htm
             (general holidays = SEHK closures; Sundays excluded, Saturday
             holidays kept — harmless, crons only run Mon-Fri)
  NYSE 2026/2027: NYSE Group holiday calendar announcement (ICE), full
             closures only. 2027-07-05 = Independence Day observed (Jul 4 is
             a Sunday); 2027-12-24 = Christmas observed (Dec 25 is a Saturday).

COVERAGE_END: when `today` is past this date the table is blind — callers must
treat that as a loud warning (not silence), so the operator extends the table
before phantom holiday snapshots reappear.
"""

from datetime import datetime

COVERAGE_END = "2027-12-31"

HKEX_HOLIDAYS = {
    # 2025 (kept for historical re-runs / audits)
    '2025-01-01', '2025-01-29', '2025-01-30', '2025-01-31',
    '2025-04-04', '2025-04-18', '2025-04-21', '2025-05-01',
    '2025-05-05', '2025-05-31', '2025-07-01', '2025-10-01',
    '2025-10-07', '2025-12-25', '2025-12-26',
    # 2026
    '2026-01-01', '2026-02-17', '2026-02-18', '2026-02-19',
    '2026-04-03', '2026-04-06', '2026-05-01',
    '2026-05-25', '2026-06-19', '2026-07-01', '2026-10-01',
    '2026-10-19', '2026-12-25',
    # 2027 (gazetted May 2026)
    '2027-01-01',                              # New Year's Day (Fri)
    '2027-02-06', '2027-02-08', '2027-02-09',  # Lunar New Year (Sat/Mon/Tue, 4th day substitutes for Sunday 2nd day)
    '2027-03-26', '2027-03-27', '2027-03-29',  # Good Friday / day after / Easter Monday
    '2027-04-05',                              # Ching Ming (Mon)
    '2027-05-01',                              # Labour Day (Sat)
    '2027-05-13',                              # Buddha's Birthday (Thu)
    '2027-06-09',                              # Tuen Ng (Wed)
    '2027-07-01',                              # HKSAR Establishment Day (Thu)
    '2027-09-16',                              # Day after Mid-Autumn (Thu)
    '2027-10-01',                              # National Day (Fri)
    '2027-10-08',                              # Chung Yeung (Fri)
    '2027-12-25', '2027-12-27',                # Christmas (Sat) / first weekday after (Mon)
}

NYSE_HOLIDAYS = {
    # 2026
    '2026-01-01',  # New Year's Day (Thu)
    '2026-01-19',  # MLK Day (Mon)
    '2026-02-16',  # Washington's Birthday (Mon)
    '2026-04-03',  # Good Friday (Fri)
    '2026-05-25',  # Memorial Day (Mon)
    '2026-06-19',  # Juneteenth (Fri)
    '2026-07-03',  # Independence Day observed (Fri, Jul 4 is a Saturday)
    '2026-09-07',  # Labor Day (Mon)
    '2026-11-26',  # Thanksgiving (Thu)
    '2026-12-25',  # Christmas (Fri)
    # 2027
    '2027-01-01',  # New Year's Day (Fri)
    '2027-01-18',  # MLK Day (Mon)
    '2027-02-15',  # Washington's Birthday (Mon)
    '2027-03-26',  # Good Friday (Fri)
    '2027-05-31',  # Memorial Day (Mon)
    '2027-06-18',  # Juneteenth (Fri)
    '2027-07-05',  # Independence Day observed (Mon, Jul 4 is a Sunday)
    '2027-09-06',  # Labor Day (Mon)
    '2027-11-25',  # Thanksgiving (Thu)
    '2027-12-24',  # Christmas observed (Fri, Dec 25 is a Saturday)
}

_HOLIDAYS = {"hk": HKEX_HOLIDAYS, "us": NYSE_HOLIDAYS}


def is_trading_day(date_str: str, market: str) -> bool:
    """True if `date_str` (YYYY-MM-DD, market-local) is a trading day."""
    d = datetime.strptime(date_str, "%Y-%m-%d")
    if d.weekday() >= 5:  # Saturday or Sunday
        return False
    return date_str not in _HOLIDAYS[market]


def coverage_warning(date_str: str) -> str | None:
    """Non-None when the holiday table no longer covers `date_str`."""
    if date_str > COVERAGE_END:
        return (
            f"WARNING: market_calendar.py holiday table ends {COVERAGE_END} but today is {date_str}. "
            "Holidays will be treated as trading days (phantom snapshots!). Extend the table."
        )
    return None
