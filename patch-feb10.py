#!/usr/bin/env python3
"""One-time patch: fix Feb 10 dailyPnL from -1600 to -3895 in Firestore."""
import os
import firebase_admin
from firebase_admin import credentials, firestore

MARC_UID = "cNcZwUx3nQMV96TbB1kSkQ62u8U2"
TARGET_DATE = "2026-02-10"
CORRECT_DAILY_PNL = -3895

cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
cred = credentials.Certificate(cred_path)
firebase_admin.initialize_app(cred)
db = firestore.client()

doc_ref = db.document(f"portfolios/{MARC_UID}")
doc = doc_ref.get()
data = doc.to_dict()

snapshots = data.get("snapshots", [])

# Find and patch Feb 10
for i, snap in enumerate(snapshots):
    if snap["date"] == TARGET_DATE:
        old_val = snap.get("dailyPnL")
        print(f"Found {TARGET_DATE}: dailyPnL = {old_val}")
        snapshots[i]["dailyPnL"] = CORRECT_DAILY_PNL
        print(f"Patched to: dailyPnL = {CORRECT_DAILY_PNL}")
        break
else:
    print(f"ERROR: No snapshot found for {TARGET_DATE}")
    exit(1)

# Save back
doc_ref.update({"snapshots": snapshots})
print(f"Saved to Firestore. Feb 10 dailyPnL is now {CORRECT_DAILY_PNL}.")
