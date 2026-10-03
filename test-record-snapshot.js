// Check recordSnapshot: it must MERGE into the stored snapshot, must refuse a day the
// cron already settled, and must not claim success before saveData says so.
//
// recordSnapshot is DEAD CODE, with no call site in either HTML and none in their history.
// This suite exists anyway, because the function is one onClick away from live and the
// behaviour below is the whole reason it would be safe to wire.
//
// WHY (wiki/reliability-risks.md #14 and #15). It used to substitute an 8-field
// object for whatever was stored for today, dropping closingPrices, positionsAtClose,
// dailyPnL and settledAt — a browser-minted snapshot, produced on purpose by a button.
// The obvious fix, a plain merge, is worse on a cron-settled day: it keeps settledAt while
// overwriting the totals with unreconciled browser values, so portfolioValue stops equalling
// Sigma(closingPrices x qty) under the one flag every sweep in this repo trusts. Hence the
// third case below.
//
// Extracts the real function out of the HTML (no second copy) and runs it against stubs.
// Hermetic: no Firestore, no network, no credentials.
// Run: node test-record-snapshot.js        (both books)
const fs = require('fs');
const assert = require('assert');

const FILES = process.env.RECORD_SNAPSHOT_FILE
  ? [process.env.RECORD_SNAPSHOT_FILE]
  : ['index.html', 'index-us.html'];

const TODAY = '2026-09-21';
const METRICS = {
  capitalEngaged: 1000, totalValue: 1200, totalInvested: 1000,
  totalPnL: 200, realizedPnL: 50, totalDividends: 10,
};

// A snapshot as the cron writes it: the fields the old button threw away.
const cronFields = {
  closingPrices: { '1138.HK': 19.76 },
  positionsAtClose: [{ ticker: '1138.HK', quantity: 100, closingPrice: 19.76 }],
  dailyPnL: 4493,
  sources: ['tradingview', 'yahoo'],
  priceProvenance: { '1138.HK': { source: 'yahoo', drift: 0 } },
};

async function run(file) {
  const html = fs.readFileSync(__dirname + '/' + file, 'utf8');
  const src = html.match(/const recordSnapshot = async \(\) => \{[\s\S]*?\n {6}\};/);
  assert.ok(src, `${file}: recordSnapshot not found — did the function get renamed?`);

  const call = async (snapshots, saveResult = { ok: true }) => {
    const calls = { saved: [], setTo: null, alerts: [] };
    const ctx = {
      calculateMetrics: METRICS,
      snapshots,
      positions: [{ ticker: '1138.HK', quantity: 100 }],
      closedTrades: [], transactions: [], priceCache: {}, settings: {},
      today: TODAY,
      setSnapshots: (s) => { calls.setTo = s; },
      saveData: async (...a) => { calls.saved.push(a); return saveResult; },
      alert: (m) => { calls.alerts.push(m); },
    };
    await new Function('ctx', `
      const { calculateMetrics, snapshots, positions, closedTrades, transactions,
              priceCache, settings, today, setSnapshots, saveData, alert } = ctx;
      ${src[0]}
      return recordSnapshot();
    `)(ctx);
    return calls;
  };

  // 1. Nothing stored for today: the button does its original job.
  let r = await call([{ date: '2026-09-18', portfolioValue: 1 }]);
  assert.strictEqual(r.saved.length, 1, `${file}: a fresh day is written`);
  assert.strictEqual(r.setTo.length, 2, `${file}: appended, not replaced`);
  assert.strictEqual(r.setTo[1].date, TODAY);
  assert.strictEqual(r.setTo[1].portfolioValue, 1200);

  // 2. An UNSETTLED snapshot exists: merge. This is the case the old code got wrong —
  //    it replaced the object, so every assertion below failed on the pre-fix version.
  r = await call([{ date: TODAY, portfolioValue: 999, ...cronFields }]);
  assert.strictEqual(r.saved.length, 1, `${file}: an unsettled day is still writable`);
  const merged = r.setTo.find(s => s.date === TODAY);
  assert.deepStrictEqual(merged.closingPrices, cronFields.closingPrices, `${file}: closingPrices survive`);
  assert.deepStrictEqual(merged.positionsAtClose, cronFields.positionsAtClose, `${file}: positionsAtClose survive`);
  assert.strictEqual(merged.dailyPnL, 4493, `${file}: dailyPnL survives (it is the authoritative record)`);
  assert.deepStrictEqual(merged.priceProvenance, cronFields.priceProvenance, `${file}: provenance survives`);
  assert.strictEqual(merged.portfolioValue, 1200, `${file}: the recomputed total DOES overlay`);
  assert.strictEqual(r.setTo.length, 1, `${file}: merged in place, not duplicated`);

  // 3. A CRON-SETTLED snapshot exists: refuse, write nothing. Merging here would leave
  //    portfolioValue 1200 against closingPrices worth 1976, under a settledAt.
  r = await call([{ date: TODAY, portfolioValue: 1976, settledAt: '2026-09-21T16:35:00+08:00', ...cronFields }]);
  assert.strictEqual(r.saved.length, 0, `${file}: a settled day is NOT written`);
  assert.strictEqual(r.setTo, null, `${file}: a settled day does not even touch state`);
  assert.strictEqual(r.alerts.length, 1, `${file}: the refusal is stated, not silent`);
  assert.ok(r.alerts[0].includes(TODAY), `${file}: the refusal names the date`);

  // 4. The save FAILS: no success alert, state goes back to what it was. Before
  //    2026-10-03 the success alert fired whatever saveData returned (the 0177.HK shape).
  const before = [{ date: '2026-09-18', portfolioValue: 1 }];
  r = await call(before, { ok: false, reason: 'permission-denied' });
  assert.strictEqual(r.saved.length, 1, `${file}: the write was attempted`);
  assert.strictEqual(r.setTo, before, `${file}: a failed save rolls state back`);
  assert.strictEqual(r.alerts.length, 1);
  assert.ok(r.alerts[0].includes('NON enregistré'), `${file}: the failure is stated`);
  assert.ok(r.alerts[0].includes('permission-denied'), `${file}: the failure names the reason`);

  console.log(`  ${file}: 4 cases OK`);
}

(async () => {
  console.log('recordSnapshot — merge, refuse a settled day, never claim an unconfirmed save');
  for (const f of FILES) await run(f);
  console.log('ALL PASS');
})().catch(e => { console.error(e); process.exit(1); });
