#!/usr/bin/env python3
"""Diagnose US portfolio snapshots."""
import json, os
import firebase_admin
from firebase_admin import credentials, firestore

cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
cred = credentials.Certificate(cred_path)
firebase_admin.initialize_app(cred)
db = firestore.client()

print("=== ALL US PORTFOLIO DOCUMENTS ===")
for doc in db.collection("us-portfolios").stream():
    data = doc.to_dict()
    snapshots = sorted(data.get("snapshots", []), key=lambda s: s["date"])
    positions = data.get("positions", [])
    print(f"\nUser: {doc.id}")
    print(f"  Positions: {len(positions)}")
    print(f"  Snapshots: {len(snapshots)}")
    for s in snapshots:
        dp = s.get("dailyPnL", "MISSING")
        cp = "YES" if s.get("closingPrices") else "NO"
        pac = "YES" if s.get("positionsAtClose") else "NO"
        unrealized = s.get("unrealizedPnL", 0)
        print(f"    {s['date']}: dailyPnL={dp} | unrealizedPnL={unrealized:.1f} | closingPrices={cp} | positionsAtClose={pac}")
