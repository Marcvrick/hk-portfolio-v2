#!/usr/bin/env python3
"""READ-ONLY diagnose for retroactive add of 1167.HK (bought 5100 @ 4.5 on 2026-06-03).
  - Is 1167.HK already in positions / closedTrades / any snapshot? (idempotency)
  - List every snapshot date >= 2026-06-01 with posCount/pv/capEng/dailyPnL
  - Fetch yfinance daily closes 2026-06-02..2026-06-26 + the company longName
"""
import firebase_admin
from firebase_admin import credentials, firestore

CRED = 'hk-portfolio-v2/hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json'
DOC_ID = 'cNcZwUx3nQMV96TbB1kSkQ62u8U2'
TICKER = '1167.HK'

firebase_admin.initialize_app(credentials.Certificate(CRED))
db = firestore.client()
doc = db.collection('portfolios').document(DOC_ID).get().to_dict()

positions = doc.get('positions', [])
closed = doc.get('closedTrades', [])
snapshots = sorted(doc.get('snapshots', []), key=lambda s: s.get('date', ''))

print(f"=== {TICKER} present? ===")
print("  positions:", "YES" if any(p.get('ticker') == TICKER for p in positions) else "NO (needs add)")
ct = [c for c in closed if c.get('ticker') == TICKER]
print(f"  closedTrades: {len(ct)} entr{'y' if len(ct)==1 else 'ies'}", [f"{c.get('quantity')}@{c.get('entryPrice')}->{c.get('exitPrice')} ({c.get('exitDate')})" for c in ct] if ct else "")
print(f"  open positions total: {len(positions)}")

print(f"\n=== snapshots >= 2026-06-01 ({TICKER} presence) ===")
for s in snapshots:
    d = s.get('date', '')
    if d < '2026-06-01':
        continue
    pac = s.get('positionsAtClose') or []
    has = any(x.get('ticker') == TICKER for x in pac)
    print(f"  {d}: posCount={s.get('positionCount')} pv={s.get('portfolioValue')} "
          f"capEng={s.get('capitalEngaged')} dailyPnL={s.get('dailyPnL')} "
          f"has1167={'YES' if has else 'no'} cron={'Y' if s.get('settledAt') else 'n'}")

print(f"\n=== yfinance {TICKER} daily closes 2026-06-02..2026-06-26 ===")
try:
    import yfinance as yf
    t = yf.Ticker(TICKER)
    try:
        nm = t.info.get('longName') or t.info.get('shortName')
        print(f"  name: {nm}")
    except Exception as e:
        print(f"  name: <info failed: {e}>")
    hist = t.history(start='2026-06-02', end='2026-06-27', auto_adjust=False)
    for idx, row in hist.iterrows():
        print(f"  {idx.date()}  close={round(float(row['Close']), 4)}")
except Exception as e:
    print(f"  yfinance failed: {e}")
