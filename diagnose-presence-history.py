#!/usr/bin/env python3
"""
diagnose-presence-history.py
For every ticker ever seen in any snapshot's positionsAtClose, print its presence
timeline: first date, last date, and any GAPS (disappeared then reappeared).
A gap = ticker was sold/removed, then a stale write resurrected it.
Also prints per-snapshot posCount + realizedPnL trajectory to spot the wipe date.
Read-only.
"""
import firebase_admin
from firebase_admin import credentials, firestore

CRED = 'hk-portfolio-v2/hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json'
DOC_ID = 'cNcZwUx3nQMV96TbB1kSkQ62u8U2'

cred = credentials.Certificate(CRED)
firebase_admin.initialize_app(cred)
db = firestore.client()
doc = db.collection('portfolios').document(DOC_ID).get().to_dict()

snapshots = sorted(doc.get('snapshots', []), key=lambda s: s.get('date', ''))
dates = [s['date'] for s in snapshots]
open_now = {p.get('ticker') for p in doc.get('positions', [])}
closed_tickers = {c.get('ticker') for c in doc.get('closedTrades', [])}

presence = {}  # ticker -> list of dates present
for s in snapshots:
    for p in (s.get('positionsAtClose') or []):
        presence.setdefault(p.get('ticker'), []).append(s['date'])

print(f"{len(snapshots)} snapshots from {dates[0]} to {dates[-1]}\n")
print("=== tickers with GAPS in presence (disappeared then reappeared) ===")
idx = {d: i for i, d in enumerate(dates)}
for t in sorted(presence):
    ds = presence[t]
    gaps = []
    for a, b in zip(ds, ds[1:]):
        # gap if at least one snapshot exists strictly between a and b without t
        if idx[b] - idx[a] > 1:
            gaps.append((a, b, idx[b] - idx[a] - 1))
    status = 'OPEN' if t in open_now else 'closed'
    ct = 'has closedTrade' if t in closed_tickers else 'NO closedTrade'
    if gaps:
        print(f"  {t:10s} [{status}, {ct}] present {ds[0]}..{ds[-1]} ({len(ds)} snaps)")
        for a, b, n in gaps:
            print(f"      GAP: absent after {a}, reappears {b} ({n} snapshots missing)")

print("\n=== per-snapshot posCount / realizedPnL / pv (last 25) ===")
for s in snapshots[-25:]:
    pac = s.get('positionsAtClose') or []
    has177 = any(p.get('ticker') in ('0177.HK', '177.HK') for p in pac)
    has1585 = any(p.get('ticker') == '1585.HK' for p in pac)
    print(f"  {s['date']}  posCount={s.get('positionCount'):3d}  "
          f"realized={s.get('realizedPnL'):>12.1f}  pv={s.get('portfolioValue'):>10.0f}  "
          f"177={'Y' if has177 else '-'} 1585={'Y' if has1585 else '-'}")
