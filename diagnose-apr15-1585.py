#!/usr/bin/env python3
"""
Diagnose Apr 15 snapshot: find 1585.HK closing price from positionsAtClose
and show what closingPrices are present vs missing.
"""
import os, sys, firebase_admin
from firebase_admin import credentials, firestore

CRED = os.path.join(os.path.dirname(__file__), "hk-portfolio-v2",
                    "hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json")
USER_ID = "cNcZwUx3nQMV96TbB1kSkQ62u8U2"

firebase_admin.initialize_app(credentials.Certificate(CRED))
db = firestore.client()
data = db.collection("portfolios").document(USER_ID).get().to_dict()
snaps = sorted(data["snapshots"], key=lambda s: s["date"])

for date in ["2026-04-14", "2026-04-15", "2026-04-16"]:
    s = next((x for x in snaps if x["date"] == date), None)
    if not s:
        print(f"{date}: NO SNAPSHOT"); continue
    closes = s.get("closingPrices") or {}
    pac = s.get("positionsAtClose") or []
    print(f"\n=== {date} ===")
    print(f"  closingPrices keys : {sorted(closes.keys())}")
    print(f"  1585.HK in closes  : {closes.get('1585.HK')}")
    for p in pac:
        if "1585" in p.get("ticker", ""):
            print(f"  positionsAtClose 1585: {p}")
