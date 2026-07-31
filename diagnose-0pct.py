#!/usr/bin/env python3
"""Diagnostic: show exact position data + priceCache for 3680.HK and 0113.HK/113.HK"""
import os, sys, json
import firebase_admin
from firebase_admin import credentials, firestore

MARC_UID = "cNcZwUx3nQMV96TbB1kSkQ62u8U2"
TICKERS  = ["3680.HK", "0113.HK", "113.HK"]

cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
if not cred_path or not os.path.exists(cred_path):
    print("ERROR: Set GOOGLE_APPLICATION_CREDENTIALS"); sys.exit(1)

firebase_admin.initialize_app(credentials.Certificate(cred_path))
data = firestore.client().document(f"portfolios/{MARC_UID}").get().to_dict()

print("=== POSITIONS ===")
for p in data.get("positions", []):
    if any(t in p.get("ticker","") for t in ["3680","0113","113"]):
        print(json.dumps(p, indent=2, default=str))

print("\n=== PRICE CACHE ===")
cache = data.get("priceCache", {})
for t in TICKERS:
    entry = cache.get(t)
    print(f"{t}: {json.dumps(entry, indent=2, default=str) if entry else 'NOT FOUND'}")
