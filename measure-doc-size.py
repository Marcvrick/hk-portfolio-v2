#!/usr/bin/env python3
"""Read-only: size every portfolio document the way FIRESTORE charges it.

WHY THIS EXISTS (wiki/reliability-risks.md #4). The 1 MiB per-document hard limit is
the deadline this project is migrating away from, and until 2026-09-21 the only
measurement of it was a json.dumps() byte count. Firestore charges differently:

    string     len(utf-8) + 1
    number     8 bytes, whatever its decimal expansion
    bool/null  1 byte
    timestamp  8 bytes
    array      sum of its values
    map        sum of (key string size + value size)
    document   name size + sum(field name size + value size) + 32

Snapshots are almost entirely numbers, so the JSON proxy ran ~30% high: it said
734 KB and 69 sessions of headroom on the HK book where the charged size is 566 KB
and 138 sessions. Firestore exposes no per-document size in any API, so this
computation is the measurement.

    python3 measure-doc-size.py

Writes nothing. Run it before and after the snapshots-subcollection migration
(wiki/snapshots-subcollection-migration.md, phases 0 and 6).

https://firebase.google.com/docs/firestore/storage-size
"""
import json
import os
from datetime import datetime

import firebase_admin
from firebase_admin import credentials, firestore

HERE = os.path.dirname(os.path.abspath(__file__))
CRED = os.path.join(HERE, "hk-portfolio-v2",
                    "hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json")
PROJECT = "hk-portfolio-sync"
LIMIT = 1_048_576
COLLECTIONS = ("portfolios", "us-portfolios")


def str_size(s):
    return len(s.encode("utf-8")) + 1


def value_size(v):
    if v is None or isinstance(v, bool):
        return 1
    if isinstance(v, (int, float)):
        return 8
    if isinstance(v, str):
        return str_size(v)
    if isinstance(v, bytes):
        return len(v)
    if isinstance(v, datetime):
        return 8
    if isinstance(v, list):
        return sum(value_size(x) for x in v)
    if isinstance(v, dict):
        return sum(str_size(k) + value_size(x) for k, x in v.items())
    if hasattr(v, "timestamp"):  # DatetimeWithNanoseconds
        return 8
    return str_size(str(v))


def doc_name_size(*segments):
    segs = ("projects", PROJECT, "databases", "(default)", "documents") + segments
    return sum(len(s.encode()) + 1 for s in segs) + 16


def report(collection, doc_id, data):
    name = doc_name_size(collection, doc_id)
    fields = {k: str_size(k) + value_size(v) for k, v in data.items()}
    total = name + sum(fields.values()) + 32

    snaps = data.get("snapshots") or []
    snap_field = fields.get("snapshots", 0)
    per = snap_field / len(snaps) if snaps else 0
    headroom = LIMIT - total

    print(f"\n=== {collection}/{doc_id} ===")
    print(f"  charged size        {total:>9,} B  ({total / 1024:,.1f} KiB, "
          f"{100 * total / LIMIT:.1f}% of the 1 MiB limit)")
    print(f"  json.dumps() proxy  {len(json.dumps(data, default=str).encode()):>9,} B  "
          "(what wiki/reliability-risks.md used to quote)")
    if snaps:
        print(f"  snapshots field     {snap_field:>9,} B  ({100 * snap_field / total:.1f}% of the doc)")
        print(f"  entries             {len(snaps):>9,}    ({per:,.0f} B each)")
        print(f"  headroom            {headroom:>9,} B  = {int(headroom / per)} more sessions "
              f"at the current entry size")
        dates = sorted(s.get("date", "") for s in snaps)
        big = max(snaps, key=value_size)
        print(f"  date range          {dates[0]} -> {dates[-1]}")
        print(f"  largest entry       {value_size(big):,} B ({big.get('date')}, "
              f"{len(big.get('positionsAtClose') or [])} legs) = 1/{LIMIT // max(value_size(big), 1)} "
              "of the limit as its own document")
    else:
        print(f"  snapshots field     {snap_field:>9,} B  (empty)")
    for k, v in sorted(fields.items(), key=lambda kv: -kv[1]):
        if k != "snapshots" and v > 100:
            print(f"    {k:<24} {v:>9,} B")


def main():
    if not firebase_admin._apps:
        firebase_admin.initialize_app(credentials.Certificate(CRED))
    db = firestore.client()
    for coll in COLLECTIONS:
        for d in db.collection(coll).stream():
            report(coll, d.id, d.to_dict() or {})
    print("\nNothing was written.")


if __name__ == "__main__":
    main()
