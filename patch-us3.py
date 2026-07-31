#!/usr/bin/env python3
"""Clean US snapshots: delete garbage Feb 9, reset Feb 10 as first snapshot."""
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

print(f"Before: {len(snapshots)} snapshots")
for s in snapshots:
    print(f"  {s['date']}: dailyPnL={s.get('dailyPnL', 'MISSING')}")

# Delete Feb 9 (garbage data from old .HK bug)
snapshots = [s for s in snapshots if s["date"] != "2026-02-09"]

# Remove dailyPnL from Feb 10 (now the first snapshot, no reference)
for i, s in enumerate(snapshots):
    if s["date"] == "2026-02-10" and "dailyPnL" in s:
        del snapshots[i]["dailyPnL"]
        print(f"Removed dailyPnL from Feb 10")

print(f"\nAfter: {len(snapshots)} snapshots")
for s in snapshots:
    print(f"  {s['date']}: dailyPnL={s.get('dailyPnL', 'MISSING')}")

doc_ref.update({"snapshots": snapshots})
print("\nSaved to Firestore.")
