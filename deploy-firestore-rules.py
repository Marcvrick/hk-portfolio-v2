#!/usr/bin/env python3
"""
deploy-firestore-rules.py

Deploy content-protecting Firestore security rules for hk-portfolio-sync.

WHY: the live rules allow the authenticated owner to replace the whole document
(doc.set()). A stale browser tab is the authenticated owner, so it can wipe
closedTrades / snapshots / positions written after it loaded. This is the root
cause of every data-loss incident (Jun 4/5, May 28/29, Jun 11, Jun 16-24, the
Jun 25 WuXi sale + Xiaomi loss). Client-side guards can't fix it because the
offending tab runs old code. Server-side rules apply regardless of client version.

NEW INVARIANTS (owner UPDATE only; admin SDK + cron bypass rules entirely):
  - closedTrades is append-only        (size never decreases)
  - snapshots    is append-only        (size never decreases)
  - positions may grow / stay / shrink by exactly 1 (manual single delete) /
    shrink by any amount ONLY if a closedTrade was added (a real sale).
    A stale tab reverting to an old state drops several positions with no new
    trade -> REJECTED by the server.

Friend read-sharing (allowedViewers) and viewerInvites are preserved unchanged.

Runs the server-side Rules test suite (9 cases) FIRST. Deploys only with --apply
AND all tests green. Saves the previous ruleset to rules-rollback-<id>.txt.
"""
import sys, json
from google.oauth2 import service_account
import google.auth.transport.requests as gt
import requests

CRED = 'hk-portfolio-v2/hk-portfolio-sync-firebase-adminsdk-fbsvc-5beeec05f3.json'
PROJECT = 'hk-portfolio-sync'
OWNER_UID = 'cNcZwUx3nQMV96TbB1kSkQ62u8U2'
OWNER_EMAIL = 'danymontaq@gmail.com'
FRIEND_EMAIL = 'friend@example.com'
SCOPES = ['https://www.googleapis.com/auth/firebase', 'https://www.googleapis.com/auth/cloud-platform']
APPLY = '--apply' in sys.argv

# The rules are READ FROM firestore.rules, never restated here. This script used to
# carry its own inline copy of the ruleset, which silently drifted from the file it
# was supposed to deploy (caught 2026-09-08: the file had the positionDeletions
# receipt, this string still had the old unconditional shrink-by-1 allowance, so the
# test suite would have green-lit a ruleset nobody had reviewed). One source of
# truth: the file sitting next to this script.
RULES_FILE = 'firestore.rules'
with open(RULES_FILE) as fh:
    NEW_RULES = fh.read()

creds = service_account.Credentials.from_service_account_file(CRED, scopes=SCOPES)
creds.refresh(gt.Request())
H = {'Authorization': f'Bearer {creds.token}', 'Content-Type': 'application/json'}

def doc(npos, nclosed, nsnap, viewers=None, ndel=None):
    """ndel=None models a client that omits positionDeletions entirely (old cached
    JS building the outgoing document from its own field whitelist)."""
    d = {
        'positions': [{} for _ in range(npos)],
        'closedTrades': [{} for _ in range(nclosed)],
        'snapshots': [{} for _ in range(nsnap)],
    }
    if ndel is not None:
        d['positionDeletions'] = [{} for _ in range(ndel)]
    if viewers is not None:
        d['allowedViewers'] = viewers
    return d

PATH = f'/databases/(default)/documents/portfolios/{OWNER_UID}'

def tc(name, expectation, method, existing, incoming=None, auth_uid=OWNER_UID, email=OWNER_EMAIL):
    req = {
        'auth': {'uid': auth_uid, 'token': {'email': email}},
        'path': PATH,
        'method': method,
    }
    if incoming is not None:
        req['resource'] = {'data': incoming}
    case = {'expectation': expectation, 'request': req}
    if existing is not None:
        case['resource'] = {'data': existing}
    case['__name__'] = name
    return case

