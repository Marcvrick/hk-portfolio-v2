#!/usr/bin/env python3
"""Patch US portfolio snapshots: fix wrong dailyPnL values."""
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
        # First snapshot ever — no previous day to compare, dailyPnL is meaningless
        # Remove it so calendar falls back to "no data" for this day
        old = snap.get("dailyPnL")
        if "dailyPnL" in snapshots[i]:
            del snapshots[i]["dailyPnL"]
        print(f"Feb 9: removed dailyPnL (was {old})")

    elif snap["date"] == "2026-02-10":
        # Calculate correct dailyPnL from closingPrices difference
        feb9 = next((s for s in snapshots if s["date"] == "2026-02-09"), None)
        if feb9 and feb9.get("closingPrices") and snap.get("closingPrices") and snap.get("positionsAtClose"):
            daily_pnl = 0
            for pos in snap["positionsAtClose"]:
                ticker = pos["ticker"]
                today_close = snap["closingPrices"].get(ticker)
                prev_close = feb9["closingPrices"].get(ticker)
                if today_close is not None and prev_close is not None:
                    daily_pnl += (today_close - prev_close) * pos["quantity"]
                    print(f"  {ticker}: ({today_close} - {prev_close}) * {pos['quantity']} = {(today_close - prev_close) * pos['quantity']:.1f}")
                else:
                    print(f"  {ticker}: MISSING (today={today_close}, prev={prev_close})")
            realized_change = (snap.get("realizedPnL", 0)) - (feb9.get("realizedPnL", 0))
            daily_pnl += realized_change
            old = snap.get("dailyPnL")
            snapshots[i]["dailyPnL"] = round(daily_pnl, 2)
            print(f"Feb 10: dailyPnL {old} → {round(daily_pnl, 2)}")
        else:
            # Fallback: use unrealizedPnL difference
            unrealized_diff = (snap.get("unrealizedPnL", 0)) - (feb9.get("unrealizedPnL", 0) if feb9 else 0)
            realized_diff = (snap.get("realizedPnL", 0)) - (feb9.get("realizedPnL", 0) if feb9 else 0)
            correct = round(unrealized_diff + realized_diff, 2)
            old = snap.get("dailyPnL")
            snapshots[i]["dailyPnL"] = correct
            print(f"Feb 10: dailyPnL {old} → {correct} (from unrealizedPnL diff)")

doc_ref.update({"snapshots": snapshots})
print("\nSaved to Firestore.")
