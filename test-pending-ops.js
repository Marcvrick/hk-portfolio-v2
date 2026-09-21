// Check the pending-operation log: the durable record of what Dany asked for, which
// is what makes a write the cloud never received recoverable (2714 / 0177 / 1138, see
// wiki/incidents.md). Extracts the real code out of index.html (no copy) and runs it
// against a localStorage stub.
// Run: node test-pending-ops.js
const fs = require('fs');
const assert = require('assert');

const FILE = process.env.PENDING_OPS_FILE || 'index.html';
const html = fs.readFileSync(__dirname + '/' + FILE, 'utf8');
const convert = html.match(/const convertOldTicker = \(ticker\) => \{[\s\S]*?\n {4}\};/)[0];
const storage = html.match(/const storage = \{[\s\S]*?\n {4}\};/)[0];
const ops = html.match(/const PENDING_OPS_KEY[\s\S]*?const isOpReflected[\s\S]*?\n {4}\};/)[0];

const store = {};
global.localStorage = {
  getItem: k => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v); },
};

const sandbox = {};
new Function('sandbox', `
  ${convert}
  ${storage}
  ${ops}
  Object.assign(sandbox, { convertOldTicker, storage, PENDING_OPS_KEY,
    readPendingOps, writePendingOps, beginPendingOp, endPendingOp, isOpReflected });
`)(sandbox);

const { readPendingOps, beginPendingOp, endPendingOp, isOpReflected, PENDING_OPS_KEY } = sandbox;

// ---- the log itself ----
assert.deepStrictEqual(readPendingOps(), [], 'empty storage reads as an empty log');

const id = beginPendingOp({ kind: 'close', ticker: '1138.HK', quantity: 10000, exitPrice: 19.76, exitDate: '2026-09-21' });
assert.strictEqual(readPendingOps().length, 1, 'begin records the intent');
assert.ok(readPendingOps()[0].at, 'the record is timestamped (the grace window needs it)');

// The whole point: it is on disk, not in React state, so a refresh keeps it.
assert.ok(store[PENDING_OPS_KEY].includes('1138.HK'), 'the intent survives in localStorage');

endPendingOp(id);
assert.strictEqual(readPendingOps().length, 0, 'end clears only on a confirmed save');

// Corrupt storage must not brick the app.
store[PENDING_OPS_KEY] = '{not json';
assert.deepStrictEqual(readPendingOps(), [], 'unparseable log degrades to empty');

// ---- reflection: is the cloud already carrying this operation? ----
const closeOp = { kind: 'close', ticker: '1138.HK', quantity: 10000, exitDate: '2026-09-21' };
assert.strictEqual(isOpReflected(closeOp, [], []), false, 'no trade in the cloud -> unreflected');
assert.strictEqual(
  isOpReflected(closeOp, [], [{ ticker: '1138.HK', quantity: 10000, exitDate: '2026-09-21' }]),
  true, 'the sale is in closedTrades -> done, whoever wrote it');
assert.strictEqual(
  isOpReflected(closeOp, [], [{ ticker: '1138.HK', quantity: 10000, exitDate: '2026-09-18' }]),
  false, 'a DIFFERENT sale of the same ticker does not count');
if (FILE === 'index.html') {
  // HK only: its convertOldTicker maps the legacy HKG: form onto NNNN.HK. The US
  // normalizer is a different function on purpose (strip .HK, uppercase), so this
  // equivalence is not expected there.
  assert.strictEqual(
    isOpReflected(closeOp, [], [{ ticker: 'HKG:1138', quantity: 10000, exitDate: '2026-09-21' }]),
    true, 'the legacy HKG: ticker form still matches');
}

// The add case that a naive quantity test gets wrong: topping up an existing holding.
const topUp = { kind: 'add', ticker: '0700.HK', quantity: 2000, expectedQuantity: 12000 };
assert.strictEqual(
  isOpReflected(topUp, [{ ticker: '0700.HK', quantity: 10000 }], []),
  false, 'the pre-existing 10,000 must NOT read as the top-up having landed');
assert.strictEqual(
  isOpReflected(topUp, [{ ticker: '0700.HK', quantity: 12000 }], []),
  true, 'the expected total is there -> reflected');

// Older records have no expectedQuantity; fall back rather than nag forever.
assert.strictEqual(
  isOpReflected({ kind: 'add', ticker: '0700.HK', quantity: 2000 }, [{ ticker: '0700.HK', quantity: 2000 }], []),
  true, 'a record written before expectedQuantity existed still resolves');

const del = { kind: 'delete', ticker: '0434.HK' };
assert.strictEqual(isOpReflected(del, [{ ticker: '0434.HK', quantity: 100 }], []), false, 'still held -> unreflected');
assert.strictEqual(isOpReflected(del, [], []), true, 'gone from positions -> reflected');

assert.strictEqual(isOpReflected({ kind: 'something-new' }, [], []), true, 'an unknown kind never nags');

console.log(`test-pending-ops (${FILE}): PASS`);