# Baseline existing doc: 12 positions, 32 closed, 96 snapshots, 3 delete receipts.
BASE = doc(12, 32, 96, viewers=[], ndel=3)
# A book that has never had a manual delete, to prove the bootstrap case: with an
# empty receipt log the drop is still refused, so no seeding is needed.
BASE0 = doc(12, 32, 96, viewers=[], ndel=0)
cases = [
    tc('owner add position (+1 pos)', 'ALLOW', 'update', BASE, doc(13, 32, 96, ndel=3)),
    tc('owner full sale (-1 pos, +1 trade)', 'ALLOW', 'update', BASE, doc(11, 33, 96, ndel=3)),
    tc('owner partial sale (same pos, +1 trade)', 'ALLOW', 'update', BASE, doc(12, 33, 96, ndel=3)),
    tc('owner add snapshot (+1 snap)', 'ALLOW', 'update', BASE, doc(12, 32, 97, ndel=3)),
    tc('owner idle re-save (nothing moves)', 'ALLOW', 'update', BASE, doc(12, 32, 96, ndel=3)),
    # --- the manual delete now needs a receipt (2026-09-08) ---
    tc('manual delete WITH receipt (-1 pos, +1 receipt)', 'ALLOW', 'update', BASE, doc(11, 32, 96, ndel=4)),
    tc('manual delete of 2 WITH 2 receipts', 'ALLOW', 'update', BASE, doc(10, 32, 96, ndel=5)),
    tc('THE 1138 BUG: -1 pos, no trade, NO receipt', 'DENY', 'update', BASE, doc(11, 32, 96, ndel=3)),
    tc('THE 1138 BUG on a never-deleted book', 'DENY', 'update', BASE0, doc(11, 32, 96, ndel=0)),
    tc('delete 2 with only 1 receipt', 'DENY', 'update', BASE, doc(10, 32, 96, ndel=4)),
    # --- old cached JS: omits the field entirely, so its every write must fail ---
    tc('OLD CODE omits positionDeletions (idle save)', 'DENY', 'update', BASE, doc(12, 32, 96)),
    tc('OLD CODE omits positionDeletions (drops a position)', 'DENY', 'update', BASE, doc(11, 32, 96)),
    tc('STALE tab rewinds the receipt log (-1 receipt)', 'DENY', 'update', BASE, doc(12, 32, 96, ndel=2)),
    # --- the invariants that were already live ---
    tc('STALE revert: -2 pos no trade', 'DENY', 'update', BASE, doc(10, 32, 96, ndel=3)),
    tc('STALE wipe closedTrade (-1 trade)', 'DENY', 'update', BASE, doc(12, 31, 96, ndel=3)),
    tc('STALE wipe snapshots (-5 snap)', 'DENY', 'update', BASE, doc(12, 32, 91, ndel=3)),
    tc('friend read (allowedViewers)', 'ALLOW', 'get',
       doc(12, 32, 96, viewers=[FRIEND_EMAIL], ndel=3), auth_uid='someoneElse', email=FRIEND_EMAIL),
    tc('stranger write', 'DENY', 'update', BASE, doc(13, 32, 96, ndel=3),
       auth_uid='strangerUid', email='stranger@x.com'),
]

body = {
    'source': {'files': [{'name': 'firestore.rules', 'content': NEW_RULES}]},
    'testSuite': {'testCases': [{k: v for k, v in c.items() if k != '__name__'} for c in cases]},
}
r = requests.post(f'https://firebaserules.googleapis.com/v1/projects/{PROJECT}:test',
                  headers=H, data=json.dumps(body))
print('=== test status', r.status_code, '===')
if r.status_code != 200:
    print(r.text[:1500]); raise SystemExit('test call failed')
results = r.json().get('testResults', [])
all_ok = True
for c, res in zip(cases, results):
    state = res.get('state', '?')
    ok = state == 'SUCCESS'
    all_ok = all_ok and ok
    print(f"  [{'PASS' if ok else 'FAIL'}] {c['__name__']:48s} expect={c['expectation']:5s} -> {state}")
    if not ok:
        for e in res.get('debugMessages', [])[:3]:
            print('        ', e)
print(f"\nALL TESTS {'GREEN' if all_ok else 'RED'}")

if not all_ok:
    raise SystemExit('Tests failed — NOT deploying.')

if not APPLY:
    print('\n[DRY-RUN] Tests pass. Re-run with --apply to deploy.')
    sys.exit(0)

# --- save rollback (current live ruleset) ---
rel = requests.get(f'https://firebaserules.googleapis.com/v1/projects/{PROJECT}/releases/cloud.firestore', headers=H).json()
old_name = rel.get('rulesetName')
old = requests.get(f'https://firebaserules.googleapis.com/v1/{old_name}', headers=H).json()
old_src = old.get('source', {}).get('files', [{}])[0].get('content', '')
rb = f"rules-rollback-{old_name.split('/')[-1]}.txt"
open(rb, 'w').write(old_src)
print(f"[ROLLBACK] previous ruleset saved -> {rb}  (ruleset: {old_name})")

# --- create new ruleset ---
cr = requests.post(f'https://firebaserules.googleapis.com/v1/projects/{PROJECT}/rulesets',
                   headers=H, data=json.dumps({'source': {'files': [{'name': 'firestore.rules', 'content': NEW_RULES}]}}))
print('create ruleset', cr.status_code)
if cr.status_code not in (200, 201):
    print(cr.text[:1000]); raise SystemExit('ruleset create failed')
new_name = cr.json()['name']
print('new ruleset', new_name)

# --- release (point cloud.firestore at the new ruleset) ---
upd = requests.patch(
    f'https://firebaserules.googleapis.com/v1/projects/{PROJECT}/releases/cloud.firestore',
    headers=H,
    data=json.dumps({'release': {
        'name': f'projects/{PROJECT}/releases/cloud.firestore',
        'rulesetName': new_name}}))
print('release update', upd.status_code)
if upd.status_code != 200:
    print(upd.text[:1000]); raise SystemExit('release failed')
print('\n[APPLIED] New Firestore rules are LIVE.')
