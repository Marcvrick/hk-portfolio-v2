#!/usr/bin/env python3
"""
patch-sep17-add-0177.py

Retroactively add 0177.HK (Jiangsu Expressway) — bought 10,000 @ 10.25 on 2026-09-17,
entered in the app but never persisted. Root cause (see wiki/incidents.md 2026-09-17):
addPosition() updates local React state + shows a "saved" checkmark on a FIXED 1.5s
timer, decoupled from the actual async saveData() write, which itself does a
server-read guard (with a possible 800ms retry) before the real Firestore commit. No
offline persistence is enabled, so a page refresh during that window aborts the
pending write outright with no error, no rollback, no banner (the JS context is torn
down before saveData can resolve). Confirmed: absent from positions[], priceCache,
positionDeletions, and today's already-settled 19:46 HKT snapshot; the only "177" hit
anywhere in the doc is the unrelated 2026-05-28 closedTrade. The live deployed rules
(ruleset updateTime 2026-09-08) require a receipt for any position departure and none
exists, which rules out a stale-tab revert this time.

Only ONE snapshot needs patching: 2026-09-17 itself, entry day, already cron-settled
(settledAt 2026-09-17T19:46:10+08:00) before positions[] carried 0177.HK, so the cron
rebuilt today's snapshot wholesale without it.

Ticker uses the padded "0177.HK" form to match the existing 2026-05-28 closedTrade
entry and TradingView/Yahoo convention -- the 2026-06-11 incident (177/1585) is exactly
what an unpadded stray key causes, and Dany's app input does not auto-pad ("177.HK" ->
".HK" suffix only, no zero-padding, per addPosition() index.html:1977-1981).

Close: raw Yahoo (auto_adjust=False) 2026-09-17 = 10.41 (2026-09-16 prevClose = 10.47).

Dry-run by default. Pass --apply to write.
"""
import sys
from datetime import datetime, timezone, timedelta
import firebase_admin
from firebase_admin import credentials, firestore

CRED = '/Users/mc/Downloads/hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json'
DOC_ID = 'cNcZwUx3nQMV96TbB1kSkQ62u8U2'
TICKER = '0177.HK'
NAME = 'Jiangsu Expressway'
QTY = 10000
ENTRY_PRICE = 10.25
ENTRY_DATE = '2026-09-17'
ENTRY_MV = round(ENTRY_PRICE * QTY, 2)   # 102,500
APPLY = '--apply' in sys.argv

CLOSE_TODAY = 10.41       # raw Yahoo close, 2026-09-17, auto_adjust=False
PREV_CLOSE = 10.47        # raw Yahoo close, 2026-09-16
SETTLED_DATES = ['2026-09-17']

firebase_admin.initialize_app(credentials.Certificate(CRED))
db = firestore.client()
ref = db.collection('portfolios').document(DOC_ID)
doc = ref.get().to_dict()
positions = list(doc.get('positions', []))

# ---- Idempotency ----
if any(p.get('ticker') == TICKER for p in positions):
    print(f"ABORT: {TICKER} already in positions. Nothing to do."); sys.exit(0)

HKT = timezone(timedelta(hours=8))
new_position = {
    'id': int(datetime(2026, 9, 17, 10, 0, tzinfo=HKT).timestamp() * 1000),
    'ticker': TICKER, 'name': NAME, 'quantity': QTY,
    'entryPrice': ENTRY_PRICE, 'entryDate': ENTRY_DATE,
    'currentPrice': CLOSE_TODAY,
}
new_positions = positions + [new_position]

# priceCache -- stamp the SESSION the price came from (today's 16:10 HKT close),
# never datetime.now(), per the 2026-09-08 1138.HK pricecache rule.
change = round(CLOSE_TODAY - PREV_CLOSE, 4)
price_cache = dict(doc.get('priceCache', {}))
price_cache[TICKER] = {
    'success': True, 'price': CLOSE_TODAY, 'previousClose': PREV_CLOSE,
    'change': change, 'changePercent': round(change / PREV_CLOSE * 100, 4),
    'currency': 'HKD',
    'lastUpdated': datetime(2026, 9, 17, 16, 10, tzinfo=HKT).isoformat(),
}

