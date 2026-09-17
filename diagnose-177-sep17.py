#!/usr/bin/env python3
"""Diagnose: 177.HK / 0177.HK (Jiangsu Expressway) entered 2026-09-17, 10,000 @ 10.25, absent after refresh.
Read-only. Full scan for any ticker variant, positions/closedTrades/priceCache/snapshots, plus doc-level write timing."""
import json, os, re
import firebase_admin
from firebase_admin import credentials, firestore

MARC_UID = "cNcZwUx3nQMV96TbB1kSkQ62u8U2"

cred_path = os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
cred = credentials.Certificate(cred_path)
firebase_admin.initialize_app(cred)
db = firestore.client()

doc_ref = db.document(f"portfolios/{MARC_UID}")
snap = doc_ref.get()
data = snap.to_dict()

print("=== DOC-LEVEL ===")
print(f"  lastUpdated: {data.get('lastUpdated')}")
print(f"  update_time (server): {snap.update_time}")

print("\n=== FULL-TEXT SCAN for '177' (raw JSON) ===")
raw = json.dumps(data, default=str)
hits = set(re.findall(r'"[^"]*177[^"]*"', raw))
for h in sorted(hits):
    print(f"  {h}")

print("\n=== positions[] ===")
positions = data.get("positions", [])
print(f"  total: {len(positions)}")
for p in positions:
    if "177" in p.get("ticker", ""):
        print(f"  MATCH: {json.dumps(p, default=str)}")

print("\n=== closedTrades[] (any 177 variant, any date) ===")
closed = data.get("closedTrades", [])
print(f"  total: {len(closed)}")
for c in closed:
    if "177" in c.get("ticker", ""):
        print(f"  MATCH: {json.dumps(c, default=str)}")

print("\n=== priceCache keys containing '177' ===")
pc = data.get("priceCache", {})
for k, v in pc.items():
    if "177" in k:
        print(f"  {k}: {json.dumps(v, default=str)}")

print("\n=== positionDeletions[] (receipt log, if any 177 entry) ===")
deletions = data.get("positionDeletions", [])
print(f"  total: {len(deletions)}")
for d in deletions:
    if "177" in json.dumps(d, default=str):
        print(f"  MATCH: {json.dumps(d, default=str)}")

print("\n=== transactions[] (any 177 mention) ===")
txns = data.get("transactions", [])
for t in txns:
    if "177" in json.dumps(t, default=str):
        print(f"  MATCH: {json.dumps(t, default=str)}")

print("\n=== LAST 3 SNAPSHOTS: positionCount, presence of any 177 ticker ===")
snapshots = sorted(data.get("snapshots", []), key=lambda s: s["date"])
print(f"  total snapshots: {len(snapshots)}")
for s in snapshots[-3:]:
    pac = s.get("positionsAtClose", [])
    cp = s.get("closingPrices", {})
    match_pac = [p for p in pac if "177" in p.get("ticker", "")]
    match_cp = {k: v for k, v in cp.items() if "177" in k}
    print(f"  {s['date']}: positionCount={s.get('positionCount')} settledAt={s.get('settledAt')} 177-in-pac={match_pac} 177-in-cp={match_cp}")

print("\n=== ALL POSITIONS current tickers (for eyeballing padding / near-misses) ===")
for p in positions:
    print(f"  {p.get('ticker')}  qty={p.get('shares') or p.get('quantity')}  entryDate={p.get('entryDate')}")
