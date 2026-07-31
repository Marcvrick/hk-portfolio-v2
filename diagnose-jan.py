#!/usr/bin/env python3
"""Inspect January 2026 snapshot structure."""
import os, firebase_admin
from firebase_admin import credentials, firestore

CRED = os.path.join(os.path.dirname(__file__), "hk-portfolio-v2",
                    "hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json")
USER_ID = "cNcZwUx3nQMV96TbB1kSkQ62u8U2"

firebase_admin.initialize_app(credentials.Certificate(CRED))
data = firestore.client().document(f"portfolios/{USER_ID}").get().to_dict()
snaps = sorted(data["snapshots"], key=lambda s: s["date"])
ct = data.get("closedTrades", [])

jan = [s for s in snaps if s["date"].startswith("2026-01")]
for s in jan:
    date = s["date"]
    pac  = s.get("positionsAtClose") or []
    cp   = s.get("closingPrices") or {}
    print(f"\n=== {date} ===")
    print(f"  keys present      : {sorted(s.keys())}")
    print(f"  positionsAtClose  : {len(pac)} entries")
    print(f"  closingPrices     : {len(cp)} entries  → {sorted(cp.keys())}")
    print(f"  portfolioValue    : {s.get('portfolioValue')}")
    print(f"  dailyPnL          : {s.get('dailyPnL')}")
    print(f"  unrealizedPnL     : {s.get('unrealizedPnL')}")
    print(f"  realizedPnL       : {s.get('realizedPnL')}")
    if pac:
        for p in pac:
            print(f"    {p}")

closed_jan = [t for t in ct if (t.get("exitDate") or "").startswith("2026-01")]
if closed_jan:
    print(f"\n=== Closed trades in January ===")
    for t in closed_jan:
        print(f"  {t}")
