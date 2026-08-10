// Check the month -> weeks calendar aggregation of the "P&L par semaine" card.
// Extracts the real code out of index.html (no copy) and runs it on a synthetic month boundary.
// Run: node test-weekly-calendar.js
const fs = require('fs');
const assert = require('assert');

const html = fs.readFileSync(__dirname + '/index.html', 'utf8');
const weekKey = html.match(/const getWeekKey = \(dateStr\) => \{[\s\S]*?\n {14}\};/)[0];
const calendar = html.match(/\/\/ Calendar view: month[\s\S]*?total: weeks\.reduce[\s\S]*?\n {14}\}\);/)[0];

// 2026-06-29 (Mon) .. 2026-07-03 (Fri) is ONE week straddling June and July.
const dailyPnls = [
  { date: '2026-06-29', pnl: 100 }, { date: '2026-06-30', pnl: 50 },
  { date: '2026-07-01', pnl: -20 }, { date: '2026-07-02', pnl: 10 }, { date: '2026-07-03', pnl: 5 },
  { date: '2026-07-06', pnl: 200 },
];
const monthNames = ['Jan','Fév','Mar','Avr','Mai','Jun','Jul','Aoû','Sep','Oct','Nov','Déc'];
const calendarData = new Function('dailyPnls', 'monthNames',
  `${weekKey}\n${calendar}\nreturn calendarData;`)(dailyPnls, monthNames);

assert.deepStrictEqual(calendarData.map(m => m.label), ['Jul 2026', 'Jun 2026'], 'newest month first');

const jul = calendarData[0], jun = calendarData[1];
assert.strictEqual(jun.total, 150, 'June keeps only its own days of the straddling week');
assert.strictEqual(jul.total, 195, 'July keeps its clipped half + the next full week');
for (const m of [jun, jul]) {
  assert.strictEqual(m.weeks.reduce((s, w) => s + w.pnl, 0), m.total, `${m.label}: cells must sum to the month total`);
}
assert.strictEqual(jun.weeks.length, 1);
assert.deepStrictEqual(jul.weeks.map(w => w.days), ['1–3', '6–6'], 'day range is clipped to the month');
assert.strictEqual(jul.weeks[0].week, jun.weeks[0].week, 'both halves carry the same ISO week label');

console.log('OK — calendar aggregation splits straddling weeks and stays consistent with monthly totals');
