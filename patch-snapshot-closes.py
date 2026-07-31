#!/usr/bin/env python3
"""
Patch: Add missing closingPrices for 113.HK and 3680.HK to snapshots.

Root cause: these positions had no priceCache when the cron ran, so their
closing prices were never stored in snapshots. In pre-market mode the app uses
snapshot closingPrices as currentPrice/previousClose — missing entries fall
back to p.currentPrice vs p.currentPrice = 0% change.

Fix:
  April 13 snapshot → add "113.HK": 6.17, "3680.HK": 2.10  (yesterday's close)
  Previous trading day snapshot → add "113.HK": 6.10, "3680.HK": 2.20  (day-before close)

Usage:
  GOOGLE_APPLICATION_CREDENTIALS=... python3 patch-snapshot-closes.py [--dry-run]
"""

import os, sys, json
import firebase_admin
from firebase_admin import credentials, firestore

MARC_UID = "cNcZwUx3nQMV96TbB1kSkQ62u8U2"

# April 13 closing prices (the close itself)
APR13_DATE = "2026-04-13"
APR13_ADDS = {
    "113.HK":  6.17,
    "3680.HK": 2.10,
}

# Previous close (used as previousClose in pre-market for April 14)
# = closing price of the last trading day BEFORE April 13 (= April 10)
PREV_CLOSE_ADDS = {
    "113.HK":  6.10,
    "3680.HK": 2.20,
}

DRY_RUN = "--dry-run" in sys.argv

cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
if not cred_path or not os.path.exists(cred_path):
    print("ERROR: Set GOOGLE_APPLICATION_CREDENTIALS"); sys.exit(1)

firebase_admin.initialize_app(credentials.Certificate(cred_path))
doc_ref  = firestore.client().document(f"portfolios/{MARC_UID}")
data     = doc_ref.get().to_dict()
snaps    = data.get("snapshots", [])

# Sort by date ascending
snaps_sorted = sorted(enumerate(snaps), key=lambda x: x[1].get("date", ""))

HKEX_HOLIDAYS_2026 = {
    "2026-01-01","2026-02-17","2026-02-18","2026-02-19",
    "2026-04-03","2026-04-06","2026-04-07","2026-05-01",
    "2026-05-25","2026-06-19","2026-07-01","2026-10-01",
    "2026-10-19","2026-12-25"
}

def is_trading_day(d):
    from datetime import date
    y, m, day = map(int, d.split("-"))
    wd = date(y, m, day).weekday()  # 0=Mon, 5=Sat, 6=Sun
    return wd < 5 and d not in HKEX_HOLIDAYS_2026

# Find April 13 snapshot
apr13_entry = next(((i, s) for i, s in snaps_sorted if s.get("date") == APR13_DATE), None)

# Find most recent trading day snapshot BEFORE April 13
prev_entry = next(
    ((i, s) for i, s in reversed(snaps_sorted)
     if s.get("date", "") < APR13_DATE and is_trading_day(s.get("date", ""))),
    None
)

print("=" * 60)
print("SNAPSHOTS FOUND")
print("=" * 60)

if apr13_entry:
    i13, s13 = apr13_entry
    print(f"\nApril 13 snapshot (idx={i13}):")
    print(f"  date={s13['date']}  portfolioValue={s13.get('portfolioValue'):,.0f}")
    for t in APR13_ADDS:
        print(f"  closingPrices[{t}] = {s13.get('closingPrices', {}).get(t, 'MISSING')}")
else:
    print("\nNo April 13 snapshot found — cannot add closing prices")

if prev_entry:
    ip, sp = prev_entry
    print(f"\nPrevious trading day snapshot (idx={ip}):")
    print(f"  date={sp['date']}  portfolioValue={sp.get('portfolioValue'):,.0f}")
    for t in PREV_CLOSE_ADDS:
        print(f"  closingPrices[{t}] = {sp.get('closingPrices', {}).get(t, 'MISSING')}")
else:
    print("\nNo previous trading day snapshot found")

print("\n" + "=" * 60)
print("APPLYING FIXES")
print("=" * 60)

new_snaps = list(snaps)

# Fix April 13
if apr13_entry:
    i13, s13 = apr13_entry
    cp = dict(s13.get("closingPrices", {}))
    for t, price in APR13_ADDS.items():
        old = cp.get(t, "MISSING")
        cp[t] = price
        print(f"  April 13 closingPrices[{t}]: {old} → {price}")
    new_snaps[i13] = {**s13, "closingPrices": cp}

# Fix previous trading day
if prev_entry:
    ip, sp = prev_entry
    cpp = dict(sp.get("closingPrices", {}))
    for t, price in PREV_CLOSE_ADDS.items():
        old = cpp.get(t, "MISSING")
        cpp[t] = price
        print(f"  {sp['date']} closingPrices[{t}]: {old} → {price}")
    new_snaps[ip] = {**sp, "closingPrices": cpp}

if DRY_RUN:
    print(f"\n*** DRY RUN — nothing written ***")
else:
    print(f"\nWriting to Firestore...")
    doc_ref.update({"snapshots": new_snaps})
    print("Done. Hard refresh the portfolio app.")
