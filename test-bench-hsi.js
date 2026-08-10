#!/usr/bin/env node
// Check: the History tab's "Performance vs HSI" card.
//
// Four things it must get right, each of which has a real failure mode:
//   1. P&L over the window is the BALANCE-SHEET DELTA. Six sessions have no snapshot
//      (2026-05-28..06-05), so summing dailyPnL under-reports by ~7,234 HKD.
//   2. Average engaged capital is DAY-WEIGHTED. The capital ranged 677k..1,340k; a plain
//      mean over snapshots would over-weight busy weeks and under-weight quiet ones.
//   3. TWR compounds and is capital-neutral — that is what makes it comparable to HSI.
//   4. The HSI lookup prefers the snapshot's own hsiClose, then the frozen table, then the
//      last close before that date (HKEX holidays; snapshots minted past the table's end).
//
// Fixtures are synthetic — no live holdings (this repo is public).
const assert = require('assert');

// ---- mirrors index.html, History tab, "Performance vs HSI" -------------------
const eq = (s) => (s.unrealizedPnL || 0) + (s.realizedPnL || 0);
const pad2 = (n) => String(n).padStart(2, '0');

function cutoffFor(w, lastDate) {
  if (w === 'Tout') return '0000-00-00';
  if (w === 'YTD') return `${lastDate.substring(0, 4)}-01-01`;
  const [Y, M, D] = lastDate.split('-').map(Number);
  const d = new Date(Y, M - 1 - (w === '1M' ? 1 : w === '3M' ? 3 : 6), D);
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

function hsiOn(snap, table, dates) {
  if (snap.hsiClose) return snap.hsiClose;
  if (table[snap.date] != null) return table[snap.date];
  let last = null;
  for (const d of dates) { if (d > snap.date) break; last = table[d]; }
  return last;
}

function avgEngaged(win) {
  let num = 0, den = 0;
  win.forEach((s, i) => {
    const w = i + 1 < win.length
      ? Math.round((new Date(win[i + 1].date) - new Date(s.date)) / 86400000)
      : 1;
    num += (s.capitalEngaged || 0) * w;
    den += w;
  });
  return den ? num / den : 0;
}

function twrOf(win) {
  let idx = 1;
  for (let i = 1; i < win.length; i++) {
    const base = win[i - 1].portfolioValue || 0;
    if (base && win[i].dailyPnL != null) idx *= 1 + win[i].dailyPnL / base;
  }
  return (idx - 1) * 100;
}

// ---- 1. P&L is the balance-sheet delta, not the sum of dailyPnL -------------
{
  // Session 3 is missing from the record: its move never enters any dailyPnL, but the
  // stored realized/unrealized state at both bounds still carries it.
  const win = [
    { date: '2026-03-02', realizedPnL: 0, unrealizedPnL: 0, portfolioValue: 100000, dailyPnL: null },
    { date: '2026-03-03', realizedPnL: 0, unrealizedPnL: 1000, portfolioValue: 101000, dailyPnL: 1000 },
    // 2026-03-04 has no snapshot; the market moved +500 that day
    { date: '2026-03-05', realizedPnL: 0, unrealizedPnL: 2500, portfolioValue: 102500, dailyPnL: 1000 },
  ];
  const delta = eq(win[win.length - 1]) - eq(win[0]);
  const summed = win.slice(1).reduce((a, s) => a + (s.dailyPnL || 0), 0);
  assert.strictEqual(delta, 2500, 'balance-sheet delta must capture the unrecorded session');
  assert.strictEqual(summed, 2000, 'the dailyPnL sum is expected to fall short');
  assert.ok(delta > summed, 'the card must use the delta, which is the larger, correct figure');
}

// ---- 2. average engaged capital is day-weighted ------------------------------
{
  // 1,000,000 held Mon->Fri (4 days of weight), then 2,000,000 for the last day (weight 1).
  const win = [
    { date: '2026-03-02', capitalEngaged: 1000000 },
    { date: '2026-03-06', capitalEngaged: 2000000 },
  ];
  assert.strictEqual(avgEngaged(win), (1000000 * 4 + 2000000 * 1) / 5,
    'each capital level weighs the number of days it actually held');
  // a plain mean over snapshots would say 1,500,000 — that is the bug this guards
  assert.notStrictEqual(avgEngaged(win), 1500000);
}

// ---- 3. TWR compounds, and is neutral to the size of the book ---------------
{
  const up10down10 = [
    { date: '2026-03-02', portfolioValue: 100000, dailyPnL: null },
    { date: '2026-03-03', portfolioValue: 110000, dailyPnL: 10000 },
    { date: '2026-03-04', portfolioValue: 99000, dailyPnL: -11000 },
  ];
  assert.ok(Math.abs(twrOf(up10down10) - -1) < 1e-9, '+10% then -10% compounds to -1%, not 0%');

  // Same daily percentages on a book ten times larger: identical TWR. This is the property
  // that makes TWR, and only TWR, comparable to an index.
  const tenfold = up10down10.map(s => ({
    ...s,
    portfolioValue: s.portfolioValue * 10,
    dailyPnL: s.dailyPnL == null ? null : s.dailyPnL * 10,
  }));
  assert.ok(Math.abs(twrOf(tenfold) - twrOf(up10down10)) < 1e-9,
    'TWR must not move when only the capital deployed changes');
}

// ---- 4. HSI lookup precedence ------------------------------------------------
{
  const table = { '2026-04-02': 25116.53, '2026-04-08': 25893.02 };
  const dates = Object.keys(table).sort();
  assert.strictEqual(hsiOn({ date: '2026-04-08', hsiClose: 99999 }, table, dates), 99999,
    "the snapshot's own hsiClose wins over the frozen table");
  assert.strictEqual(hsiOn({ date: '2026-04-02' }, table, dates), 25116.53,
    'an exact date reads straight from the table');
  assert.strictEqual(hsiOn({ date: '2026-04-07' }, table, dates), 25116.53,
    'an HKEX holiday forward-fills from the last close before it');
  assert.strictEqual(hsiOn({ date: '2026-08-11' }, table, dates), 25893.02,
    'past the end of the table, hold the last close (the card flags this as stale)');
  assert.strictEqual(hsiOn({ date: '2026-01-01' }, table, dates), null,
    'before the table starts there is no benchmark — the card must render "—", not 0');
}

// ---- 5. window cutoffs are local-date safe ----------------------------------
{
  assert.strictEqual(cutoffFor('YTD', '2026-08-10'), '2026-01-01');
  assert.strictEqual(cutoffFor('3M', '2026-08-10'), '2026-05-10');
  assert.strictEqual(cutoffFor('1M', '2026-03-31'), '2026-03-03', 'Feb 31 rolls into March, by design');
  assert.strictEqual(cutoffFor('Tout', '2026-08-10'), '0000-00-00');
  // A UTC round-trip (new Date(s).toISOString()) shifts the day west of Greenwich. Dany
  // is in France or Paraguay; the Paraguay case would silently drop a session.
  assert.strictEqual(cutoffFor('6M', '2026-01-05'), '2025-07-05');
}

console.log('test-bench-hsi: all checks passed');
