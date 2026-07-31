#!/usr/bin/env python3
"""
diagnose-resurrected.py
Find ALL positions that exist in positions[] despite having a closedTrades entry
(sold-but-reappeared, e.g. 177.HK, 1585.HK). For each, show:
  - the open-position record (qty, entry, entryDate, id)
  - every closedTrades entry for that ticker
  - which snapshots >= exitDate contain it in positionsAtClose (contamination range)
Also scans every snapshot for tickers present in pac while a closedTrade with an
earlier exitDate exists AND no re-buy is plausible (entryDate <= exitDate).
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

positions = doc.get('positions', [])
closed = doc.get('closedTrades', [])
snapshots = sorted(doc.get('snapshots', []), key=lambda s: s.get('date', ''))

closed_by_ticker = {}
for c in closed:
    closed_by_ticker.setdefault(c.get('ticker'), []).append(c)

print(f"=== open positions ({len(positions)}) ===")
for p in sorted(positions, key=lambda x: x.get('ticker', '')):
    t = p.get('ticker')
    cts = closed_by_ticker.get(t, [])
    mark = ''
    for c in cts:
        # same entryDate+entryPrice+qty as a closed trade => resurrected, not a re-buy
        same = (c.get('entryDate') == p.get('entryDate')
                and c.get('entryPrice') == p.get('entryPrice')
                and c.get('quantity') == p.get('quantity'))
        if same:
            mark = f"  <<< RESURRECTED (closed {c.get('exitDate')} @ {c.get('exitPrice')})"
        elif cts and not mark:
            mark = f"  (has prior closedTrades: {[(c.get('exitDate'), c.get('exitPrice')) for c in cts]} — check if re-buy)"
    print(f"  {t:10s} qty={p.get('quantity')} entry={p.get('entryPrice')} "
          f"entryDate={p.get('entryDate')} id={p.get('id')}{mark}")

print(f"\n=== closedTrades for 177.HK / 1585.HK ===")
for t in ('177.HK', '1585.HK', '0177.HK', '01585.HK'):
    for c in closed_by_ticker.get(t, []):
        print(f"  {t}: {c}")

# Snapshot contamination scan for suspect tickers
suspects = []
for p in positions:
    t = p.get('ticker')
    for c in closed_by_ticker.get(t, []):
        if (c.get('entryDate') == p.get('entryDate')
                and c.get('entryPrice') == p.get('entryPrice')
                and c.get('quantity') == p.get('quantity')):
            suspects.append((t, c.get('exitDate')))

print(f"\n=== snapshot contamination (suspect tickers in pac on/after their exitDate) ===")
for t, exit_date in suspects:
    dates = []
    for s in snapshots:
        d = s.get('date', '')
        if d <= exit_date:
            continue
        if any(x.get('ticker') == t for x in (s.get('positionsAtClose') or [])):
            dates.append(d)
    print(f"  {t} (exited {exit_date}): in {len(dates)} post-exit snapshots: "
          f"{dates[:3]}{' ... ' + str(dates[-3:]) if len(dates) > 6 else dates[3:]}")

print(f"\n=== priceCache entries for suspects ===")
pc = doc.get('priceCache') or {}
for t, _ in suspects:
    print(f"  {t}: {'present' if t in pc else 'absent'}")
