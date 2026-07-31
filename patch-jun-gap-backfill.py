#!/usr/bin/env python3
"""
Backfill the June 2026 snapshot gap that made the calendar repeat the same
dailyPnL across several days.

Root cause (diagnosed Jun 27 2026):
  - The cron stopped writing settled snapshots from Jun 16 to Jun 24 (10-day
    outage; only Jun 25 resumed). With no snapshots, the calendar's gap-fill
    block (index.html ~L3999) spreads the total Jun 15→Jun 25 change evenly
    across the 7 missing trading days, so each one shows the *identical*
    estimated number (~ -6752).
  - Jun 15 has a PHANTOM snapshot (settledAt=None) whose closingPrices are a
    byte-for-byte copy of Jun 12, so its dailyPnL (4441) duplicates Jun 12.

Jun 19 is an HKEX holiday (Tuen Ng) — correctly has no snapshot.
No trades occurred in the gap: same 11 positions, realizedPnL constant at 9979.

Fix: rebuild Jun 15 with its real close, and insert real settled snapshots for
Jun 16/17/18/22/23/24, each with dailyPnL = Σ(close_d − close_prevTradingDay)×qty.
Validated: recomputed Jun 25 = -6322 == stored cron value.

Idempotent. Usage: python3 patch-jun-gap-backfill.py [--dry-run]
"""
import os, sys
import firebase_admin
from firebase_admin import credentials, firestore
import yfinance as yf

DRY = "--dry-run" in sys.argv
USER = "cNcZwUx3nQMV96TbB1kSkQ62u8U2"
CRED = "hk-portfolio-v2/hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json"

# Ordered trading days. Each day's prevTradingDay = the entry before it.
# Jun 12 is the anchor (correct, untouched). Jun 19 omitted (HKEX holiday).
ANCHOR = "2026-06-12"
GAP_DAYS = ["2026-06-15", "2026-06-16", "2026-06-17", "2026-06-18",
            "2026-06-22", "2026-06-23", "2026-06-24"]
CHAIN = [ANCHOR] + GAP_DAYS + ["2026-06-25"]  # last one used only as validation

firebase_admin.initialize_app(credentials.Certificate(CRED))
db = firestore.client()
doc_ref = db.collection("portfolios").document(USER)
data = doc_ref.get().to_dict() or {}
snaps = data.get("snapshots", [])

anchor = next(s for s in snaps if s.get("date") == ANCHOR)
template_pac = anchor.get("positionsAtClose", [])  # 11 positions, entry data
qty = {p["ticker"]: p["quantity"] for p in template_pac}
realized = next(s for s in snaps if s.get("date") == "2026-06-25").get("realizedPnL", 9979)
tickers = list(qty.keys())

# --- Fetch real closes (4-digit padded fallback for 113/300) ---
def ypad(t):
    return t.replace(".HK", "").zfill(4) + ".HK"

closes = {}
for t in tickers:
    h = None
    for cand in (t, ypad(t)):
        try:
            hh = yf.Ticker(cand).history(start="2026-06-11", end="2026-06-26", auto_adjust=False)
            if len(hh) > 0:
                h = hh; break
        except Exception:
            pass
    if h is None:
        print(f"FATAL: no yfinance data for {t}"); sys.exit(1)
    closes[t] = {idx.strftime("%Y-%m-%d"): round(float(row["Close"]), 3) for idx, row in h.iterrows()}

def close_on(t, d):
    return closes[t].get(d, anchor["closingPrices"].get(t))  # anchor fallback

def build_snapshot(date, prev_date):
    new_closes, pac, pv, capital = {}, [], 0.0, 0.0
    for p in template_pac:
        tk = p["ticker"]; q = p["quantity"]; entry = p.get("entryPrice", 0)
        c = close_on(tk, date)
        new_closes[tk] = c
        pv += c * q; capital += entry * q
        pac.append({**p, "closingPrice": c, "marketValue": round(c * q, 2),
                    "pnl": round((c - entry) * q, 2),
                    "pnlPercent": round((c - entry) / entry * 100, 4) if entry else 0})
    daily = sum((close_on(tk, date) - close_on(tk, prev_date)) * qty[tk] for tk in tickers)
    return {
        "date": date,
        "closingPrices": new_closes,
        "positionsAtClose": pac,
        "portfolioValue": round(pv, 2),
        "capitalEngaged": round(capital, 2),
        "unrealizedPnL": round(pv - capital, 2),
        "realizedPnL": realized,
        "dailyPnL": round(daily, 2),
        "positionCount": len(pac),
        "settledAt": f"{date}T20:00:00+08:00",
        "sources": ["yahoo-backfill"],
        "backfilledBy": "patch-jun-gap-backfill.py",
    }

# --- Validate against the known-good Jun 25 cron value ---
v25 = build_snapshot("2026-06-25", "2026-06-24")
stored25 = next(s for s in snaps if s.get("date") == "2026-06-25").get("dailyPnL")
print(f"Validation — Jun 25 recomputed={v25['dailyPnL']} vs stored cron={stored25} "
      f"({'OK' if abs(v25['dailyPnL'] - stored25) < 1 else 'MISMATCH!'})")

# --- Build gap snapshots ---
prev = ANCHOR
new_by_date = {}
print("\nday        prevTD     dailyPnL   (was)")
for d in GAP_DAYS:
    snap = build_snapshot(d, prev)
    existing = next((s for s in snaps if s.get("date") == d), None)
    was = existing.get("dailyPnL") if existing else "(no snap)"
    print(f"{d}  {prev}  {snap['dailyPnL']:>9,.1f}   was={was}")
    new_by_date[d] = snap
    prev = d

# --- Merge: replace Jun 15, insert the rest, keep everything else ---
merged = [new_by_date.get(s["date"], s) for s in snaps]
existing_dates = {s["date"] for s in snaps}
for d in GAP_DAYS:
    if d not in existing_dates:
        merged.append(new_by_date[d])
merged.sort(key=lambda s: s.get("date", ""))

if DRY:
    print("\nDRY RUN — no writes. Snapshot count: "
          f"{len(snaps)} → {len(merged)}")
    sys.exit(0)

doc_ref.update({"snapshots": merged})
print(f"\nFirestore updated: portfolios/{USER} — snapshots {len(snaps)} → {len(merged)}")
