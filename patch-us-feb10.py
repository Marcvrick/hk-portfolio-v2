#!/usr/bin/env python3
"""Calculate Feb 10 dailyPnL from Yahoo (Monday close vs Friday close) and store it."""
import json, os, ssl, urllib.request
from datetime import datetime, timezone

ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE
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

feb10 = next((s for s in snapshots if s["date"] == "2026-02-10"), None)
if not feb10:
    print("ERROR: No Feb 10 snapshot")
    exit(1)

positions_at_close = feb10.get("positionsAtClose", [])
closing_prices = feb10.get("closingPrices", {})

print("=== Calculating Feb 10 daily P&L (Monday close vs Friday close) ===\n")

daily_pnl = 0
for pos in positions_at_close:
    ticker = pos["ticker"]
    monday_close = closing_prices.get(ticker)
    qty = pos["quantity"]

    if monday_close is None:
        print(f"  {ticker}: no Monday close, skipping")
        continue

    # Fetch Yahoo to get Friday's close
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=10d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15, context=ssl_ctx) as resp:
            ydata = json.loads(resp.read().decode())
    except Exception as e:
        print(f"  {ticker}: FAIL {e}")
        continue

    result = ydata.get("chart", {}).get("result", [None])[0]
    if not result:
        print(f"  {ticker}: no result")
        continue

    timestamps = result.get("timestamp", [])
    closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])

    # Find Friday Feb 6 close (last close before Monday Feb 9 UTC midnight)
    # Feb 10 is Monday, so we need the close before Feb 10 00:00 UTC
    # Actually, Feb 10 2026 is Tuesday. Let me find the close on Feb 9 (Monday)
    # Wait - let me just find the close for the day BEFORE Feb 10's close
    # Strategy: find Feb 10's bar, then take the one before it

    # Find the bar that corresponds to Feb 10
    feb10_idx = None
    for i, ts in enumerate(timestamps):
        bar_date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        if bar_date == "2026-02-10":
            feb10_idx = i
            break

    if feb10_idx is None or feb10_idx == 0:
        print(f"  {ticker}: can't find Feb 10 bar or no previous bar")
        continue

    # Previous trading day's close = the bar before Feb 10
    prev_close = None
    for i in range(feb10_idx - 1, -1, -1):
        if closes[i] is not None:
            prev_date = datetime.fromtimestamp(timestamps[i], tz=timezone.utc).strftime("%Y-%m-%d")
            prev_close = closes[i]
            break

    if prev_close is None:
        print(f"  {ticker}: no previous close found")
        continue

    pos_pnl = (monday_close - prev_close) * qty
    daily_pnl += pos_pnl
    print(f"  {ticker}: ({monday_close} - {prev_close}) × {qty} = {pos_pnl:+.1f}  [prev={prev_date}]")

daily_pnl = round(daily_pnl, 2)
print(f"\n=== Feb 10 daily P&L = {daily_pnl:+.2f} ===")

# Store it
for i, s in enumerate(snapshots):
    if s["date"] == "2026-02-10":
        snapshots[i]["dailyPnL"] = daily_pnl
        break

doc_ref.update({"snapshots": snapshots})
print(f"Saved to Firestore.")
