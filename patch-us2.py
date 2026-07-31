#!/usr/bin/env python3
"""Fix US snapshots: patch Feb 10 dailyPnL and clean Feb 9 closingPrices keys."""
import os
import firebase_admin
from firebase_admin import credentials, firestore

US_UID = "JJDY5whY9vNmCcRsi8kafMHZbmD2"

cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
cred = credentials.Certificate(cred_path)
firebase_admin.initialize_app(cred)
db = firestore.client()

doc_ref = db.document(f"us-portfolios/{US_UID}")
doc = doc_ref.get()
data = doc.to_dict()
snapshots = data.get("snapshots", [])

for i, snap in enumerate(snapshots):
    if snap["date"] == "2026-02-09":
        # Fix closingPrices keys: strip .HK and whitespace
        old_cp = snap.get("closingPrices", {})
        new_cp = {}
        for k, v in old_cp.items():
            clean_key = k.replace(".HK", "").strip()
            new_cp[clean_key] = v
            if clean_key != k:
                print(f"  Feb 9 key fix: '{k}' → '{clean_key}' = {v}")
        snapshots[i]["closingPrices"] = new_cp

        # Also fix positionsAtClose tickers
        pac = snap.get("positionsAtClose", [])
        for j, pos in enumerate(pac):
            old_ticker = pos.get("ticker", "")
            new_ticker = old_ticker.replace(".HK", "").strip()
            if new_ticker != old_ticker:
                pac[j]["ticker"] = new_ticker
        snapshots[i]["positionsAtClose"] = pac
        print(f"  Feb 9: cleaned {len(new_cp)} closingPrices keys")

    elif snap["date"] == "2026-02-10":
        # Calculate dailyPnL from unrealizedPnL difference (closingPrices can't be trusted from Feb 9)
        feb9 = next((s for s in snapshots if s["date"] == "2026-02-09"), None)
        if feb9:
            unrealized_diff = snap.get("unrealizedPnL", 0) - feb9.get("unrealizedPnL", 0)
            realized_diff = snap.get("realizedPnL", 0) - feb9.get("realizedPnL", 0)
            correct = round(unrealized_diff + realized_diff, 2)
            old = snap.get("dailyPnL")
            snapshots[i]["dailyPnL"] = correct
            print(f"  Feb 10: dailyPnL {old} → {correct}")

doc_ref.update({"snapshots": snapshots})
print("\nSaved to Firestore.")
