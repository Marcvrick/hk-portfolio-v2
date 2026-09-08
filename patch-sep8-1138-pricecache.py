#!/usr/bin/env python3
"""
patch-sep8-1138-pricecache.py

Fix a defect introduced by patch-sep8-add-1138.py earlier the same day.

WHAT WENT WRONG. That script seeded priceCache["1138.HK"] with the 2026-09-07
close (17.33 / previousClose 17.49) but stamped `lastUpdated` with
datetime.now(), i.e. 2026-09-08. The app's freshness gate (`isCacheFromToday`,
added 2026-07-08, see wiki/morning-stale-first-paint.md) only checks the DATE on
`lastUpdated` before rendering a cache entry as today's price. A stale price
carrying a fresh timestamp defeats it exactly. The app therefore displayed 1138
at 17.33, -0.16, -0.91% while the stock actually closed 17.99, +0.66, +3.81%.

**Rule this establishes: never write a priceCache entry whose `lastUpdated` is
newer than the price it carries.** Either stamp the timestamp of the session the
price came from, or fetch the price for the session you are stamping. A patch
that seeds a cache must do one or the other, never mix them.

WHAT THIS FIXES. priceCache["1138.HK"] and positions[].currentPrice, set from
the live TradingView scanner, the same source and endpoint update.py and the
browser use, so the values are exactly what the app would have fetched itself.

WHAT THIS DELIBERATELY DOES NOT TOUCH. The 2026-09-08 snapshot. It is
browser-minted (no settledAt) from a priceCache whose other 18 tickers are
stamped 15:49 HKT, i.e. BEFORE the 16:00 close, so every leg in it is intraday,
not just 1138. Correcting one ticker inside it would buy false precision. The
cron replaces today's snapshot wholesale from positions[] (update.py L597-604),
which is the correct repair for all 15 legs at once.

Dry-run by default. Pass --apply to write.
"""
import json
import sys
import urllib.request
from datetime import datetime, timezone, timedelta

import firebase_admin
from firebase_admin import credentials, firestore

CRED = 'hk-portfolio-v2/hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json'
DOC_ID = 'cNcZwUx3nQMV96TbB1kSkQ62u8U2'
TICKER = '1138.HK'
HKT = timezone(timedelta(hours=8))
APPLY = '--apply' in sys.argv


def tradingview_quote(code: str):
    """Same scanner endpoint update.py and index.html use."""
    body = json.dumps({
        "symbols": {"tickers": [f"HKEX:{code}"], "query": {"types": []}},
        "columns": ["close", "change_abs", "change"],
    }).encode()
    req = urllib.request.Request(
        "https://scanner.tradingview.com/hongkong/scan", data=body,
        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    d = json.load(urllib.request.urlopen(req, timeout=20))["data"][0]["d"]
    return {"close": d[0], "change_abs": d[1], "change_pct": d[2]}


q = tradingview_quote('1138')
price = round(q["close"], 4)
change = round(q["change_abs"], 4)
prev_close = round(price - change, 4)
change_pct = round(q["change_pct"], 4)

print("=== TradingView (live, the app's own source) ===")
print(f"  close={price}  change_abs={change:+}  change%={change_pct:+}  -> previousClose={prev_close}")

# Sanity gate: previousClose implied by TV must equal the stored 2026-09-07 close.
firebase_admin.initialize_app(credentials.Certificate(CRED))
db = firestore.client()
ref = db.collection('portfolios').document(DOC_ID)
doc = ref.get().to_dict()

snap_0907 = next((s for s in doc['snapshots'] if s.get('date') == '2026-09-07'), None)
stored_0907 = (snap_0907.get('closingPrices') or {}).get(TICKER) if snap_0907 else None
print(f"  stored 2026-09-07 close = {stored_0907}")
if stored_0907 is None or abs(stored_0907 - prev_close) > 0.011:
    print(f"[ABORT] TV previousClose {prev_close} disagrees with the stored 09-07 close {stored_0907}. "
          f"Do not write a cache entry that contradicts the settled record.")
    sys.exit(1)
print("  agree -> the quote is for the session after 09-07, as intended")

old_cache = (doc.get('priceCache') or {}).get(TICKER)
old_pos = next((p for p in doc['positions'] if p.get('ticker') == TICKER), None)
if old_pos is None:
    print(f"[ABORT] {TICKER} is not in positions[]."); sys.exit(1)

new_cache = {
    'success': True,
    'price': price,
    'previousClose': prev_close,
    'change': change,
    'changePercent': change_pct,
    'currency': 'HKD',
    'lastUpdated': datetime.now(HKT).isoformat(),
}

print("\n=== priceCache['1138.HK'] ===")
print(f"  before: price={old_cache and old_cache.get('price')} prev={old_cache and old_cache.get('previousClose')} "
      f"change={old_cache and old_cache.get('change')} pct={old_cache and old_cache.get('changePercent')}")
print(f"  after : price={price} prev={prev_close} change={change:+} pct={change_pct:+}")
print("\n=== positions[].currentPrice ===")
print(f"  before: {old_pos.get('currentPrice')}   after: {price}")

if not APPLY:
    print("\n[DRY-RUN] No write. Re-run with --apply to commit.")
    sys.exit(0)

price_cache = dict(doc.get('priceCache') or {})
price_cache[TICKER] = new_cache
positions = [dict(p, currentPrice=price) if p.get('ticker') == TICKER else p
             for p in doc['positions']]

ref.update({'priceCache': price_cache, 'positions': positions,
            'lastUpdated': firestore.SERVER_TIMESTAMP})
print("\n[APPLIED] Firestore updated.")

v = ref.get().to_dict()
vc = (v.get('priceCache') or {}).get(TICKER)
vp = next((p for p in v['positions'] if p.get('ticker') == TICKER), None)
ok = (abs(vc['price'] - price) < 1e-6
      and abs(vc['previousClose'] - prev_close) < 1e-6
      and abs(vc['price'] - vc['previousClose'] - vc['change']) < 1e-6
      and abs(vp['currentPrice'] - price) < 1e-6)
print(f"[VERIFY] cache price={vc['price']} prev={vc['previousClose']} change={vc['change']:+} "
      f"pct={vc['changePercent']:+} | position.currentPrice={vp['currentPrice']}")
print(f"[VERIFY] internally consistent (price - previousClose == change) and position agrees: {ok}")
print(f"[VERIFY] positions still {len(v['positions'])}, closedTrades {len(v['closedTrades'])}, "
      f"snapshots {len(v['snapshots'])}")
