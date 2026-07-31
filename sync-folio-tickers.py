#!/usr/bin/env python3
"""
sync-folio-tickers.py — Portfolio Tracker → FinMC_2 one-way sync.

Reads the live Firestore portfolio documents (HK + US) and writes a minimal
ticker snapshot to `portfolio-tickers.json` next to this script. FinMC_2's
`/api/folio` endpoint invokes this as a subprocess on demand, so the Firebase
Admin SDK state lives in a short-lived process — no init races with uvicorn's
--reload, no gRPC/proxy interference with the FastAPI lifecycle.

Output shape (portfolio-tickers.json):
{
  "updated_at": "2026-04-21T10:30:00+00:00",
  "HK": {
    "positions": [
      {"ticker": "113.HK", "name": "Dickson Concept", "quantity": 20000,
       "entry_price": 6.10, "entry_date": "2026-04-13"},
      ...
    ],
    "snapshots": [
      {"date": "2026-01-26", "value": 1040320.5},
      ...  // daily portfolio-value history, capped at SNAPSHOT_CAP_DAYS
    ]
  },
  "US": { ... }
}

Usage (standalone):
  python3 sync-folio-tickers.py
  python3 sync-folio-tickers.py --dry-run

Environment:
  FIREBASE_CREDENTIALS_PATH  override path to service-account JSON
  FOLIO_UID / FOLIO_UID_HK / FOLIO_UID_US
                             pin to a specific user doc; otherwise pick the
                             richest document in each collection.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

SCRIPT_DIR = Path(__file__).parent.resolve()
OUT_PATH = SCRIPT_DIR / "portfolio-tickers.json"
DEFAULT_CRED_PATH = (
    SCRIPT_DIR / "hk-portfolio-v2" /
    "hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json"
)
COLLECTIONS = {"HK": "portfolios", "US": "us-portfolios"}
# Cap the history series at 2 years — FinMC's chart window.
SNAPSHOT_CAP_DAYS = 365 * 2


def _init_firebase(cred_path: Path) -> None:
    import firebase_admin
    from firebase_admin import credentials
    try:
        firebase_admin.get_app()
    except ValueError:
        firebase_admin.initialize_app(credentials.Certificate(str(cred_path)))


def _pick_doc(db, collection: str, uid_override: Optional[str]) -> Dict[str, Any]:
    """Pick the Firestore doc for this market.

    If a UID override is provided, use it directly. Otherwise iterate the
    collection and return the doc with the richest positions array (matches
    update.py's "richest doc wins" pattern).
    """
    if uid_override:
        doc = db.collection(collection).document(uid_override).get()
        return (doc.to_dict() or {}) if doc.exists else {}

    best: Dict[str, Any] = {}
    best_count = -1
    for snap in db.collection(collection).stream():
        data = snap.to_dict() or {}
        positions = data.get("positions") or []
        if len(positions) > best_count:
            best = data
            best_count = len(positions)
    return best


def _cap_snapshots(snapshots: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep only the last SNAPSHOT_CAP_DAYS of daily snapshots, sorted by date."""
    if not snapshots:
        return []
    cutoff = (datetime.now(timezone.utc).date()).toordinal() - SNAPSHOT_CAP_DAYS
    rows: List[Dict[str, Any]] = []
    for s in snapshots:
        d = s.get("date")
        val = s.get("portfolioValue")
        if not d or val is None:
            continue
        try:
            date_ord = datetime.strptime(d, "%Y-%m-%d").date().toordinal()
        except ValueError:
            continue
        if date_ord < cutoff:
            continue
        rows.append({"date": d, "value": float(val)})
    rows.sort(key=lambda r: r["date"])
    return rows


def _strip(p: Dict[str, Any]) -> Dict[str, Any]:
    """Keep only the fields FinMC needs for charting + display."""
    return {
        "ticker": p.get("ticker"),
        "name": p.get("name") or "",
        "quantity": p.get("quantity"),
        "entry_price": p.get("entryPrice"),
        "entry_date": p.get("entryDate"),
    }


def main() -> int:
    dry_run = "--dry-run" in sys.argv

    cred_path = Path(os.environ.get("FIREBASE_CREDENTIALS_PATH", str(DEFAULT_CRED_PATH)))
    if not cred_path.exists():
        print(f"ERROR: credentials not found at {cred_path}", file=sys.stderr)
        return 1

    try:
        _init_firebase(cred_path)
        from firebase_admin import firestore
        db = firestore.client()
    except Exception as e:
        print(f"ERROR: firebase init failed: {e}", file=sys.stderr)
        return 2

    out: Dict[str, Any] = {"updated_at": datetime.now(timezone.utc).isoformat()}
    per_market_status: Dict[str, str] = {}

    for market, collection in COLLECTIONS.items():
        uid = os.environ.get(f"FOLIO_UID_{market}") or os.environ.get("FOLIO_UID")
        try:
            doc = _pick_doc(db, collection, uid)
            positions = doc.get("positions") or []
            snapshots = _cap_snapshots(doc.get("snapshots") or [])
            rows = [_strip(p) for p in positions if p.get("ticker")]
            out[market] = {"positions": rows, "snapshots": snapshots}
            per_market_status[market] = f"{len(rows)} pos + {len(snapshots)} snapshots"
        except Exception as e:
            print(f"WARN: {market} read failed: {e}", file=sys.stderr)
            out[market] = {"positions": [], "snapshots": []}
            per_market_status[market] = f"ERROR: {e}"

    if dry_run:
        print(json.dumps(out, indent=2))
        return 0

    tmp_path = OUT_PATH.with_suffix(OUT_PATH.suffix + ".tmp")
    tmp_path.write_text(json.dumps(out, indent=2))
    os.replace(tmp_path, OUT_PATH)

    summary = " ".join(f"{m}={per_market_status[m]}" for m in COLLECTIONS)
    print(f"Wrote {OUT_PATH} ({summary})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
