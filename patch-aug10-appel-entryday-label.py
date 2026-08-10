#!/usr/bin/env python3
"""
patch-aug10-appel-entryday-label.py

Follow-up to patch-aug10-fix-appel-ticker.py, which deliberately left the entry-day
snapshot (2026-07-21) untouched so its stored close of 327.96 — plausibly the real
browser-side fill — would not be overwritten with Yahoo's 327.74.

That left the label behind too. 2026-07-21 still carries `APPEL` in closingPrices,
positionsAtClose and priceProvenance, while 07-22 onward and positions[] now say
`AAPL`. Consequences:

  - The History tab's record-integrity check reads APPEL as leaving the book between
    07-21 and 07-22 with no sale, so the US card reports 9 unexplained exits instead
    of the 8 real ones and mis-states the correction (-946.10 instead of -1,205.30).
  - Any future audit that pivots on ticker sees a one-day ghost holding.

This is a RENAME ONLY. No price, no quantity, no derived total changes: the entry-day
close stays 327.96 exactly as the previous patch intended. The script asserts that
every numeric field is bit-identical before and after, and aborts if any moves.

Dry-run by default. Writes only with --apply.
"""
import sys
import firebase_admin
from firebase_admin import credentials, firestore

APPLY = '--apply' in sys.argv

CRED = 'hk-portfolio-v2/hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json'
DOC_ID = 'JJDY5whY9vNmCcRsi8kafMHZbmD2'
OLD, NEW, NAME = 'APPEL', 'AAPL', 'Apple'
DATE = '2026-07-21'
EXPECTED_CLOSE = 327.96

NUMERIC = ('portfolioValue', 'capitalEngaged', 'unrealizedPnL', 'realizedPnL',
           'dailyPnL', 'positionCount', 'totalDividends', 'dividendIncomeToday')

firebase_admin.initialize_app(credentials.Certificate(CRED))
db = firestore.client()
ref = db.collection('us-portfolios').document(DOC_ID)
doc = ref.get().to_dict()

snaps = sorted(doc.get('snapshots', []), key=lambda s: s['date'])
snap = next((s for s in snaps if s['date'] == DATE), None)
if snap is None:
    sys.exit(f"ABORT: no snapshot for {DATE}.")

cp = snap.get('closingPrices') or {}
pac = snap.get('positionsAtClose') or []
prov = snap.get('priceProvenance') or {}

# ---------------------------------------------------------------- idempotency
if OLD not in cp and not any(p.get('ticker', '').upper() == OLD for p in pac):
    sys.exit(f"ABORT (idempotency): {OLD} already absent from the {DATE} snapshot.")
if NEW in cp or any(p.get('ticker', '').upper() == NEW for p in pac):
    sys.exit(f"ABORT: {NEW} already present in the {DATE} snapshot — would collide.")
if abs(cp.get(OLD, 0) - EXPECTED_CLOSE) > 1e-6:
    sys.exit(f"ABORT: stored close {cp.get(OLD)} != expected {EXPECTED_CLOSE}. Re-diagnose.")
if any(s['date'] != DATE and OLD in (s.get('closingPrices') or {}) for s in snaps):
    sys.exit(f"ABORT: {OLD} still present on other dates — run patch-aug10-fix-appel-ticker.py first.")
if not any(p['ticker'].upper() == NEW for p in doc.get('positions', [])):
    sys.exit(f"ABORT: positions[] does not hold {NEW} — run the main patch first.")

old_pos = next(p for p in pac if p.get('ticker', '').upper() == OLD)
before = {k: snap.get(k) for k in NUMERIC}

# ------------------------------------------------------------------ rename only
new_pac = [dict(p, ticker=NEW, name=NAME) if p.get('ticker', '').upper() == OLD else p
           for p in pac]
new_cp = {(NEW if k.upper() == OLD else k): v for k, v in cp.items()}
new_prov = {(NEW if k.upper() == OLD else k): v for k, v in prov.items()}

