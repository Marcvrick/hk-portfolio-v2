// Test firestore.rules against the REAL rules engine, via the Firestore emulator.
//
// WHY THIS EXISTS: deploy-firestore-rules.py calls the firebaserules.googleapis.com
// :test endpoint, and the admin service account does not have
// `firebaserules.rulesets.test` (403, re-confirmed 2026-09-08). So the project's only
// rules test could never actually run, and the rules that guard this portfolio have
// been shipped unexercised. The emulator needs no cloud permissions at all.
//
// Run:  cd rules-test && npm install && npm test
//
// It reads ../firestore.rules directly — there is no second copy of the ruleset
// anywhere, on purpose (deploy-firestore-rules.py used to carry an inline copy that
// silently drifted from the file).
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { initializeTestEnvironment, assertSucceeds, assertFails } from '@firebase/rules-unit-testing';
import { doc, getDoc, setDoc, updateDoc } from 'firebase/firestore';

const HERE = dirname(fileURLToPath(import.meta.url));
const RULES = readFileSync(join(HERE, '..', 'firestore.rules'), 'utf8');
const OWNER = 'ownerUid';
const OWNER_EMAIL = 'owner@example.com';
const FRIEND_EMAIL = 'friend@example.com';

const testEnv = await initializeTestEnvironment({
  projectId: 'demo-hk-portfolio',
  firestore: { rules: RULES, host: '127.0.0.1', port: 8080 },
});

const arr = n => Array.from({ length: n }, (_, i) => ({ i }));

// ndel === null models OLD CLIENT CODE. Both HTML clients build the outgoing document
// from an explicit field whitelist, so a tab running old cached JS omits
// positionDeletions entirely rather than echoing it back.
function mkDoc(npos, nclosed, nsnap, ndel, viewers = []) {
  const d = { positions: arr(npos), closedTrades: arr(nclosed), snapshots: arr(nsnap), allowedViewers: viewers };
  if (ndel !== null) d.positionDeletions = arr(ndel);
  return d;
}

const BASE  = mkDoc(12, 32, 96, 3);   // a book that has had 3 manual deletes
const BASE0 = mkDoc(12, 32, 96, 0);   // a book that has never had one (bootstrap case)

const CASES = [
  // --- everyday use must keep working ---
  ['ALLOW', 'add position (+1 pos)',                       BASE,  mkDoc(13, 32, 96, 3)],
  ['ALLOW', 'full sale (-1 pos, +1 trade)',                BASE,  mkDoc(11, 33, 96, 3)],
  ['ALLOW', 'partial sale (same pos, +1 trade)',           BASE,  mkDoc(12, 33, 96, 3)],
  ['ALLOW', 'add snapshot (+1 snap)',                      BASE,  mkDoc(12, 32, 97, 3)],
  ['ALLOW', 'idle re-save (nothing moves)',                BASE,  mkDoc(12, 32, 96, 3)],
  ['ALLOW', 'sale of 3 at once (+1 trade)',                BASE,  mkDoc(9,  33, 96, 3)],
  // --- a manual delete now has to carry a receipt (2026-09-08) ---
  ['ALLOW', 'manual delete WITH receipt',                  BASE,  mkDoc(11, 32, 96, 4)],
  ['ALLOW', 'delete 2 WITH 2 receipts',                    BASE,  mkDoc(10, 32, 96, 5)],
  ['ALLOW', 'first ever delete, empty log -> 1 receipt',   BASE0, mkDoc(11, 32, 96, 1)],
  // --- THE BUG THIS SHIPS TO STOP (1138.HK, 2026-09-08): a position leaving the
  //     book with no sale and no receipt is exactly a stale tab reverting an add ---
  ['DENY',  'THE 1138 BUG: -1 pos, no trade, no receipt',  BASE,  mkDoc(11, 32, 96, 3)],
  ['DENY',  'THE 1138 BUG on a never-deleted book',        BASE0, mkDoc(11, 32, 96, 0)],
  ['DENY',  'delete 2 with only 1 receipt',                BASE,  mkDoc(10, 32, 96, 4)],
  // --- old cached JS omits the field, so its every write must fail closed ---
  ['DENY',  'OLD CODE omits receipts (idle save)',         BASE,  mkDoc(12, 32, 96, null)],
  ['DENY',  'OLD CODE omits receipts (drops a position)',  BASE,  mkDoc(11, 32, 96, null)],
  ['DENY',  'OLD CODE omits receipts (adds a position)',   BASE,  mkDoc(13, 32, 96, null)],
  ['DENY',  'stale tab rewinds the receipt log',           BASE,  mkDoc(12, 32, 96, 2)],
  // --- invariants that were already live, must not regress ---
  ['DENY',  'stale revert: -2 pos, no trade',              BASE,  mkDoc(10, 32, 96, 3)],
  ['DENY',  'wipe a closedTrade (-1 trade)',               BASE,  mkDoc(12, 31, 96, 3)],
  ['DENY',  'wipe snapshots (-5 snap)',                    BASE,  mkDoc(12, 32, 91, 3)],
];

let pass = 0, fail = 0;
const report = (ok, expect, name) => {
  ok ? pass++ : fail++;
  console.log(`  [${ok ? 'PASS' : 'FAIL'}] ${expect.padEnd(5)} ${name}`);
};

// Both books get the identical ruleset, so both get the identical matrix.
for (const collection of ['portfolios', 'us-portfolios']) {
  console.log(`\n===== ${collection} =====`);
  for (const [expect, name, base, incoming] of CASES) {
    await testEnv.clearFirestore();
    await testEnv.withSecurityRulesDisabled(async ctx => {
      await setDoc(doc(ctx.firestore(), collection, OWNER), base);
    });
    const db = testEnv.authenticatedContext(OWNER, { email: OWNER_EMAIL }).firestore();
    const ref = doc(db, collection, OWNER);
    let ok;
    try {
      // setDoc, not updateDoc: the app writes with a full-document set() replace,
      // which is the whole reason this class of bug exists.
      if (expect === 'ALLOW') { await assertSucceeds(setDoc(ref, incoming)); ok = true; }
      else                    { await assertFails(setDoc(ref, incoming));    ok = true; }
    } catch (e) { ok = false; }
    report(ok, expect, name);
  }
}

console.log('\n===== sharing / access =====');
const seed = async viewers => {
  await testEnv.clearFirestore();
  await testEnv.withSecurityRulesDisabled(async ctx =>
    setDoc(doc(ctx.firestore(), 'portfolios', OWNER), mkDoc(12, 32, 96, 3, viewers)));
};
await seed([FRIEND_EMAIL]);
try {
  await assertSucceeds(getDoc(doc(testEnv.authenticatedContext('friendUid', { email: FRIEND_EMAIL }).firestore(), 'portfolios', OWNER)));
  report(true, 'ALLOW', 'friend in allowedViewers can read');
} catch { report(false, 'ALLOW', 'friend in allowedViewers can read'); }
try {
  await assertFails(updateDoc(doc(testEnv.authenticatedContext('friendUid', { email: FRIEND_EMAIL }).firestore(), 'portfolios', OWNER), { positions: arr(13) }));
  report(true, 'DENY', 'friend cannot write');
} catch { report(false, 'DENY', 'friend cannot write'); }
await seed([]);
try {
  await assertFails(getDoc(doc(testEnv.authenticatedContext('strangerUid', { email: 'x@example.com' }).firestore(), 'portfolios', OWNER)));
  report(true, 'DENY', 'stranger cannot read');
} catch { report(false, 'DENY', 'stranger cannot read'); }

await testEnv.cleanup();
console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail === 0 ? 0 : 1);
