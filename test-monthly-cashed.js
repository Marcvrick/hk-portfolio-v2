// Check the "Encaissé par mois" aggregation of the Completed Trades tab.
// Extracts the real code out of index.html (no copy) and runs it on synthetic trades.
// Run: node test-monthly-cashed.js
const fs = require('fs');
const assert = require('assert');

const BLOCK = /const byYear = \{\};[\s\S]*?const years = Object\.keys\(byYear\)\.sort\(\)\.reverse\(\);/;

for (const file of ['index.html', 'index-us.html']) {
  const html = fs.readFileSync(__dirname + '/' + file, 'utf8');
  const code = html.match(BLOCK)[0];

  const closedWithCalc = [
    { exitDate: '2026-01-15', pnl: 1000, exitPrice: 10, quantity: 100 },
    { exitDate: '2026-01-28', pnl: -400, exitPrice: 5, quantity: 200 },
    { exitDate: '2026-08-03', pnl: 250, exitPrice: 99.1, quantity: 400 },
    { exitDate: '2025-12-31', pnl: 77, exitPrice: 20, quantity: 50 },
    { exitDate: null, pnl: 999999, exitPrice: 1, quantity: 1 },   // no exit date -> ignored
  ];
  const { byYear, years } = new Function('closedWithCalc',
    `${code}\nreturn { byYear, years };`)(closedWithCalc);

  assert.deepStrictEqual(years, ['2026', '2025'], `${file}: newest year first`);
  assert.strictEqual(byYear['2026'].length, 12, `${file}: 12 month cells`);

  const jan = byYear['2026'][0], aug = byYear['2026'][7], feb = byYear['2026'][1];
  assert.strictEqual(jan.pnl, 600, `${file}: January nets both trades`);
  assert.strictEqual(jan.count, 2);
  assert.strictEqual(jan.proceeds, 10 * 100 + 5 * 200, `${file}: proceeds = exitPrice x qty`);
  assert.strictEqual(aug.pnl, 250, `${file}: August is index 7, not 8`);
  assert.deepStrictEqual(feb, { pnl: 0, proceeds: 0, count: 0 }, `${file}: empty month stays empty`);
  assert.strictEqual(byYear['2025'][11].pnl, 77, `${file}: December is index 11`);

  // The grand total shown under the grid is m.realizedPnL; the cells must sum to the
  // same thing (both are net of fees, from the same closedWithCalc).
  const cellSum = years.reduce((s, y) => s + byYear[y].reduce((a, c) => a + c.pnl, 0), 0);
  const netRealized = closedWithCalc.filter(t => t.exitDate).reduce((s, t) => s + t.pnl, 0);
  assert.strictEqual(cellSum, netRealized, `${file}: cells must sum to realized P&L`);

  console.log(`${file}: OK`);
}
