#!/usr/bin/env python3
"""
Daily portfolio updater for Firebase Firestore.
Fetches TradingView prices for all positions, updates priceCache and saves a daily snapshot.
Designed to run via GitHub Actions cron at HK market close (16:30 HKT = 08:30 UTC).
"""

import json
import os
import ssl
import sys
from datetime import datetime, timezone, timedelta
import urllib.request

# Firebase Admin SDK
import firebase_admin
from firebase_admin import credentials, firestore

from market_calendar import is_trading_day, coverage_warning, HKEX_HOLIDAYS

HKT = timezone(timedelta(hours=8))
COLLECTION = "portfolios"

# Snapshot-validity window: the CAS auction ends 16:10 HKT; before that TV
# serves intraday/pre-CAS prints. After midnight HKT a drifted GitHub Actions
# run would compute the WRONG `today` and stamp yesterday's prices on it.
# So: only write snapshots between WINDOW_START and midnight, HKT.
# Override for manual reruns: ALLOW_OFF_HOURS=1.
WINDOW_START = "16:10"


def init_firebase():
    """Initialize Firebase Admin SDK."""
    # Check for credentials file path in environment variable
    cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")

    if cred_path and os.path.exists(cred_path):
        # Use credentials file
        cred = credentials.Certificate(cred_path)
    elif os.environ.get("FIREBASE_CREDENTIALS_JSON"):
        # Use credentials from environment variable (for GitHub Actions)
        cred_json = json.loads(os.environ.get("FIREBASE_CREDENTIALS_JSON"))
        cred = credentials.Certificate(cred_json)
    else:
        print("ERROR: No Firebase credentials found.")
        print("Set GOOGLE_APPLICATION_CREDENTIALS path or FIREBASE_CREDENTIALS_JSON content.")
        sys.exit(1)

    firebase_admin.initialize_app(cred)
    return firestore.client()


