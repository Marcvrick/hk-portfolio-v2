#!/usr/bin/env node
// Check: the Performance tab's entry-day rule must survive the session rollover.
// A position opened on the last completed session keeps its entry price as the
// baseline while the tab still renders that session (weekend / holiday /
// pre-market / stale cache). Before 2026-08-08 `isNewToday` compared entryDate
// against the wall-clock date, so once the date rolled past the session the row
// fell back to the exchange previous close and displayed the whole session's
// move instead of the move from the fill.
// Fixtures are synthetic — no live holdings (this repo is public).
const assert = require('assert');

// Mirrors index.html moversData (previousClose chain + useTvDirect gate).
function row(p, { cached, todayStr, marketClosed, preMarket, cacheIsToday = true,
                  lastSessionDate, lastTradingClose, dayBeforeClose, yesterdayClose }) {
  const showLastSession = preMarket || marketClosed || !cacheIsToday;
  const sessionDate = showLastSession ? (lastSessionDate || todayStr) : todayStr;

  let currentPrice;
  if (preMarket && yesterdayClose != null) currentPrice = yesterdayClose;
  else if (marketClosed && lastTradingClose != null) currentPrice = lastTradingClose;
  else currentPrice = cached?.success ? cached.price : p.currentPrice;

  const isNewToday = p.entryDate === sessionDate;

  let previousClose;
  if (cached?.previousCloseOverride) previousClose = cached.previousCloseOverride;
  else if (isNewToday) previousClose = p.entryPrice;
  else if (preMarket) previousClose = dayBeforeClose ?? yesterdayClose ?? p.currentPrice;
  else if (cached?.success && cached.previousClose) previousClose = cached.previousClose;
  else if (yesterdayClose != null) previousClose = yesterdayClose;
  else previousClose = p.currentPrice;

  const useTvDirect = !isNewToday && !cached?.previousCloseOverride
    && cached?.success && cached.changePercent != null && cached.change != null;
  return useTvDirect
    ? { pct: cached.changePercent, dollar: cached.change * p.quantity }
    : { pct: previousClose > 0 ? ((currentPrice - previousClose) / previousClose) * 100 : 0,
        dollar: (currentPrice - previousClose) * p.quantity };
}

// Opened Fri 08-07 at 10.00. The stock closed 9.00 Thu and 10.02 Fri, so TV
// reports a +1.02 session move — 51x the 0.02 actually earned from the fill.
const opened = { ticker: 'TEST.HK', quantity: 1000, entryPrice: 10.00,
                 entryDate: '2026-08-07', currentPrice: 10.02 };
const tvFri = { success: true, price: 10.02, previousClose: 9.00, change: 1.02,
                changePercent: 11.3333 };

// Saturday: the tab shows Friday. Baseline must stay the fill, not Thursday's close.
const sat = row(opened, { cached: tvFri, todayStr: '2026-08-08', marketClosed: true,
  preMarket: false, lastSessionDate: '2026-08-07', lastTradingClose: 10.02 });
assert.ok(Math.abs(sat.dollar - 20) < 1e-6, `Saturday $ ${sat.dollar} != 20`);
assert.ok(Math.abs(sat.pct - 0.2) < 1e-9, `Saturday % ${sat.pct} != 0.2`);

// Friday intraday: already correct before the fix, must stay correct.
const fri = row(opened, { cached: tvFri, todayStr: '2026-08-07', marketClosed: false,
  preMarket: false });
assert.ok(Math.abs(fri.dollar - 20) < 1e-6, `Friday $ ${fri.dollar} != 20`);

// Monday pre-market: still showing Friday, same baseline.
const pre = row(opened, { cached: tvFri, todayStr: '2026-08-10', marketClosed: false,
  preMarket: true, lastSessionDate: '2026-08-07', yesterdayClose: 10.02,
  dayBeforeClose: 9.00 });
assert.ok(Math.abs(pre.dollar - 20) < 1e-6, `pre-market $ ${pre.dollar} != 20`);

// Stale cache on a live day: same rule (the row still describes Friday).
const stale = row(opened, { cached: tvFri, todayStr: '2026-08-10', marketClosed: false,
  preMarket: false, cacheIsToday: false, lastSessionDate: '2026-08-07' });
assert.ok(Math.abs(stale.dollar - 20) < 1e-6, `stale-cache $ ${stale.dollar} != 20`);

// Monday live: no longer the entry session -> TV's official figures take over.
const live = row(opened, { cached: { success: true, price: 10.50, previousClose: 10.02,
  change: 0.48, changePercent: 4.79 }, todayStr: '2026-08-10', marketClosed: false,
  preMarket: false });
assert.ok(Math.abs(live.dollar - 480) < 1e-6, `Monday $ ${live.dollar} != 480`);

// A position held from before still reads the whole session on a closed day.
const held = row({ ticker: 'OLD.HK', quantity: 100, entryPrice: 80, entryDate: '2026-01-05',
  currentPrice: 120 }, { cached: { success: true, price: 120, previousClose: 118,
  change: 2, changePercent: 1.69 }, todayStr: '2026-08-08', marketClosed: true,
  preMarket: false, lastSessionDate: '2026-08-07', lastTradingClose: 120 });
assert.ok(Math.abs(held.dollar - 200) < 1e-6, `held $ ${held.dollar} != 200`);

// Manual override still outranks the entry-day rule.
const ovr = row(opened, { cached: { ...tvFri, previousCloseOverride: 9.50 },
  todayStr: '2026-08-08', marketClosed: true, preMarket: false,
  lastSessionDate: '2026-08-07', lastTradingClose: 10.02 });
assert.ok(Math.abs(ovr.dollar - 520) < 1e-6, `override $ ${ovr.dollar} != 520`);

console.log('OK — entry-day rule holds across session rollover (7 cases)');
