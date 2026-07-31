#!/usr/bin/env python3
"""
Patch: Fix missing/zero change & changePercent in priceCache for 3680.HK and 0113.HK.

Root cause: priceCache entries for these tickers lack proper change/changePercent fields,
so the app falls back to 0% / +0 display.

Correct data (April 13 closes):
  3680.HK: price=2.10, prevClose=2.20, change=-0.10, changePercent=-4.545%
  0113.HK: price=6.17, prevClose=6.10, change=+0.07, changePercent=+1.148%

Usage:
  GOOGLE_APPLICATION_CREDENTIALS=... python3 patch-pricecache-fix.py [--dry-run]
"""

import os
import sys
import json
import firebase_admin
from firebase_admin import credentials, firestore

MARC_UID = "cNcZwUx3nQMV96TbB1kSkQ62u8U2"

FIXES = {
    "3680.HK": {
        "price":         2.10,
        "previousClose": 2.20,
        "change":        -0.10,
        "changePercent": -4.5455,
        "success":       True,
        "currency":      "HKD",
    },
    "0113.HK": {
        "price":         6.17,
        "previousClose": 6.10,
        "change":        0.07,
        "changePercent": 1.1475,
        "success":       True,
        "currency":      "HKD",
    },
    "113.HK": {
        "price":         6.17,
        "previousClose": 6.10,
        "change":        0.07,
        "changePercent": 1.1475,
        "success":       True,
        "currency":      "HKD",
    },
}

DRY_RUN = "--dry-run" in sys.argv

cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
if not cred_path or not os.path.exists(cred_path):
    print("ERROR: Set GOOGLE_APPLICATION_CREDENTIALS to the path of your service account JSON")
    sys.exit(1)

cred = credentials.Certificate(cred_path)
firebase_admin.initialize_app(cred)
db = firestore.client()

doc_ref = db.document(f"portfolios/{MARC_UID}")
data = doc_ref.get().to_dict()
price_cache = data.get("priceCache", {})

print("=" * 60)
print("CURRENT priceCache STATE")
print("=" * 60)
for ticker in FIXES:
    current = price_cache.get(ticker, {})
    print(f"\n{ticker}:")
    print(f"  price={current.get('price')}  change={current.get('change')}  "
          f"changePercent={current.get('changePercent')}  prevClose={current.get('previousClose')}")

print("\n" + "=" * 60)
print("APPLYING FIXES")
print("=" * 60)

new_cache = dict(price_cache)
for ticker, fix in FIXES.items():
    existing = price_cache.get(ticker, {})
    new_cache[ticker] = {**existing, **fix}
    print(f"\n{ticker}:")
    print(f"  price={fix['price']}  change={fix['change']:+.2f}  "
          f"changePercent={fix['changePercent']:+.4f}%  prevClose={fix['previousClose']}")

if DRY_RUN:
    print(f"\n*** DRY RUN — no changes written ***")
else:
    print(f"\nWriting to Firestore...")
    doc_ref.update({"priceCache": new_cache})
    print("Done. Refresh the portfolio app.")
