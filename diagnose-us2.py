#!/usr/bin/env python3
"""Check US closingPrices keys for each snapshot."""
import json, os
import firebase_admin
from firebase_admin import credentials, firestore

US_UID = "JJDY5whY9vNmCcRsi8kafMHZbmD2"

cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
cred = credentials.Certificate(cred_path)
firebase_admin.initialize_app(cred)
db = firestore.client()

doc = db.document(f"us-portfolios/{US_UID}").get()
data = doc.to_dict()

snapshots = sorted(data.get("snapshots", []), key=lambda s: s["date"])

for s in snapshots:
    cp = s.get("closingPrices", {})
    print(f"\n=== {s['date']} closingPrices ===")
    for k, v in sorted(cp.items()):
        print(f"  {k}: {v}")