def fetch_tradingview_prices():
    """Fetch all HKEX prices in one bulk call via TradingView Scanner API.

    Returns dict: { "1913.HK": close_price, "0285.HK": close_price, ... }
    TradingView returns codes without zero-padding (e.g. "285"),
    so we store both padded and unpadded versions for flexible lookup.
    """
    payload = {
        "columns": ["name", "open", "high", "low", "close", "change", "change_abs", "volume"],
        "range": [0, 25000],
        "sort": {"sortBy": "name", "sortOrder": "asc"},
    }
    req = urllib.request.Request(
        "https://scanner.tradingview.com/hongkong/scan",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"  FAIL TradingView bulk fetch: {e}")
        return {}

    prices = {}
    skipped = 0
    for item in data.get("data", []):
        parts = item["s"].split(":")
        code = parts[1]  # e.g. "1913"
        d = item["d"]
        # columns: name, open, high, low, close, change, change_abs, volume
        close = d[4]
        if close is None:
            skipped += 1
            continue
        change_pct = d[5]   # % change from previous close
        change_abs = d[6]   # absolute change from previous close
        # Store as both "1913.HK" and "01913.HK" (zero-padded to 4 digits) for flexible lookup
        ticker_raw = f"{code}.HK"
        ticker_padded = f"{code.zfill(4)}.HK"
        entry = {
            "close": close,
            "changePercent": change_pct,
            "changeAbs": change_abs,
        }
        prices[ticker_raw] = entry
        prices[ticker_padded] = entry

    total = data.get("totalCount", len(prices) // 2)
    if skipped:
        print(f"  Skipped {skipped} tickers with no close price")
    print(f"  TradingView: {total} HK tickers fetched")
    return prices


# --- Yahoo Finance reconciliation source ---
# Used to cross-check TradingView's CAS print against the official exchange
# settlement. TV scanner at 16:30 HKT (and even at 16:45) can return the last
# traded price BEFORE the closing auction settles — Yahoo derives close from
# HKEX's published settlement, so it's the secondary source of truth.
RECONCILE_TOLERANCE_PCT = 0.5    # 0.5% — bigger gap = use Yahoo
RECONCILE_TOLERANCE_ABS = 0.05   # 0.05 HKD — bigger gap = use Yahoo


def _yahoo_close_for(ticker_clean: str, target_date: str):
    """Return Yahoo's daily close for `target_date` ('YYYY-MM-DD' in HKT) or None.

    Tries multiple ticker formats because Yahoo's HK listings inconsistently
    accept zero-padded vs unpadded codes.
    """
    base = ticker_clean.replace(".HK", "")
    # Try unpadded, 4-digit padded, 5-digit padded; dedupe
    candidates = []
    for c in [f"{base}.HK", f"{base.lstrip('0')}.HK", f"{base.zfill(4)}.HK", f"{base.zfill(5)}.HK"]:
        if c not in candidates:
            candidates.append(c)

    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()

    for cand in candidates:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{cand}?interval=1d&range=10d"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
                data = json.loads(resp.read())
        except Exception:
            continue
        try:
            result = data["chart"]["result"][0]
            timestamps = result["timestamp"]
            closes = result["indicators"]["quote"][0]["close"]
        except (KeyError, IndexError, TypeError):
            continue
        for i, ts in enumerate(timestamps):
            dt = datetime.fromtimestamp(ts, HKT).strftime("%Y-%m-%d")
            if dt == target_date and closes[i] is not None:
                return float(closes[i])
    return None


def reconcile_with_yahoo(tv_prices: dict, positions: list, target_date: str) -> dict:
    """For each held ticker, fetch Yahoo's close and reconcile against TV.

    Returns provenance dict: { ticker: {source, tvClose, yahooClose, chosen, drift, provisional} }
    Mutates tv_prices in place — replaces close/changeAbs when Yahoo wins.
    """
    print(f"  Yahoo reconciliation for {len(positions)} held tickers...")
    provenance = {}
    for p in positions:
        clean = p["ticker"].replace("b.HK", ".HK")
        tv_entry = tv_prices.get(clean)
        if tv_entry is None:
            provenance[clean] = {"source": "missing", "provisional": True}
            continue
        tv_close = tv_entry["close"]
        yahoo_close = _yahoo_close_for(clean, target_date)
        if yahoo_close is None:
            # Yahoo unreachable — keep TV but flag as provisional
            provenance[clean] = {
                "source": "tv-only",
                "tvClose": tv_close,
                "yahooClose": None,
                "chosen": tv_close,
                "drift": None,
                "provisional": True,
            }
            print(f"  ?? {clean}: Yahoo unreachable, keeping TV {tv_close} (provisional)")
            continue

        drift = tv_close - yahoo_close
        drift_pct = (abs(drift) / yahoo_close * 100) if yahoo_close else 0
        gap_too_large = abs(drift) > RECONCILE_TOLERANCE_ABS or drift_pct > RECONCILE_TOLERANCE_PCT

        if gap_too_large:
            # Yahoo is exchange-aligned — prefer it. Patch tv_prices so downstream
            # logic (priceCache, snapshot, dailyPnL) uses the reconciled value.
            tv_entry["close"] = yahoo_close
            # Keep TV's previous-close baseline by adjusting changeAbs/changePercent
            tv_change_abs = tv_entry.get("changeAbs")
            if tv_change_abs is not None:
                # Original prevClose = tv_close - tv_change_abs; recompute change vs that.
                prev_close = tv_close - tv_change_abs
                new_change_abs = round(yahoo_close - prev_close, 4)
                tv_entry["changeAbs"] = new_change_abs
                tv_entry["changePercent"] = round((new_change_abs / prev_close) * 100, 4) if prev_close else 0
            provenance[clean] = {
                "source": "yahoo-reconciled",
                "tvClose": tv_close,
                "yahooClose": yahoo_close,
                "chosen": yahoo_close,
                "drift": round(drift, 4),
                "provisional": False,
            }
            print(f"  !! {clean}: TV={tv_close} Yahoo={yahoo_close} drift={drift:+.4f} ({drift_pct:.2f}%) -> using Yahoo")
        else:
            provenance[clean] = {
                "source": "tv+yahoo",
                "tvClose": tv_close,
                "yahooClose": yahoo_close,
                "chosen": tv_close,
                "drift": round(drift, 4),
                "provisional": False,
            }

    n_yahoo = sum(1 for v in provenance.values() if v["source"] == "yahoo-reconciled")
    n_provisional = sum(1 for v in provenance.values() if v.get("provisional"))
    print(f"  Reconciliation: {n_yahoo} corrected to Yahoo, {n_provisional} provisional")
    return provenance


# --- Yahoo Finance (disabled, kept as fallback) ---
# def fetch_yahoo_price(ticker: str) -> dict:
#     """Fetch price from Yahoo Finance chart API (no CORS needed server-side)."""
#     clean = ticker.replace("b.HK", ".HK")
#     url = f"https://query1.finance.yahoo.com/v8/finance/chart/{clean}?interval=1d&range=5d"
#     req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
#     try:
#         with urllib.request.urlopen(req, timeout=15) as resp:
#             data = json.loads(resp.read().decode())
#     except Exception as e:
#         return {"success": False, "error": str(e)}
#     result = data.get("chart", {}).get("result", [None])[0]
#     if not result:
#         return {"success": False, "error": "No data"}
#     meta = result.get("meta", {})
#     price = meta.get("regularMarketPrice")
#     if price is None:
#         return {"success": False, "error": "No price"}
#     timestamps = result.get("timestamp", [])
#     closes_list = (result.get("indicators", {}).get("quote", [{}])[0].get("close") or [])
#     today_utc_start = int(datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
#     previous_close = None
#     for i in range(len(timestamps) - 1, -1, -1):
#         if closes_list[i] is not None and timestamps[i] < today_utc_start:
#             previous_close = closes_list[i]
#             break
#     if not previous_close:
#         previous_close = meta.get("previousClose") or meta.get("chartPreviousClose") or price
#     return {
#         "success": True, "price": price, "previousClose": previous_close,
#         "change": round(price - previous_close, 4),
#         "changePercent": round(((price - previous_close) / previous_close) * 100, 4) if previous_close else 0,
#         "currency": meta.get("currency", "HKD"),
#         "lastUpdated": datetime.now(HKT).isoformat(),
#     }


def update_portfolio(db, doc_ref, user_id: str, today: str, tv_prices: dict):
    """Update a single user's portfolio using TradingView prices."""
    print(f"\n--- Updating portfolio for user: {user_id} ---")

    doc = doc_ref.get()
    if not doc.exists:
        print(f"  Document not found, skipping")
        return False

    data = doc.to_dict()

    positions = data.get("positions", [])
    price_cache = data.get("priceCache", {})
    snapshots = data.get("snapshots", [])
    closed_trades = data.get("closedTrades", [])
    transactions = data.get("transactions", [])

    if not positions:
        print("  No positions, skipping")
        return False

    print(f"  Positions: {len(positions)}")

    # Get yesterday's closingPrices for previousClose calculation
    yesterday_closing = {}
    for s in sorted(snapshots, key=lambda x: x["date"], reverse=True):
        if s["date"] < today:
            yesterday_closing = s.get("closingPrices", {})
            break

    # 0. Cross-check TradingView against Yahoo (settlement source of truth).
    # Mutates tv_prices in place when Yahoo and TV disagree beyond tolerance.
    price_provenance = reconcile_with_yahoo(tv_prices, positions, today)

    # 1. Match TradingView prices to portfolio positions
    print("  Matching TradingView prices...")
    matched = 0
    for p in positions:
        ticker = p["ticker"]
        clean = ticker.replace("b.HK", ".HK")
        # Try direct lookup (handles both "1913.HK" and "0285.HK" via padded keys)
        tv_entry = tv_prices.get(clean)
        if tv_entry is None:
            print(f"  MISS {clean}: not found in TradingView data")
            continue
        price = tv_entry["close"]
        tv_change_pct = tv_entry.get("changePercent")
        tv_change_abs = tv_entry.get("changeAbs")
        # Use TradingView's official change values (most reliable source)
        # Fall back to snapshot-based calculation only if TradingView didn't provide them
        if tv_change_abs is not None:
            prev_close = round(price - tv_change_abs, 4)
            change_abs = round(tv_change_abs, 4)
            change_pct = round(tv_change_pct, 4) if tv_change_pct is not None else (round((tv_change_abs / prev_close) * 100, 4) if prev_close else 0)
        else:
            prev_close = yesterday_closing.get(clean, price)
            change_abs = round(price - prev_close, 4)
            change_pct = round((change_abs / prev_close) * 100, 4) if prev_close else 0
        price_cache[clean] = {
            "success": True,
            "price": price,
            "previousClose": prev_close,
            "change": change_abs,
            "changePercent": change_pct,
            "currency": "HKD",
            "lastUpdated": datetime.now(HKT).isoformat(),
        }
        p["currentPrice"] = price
        matched += 1
        print(f"  OK {clean}: {price} (prevClose: {prev_close}, chg: {change_pct}%)")
    print(f"  Matched {matched}/{len(positions)} positions")

    # 2. Calculate snapshot
    current_value = sum(p["quantity"] * p.get("currentPrice", p.get("entryPrice", 0)) for p in positions)
    capital_engaged = sum(p["quantity"] * p.get("entryPrice", 0) for p in positions)
    realized_pnl = sum((t.get("exitPrice", 0) - t.get("entryPrice", 0)) * t.get("quantity", 0) for t in closed_trades)
    total_dividends = sum(t.get("amount", 0) for t in transactions if t.get("type") == "dividend")

    # Build closingPrices map and positionsAtClose for accurate calendar P&L
    closing_prices = {}
    positions_at_close = []
    for p in positions:
        clean = p["ticker"].replace("b.HK", ".HK")
        cur_price = p.get("currentPrice") or p.get("entryPrice", 0)
        closing_prices[clean] = cur_price
        positions_at_close.append({
            "ticker": p["ticker"],
            "name": p.get("name", ""),
            "quantity": p["quantity"],
            "entryPrice": p.get("entryPrice", 0),
            "entryDate": p.get("entryDate", ""),
            "closingPrice": cur_price,
            "marketValue": cur_price * p["quantity"],
            "pnl": (cur_price - p.get("entryPrice", 0)) * p["quantity"],
            "pnlPercent": ((cur_price - p.get("entryPrice", 0)) / p["entryPrice"] * 100) if p.get("entryPrice") else 0,
        })

    # Calculate dailyPnL from yesterday's snapshot closingPrices
    yesterday_snap = None
    for s in sorted(snapshots, key=lambda x: x["date"], reverse=True):
        if s["date"] < today:
            yesterday_snap = s
            break

    # dailyPnL uses TradingView's change_abs * quantity as the primary source.
    # Why: TV's change_abs is the difference between today's close and TV's official
    # previous-session close. Using yesterday's stored snapshot closingPrices was
    # unreliable — at 16:30 HKT cron time TV Scanner can return the latest Closing
    # Auction Session trade rather than the settled close, so stored closingPrices
    # can be 1-12 cents off. Source-of-truth for dailyPnL is the TV change, not
    # yesterday's saved field. Apr 24 2026 incident: stored dailyPnL=9720 but TV
    # change_abs sum was 6314 — Performance tab and calendar diverged by 3586 HKD.
    daily_pnl = 0
    yesterday_closing = yesterday_snap.get("closingPrices", {}) if yesterday_snap else {}
    for p in positions:
        clean = p["ticker"].replace("b.HK", ".HK")
        cur_price = p.get("currentPrice", p.get("entryPrice", 0))
        tv_entry = tv_prices.get(clean) or {}
        tv_change_abs = tv_entry.get("changeAbs")
        if p.get("entryDate") == today:
            # Entirely new position added today: use entry price as baseline
            daily_pnl += (cur_price - p.get("entryPrice", 0)) * p["quantity"]
        elif p.get("addedTodayDate") == today and p.get("addedTodayQty", 0) > 0 and p.get("qtyBeforeToday", 0) > 0:
            # Existing position with intraday addition: split calculation
            old_qty = p["qtyBeforeToday"]
            added_qty = p["addedTodayQty"]
            added_price = p.get("addedTodayPrice", 0)
            if tv_change_abs is not None:
                daily_pnl += tv_change_abs * old_qty
            else:
                prev_close = yesterday_closing.get(clean)
                if prev_close is not None:
                    daily_pnl += (cur_price - prev_close) * old_qty
            daily_pnl += (cur_price - added_price) * added_qty
        else:
            # Standard position: use TV change_abs (authoritative).
            if tv_change_abs is not None:
                daily_pnl += tv_change_abs * p["quantity"]
            else:
                # Fallback only if TV did not return change_abs for this ticker.
                prev_close = yesterday_closing.get(clean)
                if prev_close is not None:
                    daily_pnl += (cur_price - prev_close) * p["quantity"]
    # Add today's closed-position contribution: (exitPrice − prev_trading_day_close) × qty.
    # Do NOT use (realized_pnl - yesterday_realized): that adds the full entry-to-exit profit,
    # which overcounts all prior sessions' unrealized gains already captured in previous dailyPnL tiles.
    # prev close baseline = TV's official previous-session close (close − change_abs), the same
    # source the held-position legs use. Yesterday's stored snapshot close is only a fallback:
    # when the last snapshot is older than one trading day (gap), it is days stale — the exact
    # error class behind the Jun 9 2026 over-correction (wiki/dailypnl-formula.md rule 5).
    for t in closed_trades:
        if t.get("exitDate") != today:
            continue
        clean = t["ticker"].replace("b.HK", ".HK")
        tv_entry = tv_prices.get(clean) or {}
        tv_close, tv_change_abs = tv_entry.get("close"), tv_entry.get("changeAbs")
        if tv_close is not None and tv_change_abs is not None:
            prev_close = tv_close - tv_change_abs  # prior trading-day close, gap-proof
        else:
            prev_close = yesterday_closing.get(clean)
        if prev_close is not None:
            daily_pnl += (t.get("exitPrice", 0) - prev_close) * t.get("quantity", 0)
        elif t.get("entryDate") == today:
            # Opened and closed same session: gain is exit − entry
            daily_pnl += (t.get("exitPrice", 0) - t.get("entryPrice", 0)) * t.get("quantity", 0)
        # else: no prev_close available at all — skip; can't compute session contribution

    if not yesterday_snap:
        # No yesterday snapshot — fall back to total unrealized
        daily_pnl = round(current_value - capital_engaged, 2)

    # Provenance: snapshot is "settled" only if every held ticker was reconciled
    # against Yahoo. If Yahoo was unreachable for any ticker, the whole snapshot
    # is marked provisional so the UI can flag it.
    n_provisional_tickers = sum(1 for v in price_provenance.values() if v.get("provisional"))
    snapshot = {
        "date": today,
        "capitalEngaged": round(capital_engaged, 2),
        "portfolioValue": round(current_value, 2),
        "unrealizedPnL": round(current_value - capital_engaged, 2),
        "realizedPnL": round(realized_pnl, 2),
        "totalDividends": round(total_dividends, 2),
        "positionCount": len(positions),
        "closingPrices": closing_prices,
        "dailyPnL": round(daily_pnl, 2),
        "positionsAtClose": positions_at_close,
        "settledAt": datetime.now(HKT).isoformat(),
        "sources": ["tradingview", "yahoo"],
        "provisional": n_provisional_tickers > 0,
        "priceProvenance": price_provenance,  # per-ticker source/drift breakdown
    }

    # Replace today's snapshot if exists, otherwise append
    existing_idx = next((i for i, s in enumerate(snapshots) if s["date"] == today), None)
    if existing_idx is not None:
        snapshots[existing_idx] = snapshot
        print(f"  Updated existing snapshot for {today}")
    else:
        snapshots.append(snapshot)
        snapshots.sort(key=lambda s: s["date"])
        print(f"  New snapshot for {today}")

    print(f"  Value: {current_value:,.0f} HKD | Capital: {capital_engaged:,.0f} HKD | P&L: {current_value - capital_engaged:,.0f} HKD")

    # Clean up intraday addition fields (no longer needed after snapshot)
    for p in positions:
        for field in ["addedTodayDate", "addedTodayQty", "addedTodayPrice", "qtyBeforeToday"]:
            p.pop(field, None)

    # 3. Save to Firestore
    update_data = {
        "priceCache": price_cache,
        "positions": positions,
        "snapshots": snapshots,
        "lastUpdated": firestore.SERVER_TIMESTAMP,
    }

    doc_ref.update(update_data)
    print(f"  Saved to Firestore ({len(snapshots)} snapshots)")
    return True


def run():
    # Initialize Firestore
    print("Connecting to Firestore...")
    db = init_firebase()

    now_hkt = datetime.now(HKT)
    today = now_hkt.strftime("%Y-%m-%d")
    print(f"=== HK Portfolio Update {today} ===")

    warn = coverage_warning(today)
    if warn:
        print(warn)

    if not is_trading_day(today, "hk"):
        weekday = datetime.strptime(today, "%Y-%m-%d").strftime("%A")
        reason = "holiday" if today in HKEX_HOLIDAYS else "weekend"
        print(f"  Skipping — {weekday} {today} is a {reason} (HKEX closed)")
        print("=== Done: No updates ===")
        return

    # Time-window guard: refuse to snapshot before the CAS settles. This also
    # neutralises a GitHub Actions run that drifts past midnight HKT — it would
    # arrive here with the NEXT day's date and pre-open prices, and abort
    # instead of writing a corrupt snapshot.
    if os.environ.get("ALLOW_OFF_HOURS") != "1" and now_hkt.strftime("%H:%M") < WINDOW_START:
        print(f"  Skipping — {now_hkt.strftime('%H:%M')} HKT is before {WINDOW_START} (CAS not settled; "
              "a drifted run from yesterday's schedule lands here too). Set ALLOW_OFF_HOURS=1 to override.")
        print("=== Done: No updates ===")
        return

    # Fetch all HKEX prices in one bulk call
    print("Fetching TradingView HKEX prices...")
    tv_prices = fetch_tradingview_prices()
    if not tv_prices:
        print("ERROR: No prices from TradingView — aborting")
        sys.exit(1)  # red run, not a silent green skip

    # Get all user portfolios in the portfolios collection
    collection_ref = db.collection(COLLECTION)
    docs = collection_ref.stream()

    updated_count = 0
    for doc in docs:
        user_id = doc.id
        doc_ref = collection_ref.document(user_id)
        if update_portfolio(db, doc_ref, user_id, today, tv_prices):
            updated_count += 1

    print(f"\n=== Done: Updated {updated_count} portfolio(s) ===")


if __name__ == "__main__":
    run()