def make_leg(close):
    pnl = round((close - ENTRY_PRICE) * QTY, 2)
    return {
        'ticker': TICKER, 'name': NAME, 'quantity': QTY,
        'entryPrice': ENTRY_PRICE, 'entryDate': ENTRY_DATE,
        'closingPrice': close, 'marketValue': round(close * QTY, 2),
        'pnl': pnl, 'pnlPercent': round((close - ENTRY_PRICE) / ENTRY_PRICE * 100, 4),
    }

snapshots = list(doc.get('snapshots', []))
print(f"=== Position ===\n  add {TICKER} ({NAME}) qty={QTY} entry={ENTRY_PRICE} entryDate={ENTRY_DATE}")
print(f"  positions {len(positions)} -> {len(new_positions)}")
print(f"\n=== Snapshots patched ({SETTLED_DATES}) ===")
print(f"  {'date':12} {'close':>6} {'base':>6} {'dLeg':>9}  posCount  capEng(+{ENTRY_MV:,.0f})        pv            dailyPnL")
patched = []
touched = 0
for s in snapshots:
    d = s.get('date', '')
    if d not in SETTLED_DATES:
        patched.append(s); continue
    close = CLOSE_TODAY
    base = ENTRY_PRICE  # entry-day baseline: all shares added today, from the fill
    daily_leg = round((close - base) * QTY, 2)
    s = dict(s)
    old_pv, old_cap, old_dp, old_pc = (s.get('portfolioValue', 0), s.get('capitalEngaged', 0),
                                       s.get('dailyPnL', 0), s.get('positionCount', 0))
    s['positionCount'] = old_pc + 1
    s['portfolioValue'] = round(old_pv + close * QTY, 2)
    s['capitalEngaged'] = round(old_cap + ENTRY_MV, 2)
    s['unrealizedPnL'] = round(s['portfolioValue'] - s['capitalEngaged'], 2)
    s['dailyPnL'] = round(old_dp + daily_leg, 2)
    cp = dict(s.get('closingPrices') or {}); cp[TICKER] = close; s['closingPrices'] = cp
    pac = list(s.get('positionsAtClose') or []); pac.append(make_leg(close)); s['positionsAtClose'] = pac
    patched.append(s); touched += 1
    print(f"  {d:12} {close:6.2f} {base:6.2f} {daily_leg:+9.0f}  {old_pc}->{s['positionCount']:<3}  "
          f"{old_cap:.1f}->{s['capitalEngaged']:.1f}  {old_pv:.0f}->{s['portfolioValue']:.0f}  "
          f"{old_dp:.0f}->{s['dailyPnL']:.0f}")

print(f"\nSnapshots touched: {touched}  |  capital engaged added: {ENTRY_MV:,.0f} HKD")
if touched != len(SETTLED_DATES):
    print(f"[!] WARNING: expected {len(SETTLED_DATES)} snapshots, touched {touched}. Investigate before applying.")

if not APPLY:
    print("\n[DRY-RUN] No write. Re-run with --apply to commit."); sys.exit(0)

ref.update({'positions': new_positions, 'priceCache': price_cache,
            'snapshots': patched, 'lastUpdated': firestore.SERVER_TIMESTAMP})
print("\n[APPLIED] Firestore updated.")

# ---- Verify ----
v = ref.get().to_dict()
vp = next((p for p in v['positions'] if p.get('ticker') == TICKER), None)
print(f"[VERIFY] position: {vp['ticker']} qty={vp['quantity']} entry={vp['entryPrice']} entryDate={vp['entryDate']}")
ok = True
for s in sorted(v['snapshots'], key=lambda x: x['date']):
    if s['date'] not in SETTLED_DATES:
        continue
    pac = s.get('positionsAtClose') or []
    cap = round(sum(p.get('entryPrice', 0) * p.get('quantity', 0) for p in pac), 2)
    pv = round(sum(p.get('closingPrice', 0) * p.get('quantity', 0) for p in pac), 2)
    has = any(p.get('ticker') == TICKER for p in pac)
    cap_ok = abs(cap - s['capitalEngaged']) < 1
    pv_ok = abs(pv - s['portfolioValue']) < 1
    if not (has and cap_ok and pv_ok):
        ok = False
        print(f"[VERIFY][!] {s['date']}: has0177={has} capEng stored={s['capitalEngaged']} recomputed={cap} pv stored={s['portfolioValue']} recomputed={pv}")
print(f"[VERIFY] all patched snapshots self-consistent (capEng=Sum entry*qty, pv=Sum close*qty): {ok}")
