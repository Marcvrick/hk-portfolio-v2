#!/usr/bin/env python3
"""
Check 5 (record completeness) in verify-daily.py — the check that would have caught
2600.HK being held from 2026-07-23 yet absent from 11 consecutive snapshots.

Pure-function test on verify_portfolio(): no Firestore, no network.
Run: python3 test-verify-completeness.py
"""
import importlib.util
import pathlib

spec = importlib.util.spec_from_file_location(
    "verify_daily", pathlib.Path(__file__).with_name("verify-daily.py"))
vd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vd)

TODAY = "2026-08-06"


def data_with(pac_tickers, closing_tickers, positions):
    """A portfolio whose snapshot records only the given tickers."""
    return {
        "positions": positions,
        "closedTrades": [],
        "priceCache": {},
        "snapshots": [{
            "date": TODAY,
            "dailyPnL": 0,
            "portfolioValue": 100000,
            "closingPrices": {t: 10.0 for t in closing_tickers},
            "positionsAtClose": [{"ticker": t, "quantity": 100, "entryPrice": 9.0,
                                  "closingPrice": 10.0} for t in pac_tickers],
        }],
    }


def completeness(issues):
    return [i for i in issues if "missing from snapshot" in i]


HELD = [{"ticker": "0285.HK", "quantity": 1500, "entryPrice": 43.0, "entryDate": "2025-09-22"},
        {"ticker": "2600.HK", "quantity": 12000, "entryPrice": 8.40, "entryDate": "2026-07-23"}]

# 1. The real 2026-08-06 shape: 2600 held, absent from both maps -> must flag.
d = data_with(["0285.HK"], ["0285.HK"], HELD)
found = completeness(vd.verify_portfolio("u", d, {}, TODAY))
assert len(found) == 1, f"expected 1 completeness issue, got {found}"
assert "2600.HK" in found[0] and "positionsAtClose" in found[0] and "closingPrices" in found[0], found[0]

# 2. Both positions recorded -> clean.
d = data_with(["0285.HK", "2600.HK"], ["0285.HK", "2600.HK"], HELD)
assert completeness(vd.verify_portfolio("u", d, {}, TODAY)) == []

# 3. Present in positionsAtClose but no closing price -> still flagged, naming only that map.
d = data_with(["0285.HK", "2600.HK"], ["0285.HK"], HELD)
found = completeness(vd.verify_portfolio("u", d, {}, TODAY))
assert len(found) == 1 and "closingPrices" in found[0] and "positionsAtClose" not in found[0], found

# 4. A position entered AFTER the snapshot date is not yet held -> no flag.
future = [{"ticker": "3277.HK", "quantity": 1500, "entryPrice": 68.7, "entryDate": "2026-08-07"}]
d = data_with(["0285.HK"], ["0285.HK"], future)
assert completeness(vd.verify_portfolio("u", d, {}, TODAY)) == []

# 5. A snapshot with no positionsAtClose at all -> flagged, not silently passed.
d = data_with([], [], HELD)
d["snapshots"][0]["positionsAtClose"] = []
issues = vd.verify_portfolio("u", d, {}, TODAY)
assert any("no positionsAtClose" in i for i in issues), issues


# --- Check 6: snapshot self-consistency ---------------------------------------
def consistency(issues):
    return [i for i in issues if "disagrees with positionsAtClose" in i
            or "positionCount=" in i or "no positionsAtClose entry" in i]


def snap_with(**over):
    """Consistent baseline: 1 position, 100 sh @ 9.00, close 10.00."""
    s = {"date": TODAY, "dailyPnL": 0, "closingPrices": {"0285.HK": 10.0},
         "positionsAtClose": [{"ticker": "0285.HK", "quantity": 100,
                               "entryPrice": 9.0, "closingPrice": 10.0}],
         "portfolioValue": 1000.0, "capitalEngaged": 900.0,
         "unrealizedPnL": 100.0, "positionCount": 1}
    s.update(over)
    return {"positions": [{"ticker": "0285.HK", "quantity": 100, "entryPrice": 9.0,
                           "entryDate": "2025-09-22"}],
            "closedTrades": [], "priceCache": [], "snapshots": [s]}


assert consistency(vd.verify_portfolio("u", snap_with(), {}, TODAY)) == [], "baseline must be clean"

# 2026-03-31 shape: capitalEngaged too low while pv is right.
found = consistency(vd.verify_portfolio("u", snap_with(capitalEngaged=800.0), {}, TODAY))
assert any("capitalEngaged" in i for i in found), found

# 2026-04-13 shape: portfolioValue disagrees too.
found = consistency(vd.verify_portfolio("u", snap_with(portfolioValue=950.0), {}, TODAY))
assert any("portfolioValue" in i for i in found), found

# 2026-05-15 shape: positionCount overstates, and orphan closing prices remain.
found = consistency(vd.verify_portfolio(
    "u", snap_with(positionCount=4,
                   closingPrices={"0285.HK": 10.0, "1999.HK": 5.0, "2013.HK": 5.0}),
    {}, TODAY))
assert any("positionCount=4" in i for i in found), found
assert any("1999.HK" in i and "2013.HK" in i for i in found), found

# Sub-threshold rounding noise must not trip it.
assert consistency(vd.verify_portfolio("u", snap_with(portfolioValue=1000.5), {}, TODAY)) == []

print("OK — record-completeness check catches the 2600 case (5 cases)")
print("OK — self-consistency check catches the 03-31 / 04-13 / 05-15 shapes (5 cases)")