# ------------------------------------------------------------------ prove nothing moved
pv = sum(p.get('closingPrice', 0) * p.get('quantity', 0) for p in new_pac)
cap = sum(p.get('entryPrice', 0) * p.get('quantity', 0) for p in new_pac)
print(f"{DATE} — rename {OLD} -> {NEW} ({NAME}), close stays {EXPECTED_CLOSE}\n")
print(f"  {'field':<20}{'stored':>14}{'recomputed':>14}   status")
for label, stored, recomputed in (
        ('portfolioValue', snap.get('portfolioValue'), pv),
        ('capitalEngaged', snap.get('capitalEngaged'), cap),
        ('unrealizedPnL', snap.get('unrealizedPnL'), pv - cap),
        ('positionCount', snap.get('positionCount'), len(new_pac))):
    ok = abs((stored or 0) - recomputed) < 0.01
    print(f"  {label:<20}{stored:>14,.2f}{recomputed:>14,.2f}   {'unchanged' if ok else 'DRIFT'}")
print(f"  {'dailyPnL':<20}{snap.get('dailyPnL'):>14,.2f}{snap.get('dailyPnL'):>14,.2f}   untouched")
print(f"  {'realizedPnL':<20}{snap.get('realizedPnL'):>14,.2f}{snap.get('realizedPnL'):>14,.2f}   untouched")
print(f"\n  closingPrices keys : {sorted(cp)} -> {sorted(new_cp)}")
print(f"  position           : {old_pos.get('ticker')} qty {old_pos.get('quantity')} "
      f"entry {old_pos.get('entryPrice')} close {old_pos.get('closingPrice')} -> ticker {NEW}, rest identical")
print(f"  provenance keys    : {sorted(prov)} -> {sorted(new_prov)}")
print(f"  provisional        : {snap.get('provisional')} (unchanged — the entry-day price was never a MISS)")

if any(abs((before[k] or 0) - (snap.get(k) or 0)) > 1e-9 for k in NUMERIC):
    sys.exit("ABORT: a numeric field moved during planning — this must be a pure rename.")

if not APPLY:
    print("\n[DRY-RUN] No write performed. Re-run with --apply to write.")
    sys.exit(0)

# ------------------------------------------------------------------ apply
new_snaps = []
for s in snaps:
    if s['date'] == DATE:
        s = dict(s)
        s['positionsAtClose'] = new_pac
        s['closingPrices'] = new_cp
        s['priceProvenance'] = new_prov
    new_snaps.append(s)
ref.update({'snapshots': new_snaps})
print("\n[APPLIED] snapshots[] updated (label only).\n")

# ------------------------------------------------------------------ verify
fresh = next(s for s in ref.get().to_dict()['snapshots'] if s['date'] == DATE)
fcp = fresh.get('closingPrices') or {}
fpac = fresh.get('positionsAtClose') or []
fpv = sum(p.get('closingPrice', 0) * p.get('quantity', 0) for p in fpac)
fcap = sum(p.get('entryPrice', 0) * p.get('quantity', 0) for p in fpac)
checks = {
    f'{NEW} in closingPrices, no {OLD}': fcp.get(NEW) == EXPECTED_CLOSE and OLD not in fcp,
    f'{NEW} in positionsAtClose, no {OLD}': (any(p.get('ticker') == NEW for p in fpac)
                                             and not any(p.get('ticker') == OLD for p in fpac)),
    'cp keys = pac tickers': set(fcp) == {p.get('ticker') for p in fpac},
    'pv = S(close x qty)': abs(fresh.get('portfolioValue', 0) - fpv) < 0.01,
    'cap = S(entry x qty)': abs(fresh.get('capitalEngaged', 0) - fcap) < 0.01,
    'unreal = pv - cap': abs(fresh.get('unrealizedPnL', 0) - (fpv - fcap)) < 0.01,
    'posCount = len(pac)': fresh.get('positionCount') == len(fpac),
    'every numeric field unchanged': all(abs((before[k] or 0) - (fresh.get(k) or 0)) < 1e-9 for k in NUMERIC),
}
print("[VERIFY]")
for k, v in checks.items():
    print(f"  {'OK  ' if v else 'FAIL'} {k}")
ok = all(checks.values())
print("\n[VERIFY] pure rename confirmed, no value moved." if ok else "\n[VERIFY] FAILURES ABOVE.")
sys.exit(0 if ok else 1)
