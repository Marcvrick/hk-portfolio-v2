#!/usr/bin/env python3
"""Diagnose: what does yesterday's snapshot have for 1361.HK?"""
import json, os, sys
import firebase_admin
from firebase_admin import credentials, firestore

MARC_UID = "cNcZwUx3nQMV96TbB1kSkQ62u8U2"

cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
cred = credentials.Certificate(cred_path)
firebase_admin.initialize_app(cred)
db = firestore.client()

doc = db.document(f"portfolios/{MARC_UID}").get()
data = doc.to_dict()

snapshots = sorted(data.get("snapshots", []), key=lambda s: s["date"])
price_cache = data.get("priceCache", {})

print("=== ALL SNAPSHOTS ===")
for s in snapshots:
    cp = s.get("closingPrices", {})
    val_1361 = cp.get("1361.HK", "MISSING")
    print(f"  {s['date']}: closingPrices={'YES' if cp else 'NO'} | 1361.HK={val_1361} | dailyPnL={s.get('dailyPnL', 'N/A')}")

print("\n=== PRICE CACHE for 1361.HK ===")
cache_1361 = price_cache.get("1361.HK", {})
print(json.dumps(cache_1361, indent=2))

print("\n=== LAST 2 SNAPSHOTS DETAIL ===")
for s in snapshots[-2:]:
    print(f"\n--- {s['date']} ---")
    print(f"  closingPrices keys: {list(s.get('closingPrices', {}).keys())}")
    print(f"  closingPrices 1361.HK: {s.get('closingPrices', {}).get('1361.HK', 'MISSING')}")
    pac = s.get("positionsAtClose", [])
    for p in pac:
        if "1361" in p.get("ticker", ""):
            print(f"  positionsAtClose 1361: closingPrice={p.get('closingPrice')}, entryPrice={p.get('entryPrice')}")
