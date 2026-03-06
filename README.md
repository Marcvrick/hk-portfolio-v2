# Portfolio Tracker v2 - Firebase

Portfolio tracker for **Hong Kong** and **US** stocks with **Firebase Firestore** backend for reliable multi-device sync.

**Live:**
- 🇭🇰 HK Portfolio: https://marcvrick.github.io/hk-portfolio-v2/
- 🇺🇸 US Portfolio: https://marcvrick.github.io/hk-portfolio-v2/index-us.html

---

## Features

### Core
- **Firebase Authentication** (Email/Password) - Private, secure access
- Real-time portfolio tracking with live Yahoo Finance prices
- Multi-device sync via Firebase Firestore (per-user data isolation)
- Daily P&L calendar with performance history
- Position duration tracking with visual alerts
- Closed trades history with win rate analytics
- **Wishlist** - Track stocks you want to buy with target price alerts
- **Friend portfolio viewing** - View friends' portfolios (HK or US) with dynamic currency labels
- **Dual portfolio toggle** - Optional HK+US portfolio switching (off by default)

### UI/UX (v2.3)
- **Dark mode** (default) with light mode toggle (sun/moon icon)
- **Light mode** with soft lime-tinted background (#f4f6ef)
- Modern donut pie chart with muted color palette
- Compact, dense table layout
- **Compact metric cards on mobile** (4 per row, responsive sizing)
- Danger row highlighting (🚨) on Positions & Performance tabs
- Visual alerts for positions down ≥10% (red) or 8-10% (orange)
- **Failed tickers shown by name** in refresh alerts (not just count)
- Responsive design for mobile/desktop

---

## Tech Stack

**Frontend:**
- React 18 (CDN)
- Firebase JS SDK 10.x
- Recharts (charts)
- Tailwind CSS (styling)
- TradingView Scanner API (live prices, no proxy needed)

**Backend:**
- Firebase Firestore (database)
- GitHub Actions (daily cron)
- Python + firebase-admin + TradingView Scanner API (price updates)

---

## Files

| File | Description |
|------|-------------|
| `index.html` | HK Portfolio - Production app (dark mode default) |
| `index-us.html` | US Portfolio - Same layout, USD currency |
| `index-dev.html` | Development version |
| `update.py` | Cron script for HK TradingView prices (multi-user, HKEX holiday-aware) |
| `update-us.py` | Cron script for US TradingView prices |
| `patch-data-correction.py` | One-time patch: fix Feb 13/16, Mar 2 closingPrices from Stooq |
| `verify-weekly.py` | Weekly verification: Firebase snapshots vs FinMC/Stooq parquet data |
| `migrate-main-to-uid.py` | One-time migration: portfolios/main → portfolios/{uid} |
| `.github/workflows/daily-update-hk.yml` | GitHub Actions workflow (HK, 16:30 HKT) |
| `.github/workflows/daily-update-us.yml` | GitHub Actions workflow (US, 16:00 ET) |

---

## HK / US Sync Status

Both `index.html` (HK) and `index-us.html` (US) share the same core features but are maintained as separate files. When making changes, **always apply to both files** unless the change is market-specific.

| Feature / Fix | `index.html` (HK) | `index-us.html` (US) | Date Synced |
|---|:---:|:---:|---|
| Use TradingView's official % directly (never recompute) | ✅ | ✅ | 2026-03-05 |
| TradingView Scanner API replaces Yahoo Finance (browser) | ✅ | ✅ | 2026-03-05 |
| TradingView links open in edit mode (saved layout) | ✅ | ✅ | 2026-03-05 |
| Midnight auto-update `today` (60s interval detects date change) | ✅ | ✅ | 2026-03-04 |
| Market-timezone `today` + all HKT/ET helpers via Intl API | ✅ | ✅ | 2026-03-04 |
| Fix stale `today` + past snapshot immutability guard | ✅ | ✅ | 2026-03-04 |
| Post-close data protection (auto-refresh + snapshot lock) | ✅ | ✅ | 2026-02-27 |
| Fix HKT timezone bug in isPreMarket/isMarketOpen/isAfterClose | ✅ | — | 2026-02-27 |
| Fix TOTAL row alignment on mobile (Positions + Performance) | ✅ | ✅ | 2026-02-24 |
| Fix dailyGain vs Performance tab P&L discrepancy | — | ✅ | 2026-02-12 |
| Snapshot auto-save persists to Firestore | — | ✅ | 2026-02-12 |
| Fix previousClose extraction (timestamp-based) | ✅ | ✅ | 2026-02-11 |
| Live daily P&L for today (no stale snapshot) | ✅ | ✅ | 2026-02-11 |
| Auto-refresh cache threshold 5 min | ✅ | ✅ | 2026-02-11 |
| snapshotChanged includes dailyPnL | ✅ | ✅ | 2026-02-11 |
| Snapshot stores dailyPnL + positionsAtClose | ✅ | ✅ | 2026-02-11 |
| Calendar: stored dailyPnL is immutable | ✅ | ✅ | 2026-02-11 |
| Multi-user cron (iterate all docs) | ✅ | ✅ | 2026-02-10 |
| `viewingFriendRef` guards (7 locations) | ✅ | ✅ | 2026-02-10 |
| `returnToOwnPortfolio` async + fallback | ✅ | ✅ | 2026-02-10 |
| `enableDualPortfolio` toggle | ✅ | ✅ | 2026-02-10 |
| "Voir" → "Ajouter" button rename | ✅ | ✅ | 2026-02-10 |
| Dynamic currency label (HKD/USD) | ✅ | ✅ | 2026-02-10 |
| Friend daily P&L shows friend's data | ✅ | ✅ | 2026-02-10 |
| Empty `INITIAL_POSITIONS/TRADES/TRANSACTIONS` | ✅ | ✅ | 2026-02-10 |
| Cloudflare Worker as primary CORS proxy | ✅ | ✅ | 2026-02-08 |
| Dead proxy auto-migration | — | ✅ | 2026-02-08 |
| `convertOldTicker()` strips `.HK` + whitespace | — | ✅ | 2026-02-08 |

**How to use this table:** After applying a change to one file, update this table to track which file still needs the same change. This prevents the HK/US drift that caused the 2026-02-10 incident.

---

## Setup Firebase

### 1. Create Firebase Project
1. Go to https://console.firebase.google.com
2. Create project "hk-portfolio-tracker"
3. Enable **Firestore Database** (production mode, asia-east1)
4. Project Settings > Your apps > Add Web app
5. Copy Firebase config to `index.html`

### 2. Enable Authentication
1. Firebase Console > Authentication > Get Started
2. Enable **Email/Password** sign-in method
3. Add users manually: Authentication > Users > Add user

### Adding New Users

To give someone access to their own portfolio:

1. Firebase Console → **Authentication** → **Users**
2. Click **Add user**
3. Enter their email + password
4. Share the URL with them

Each user gets their **own isolated portfolio** (HK and/or US). Users cannot see each other's data.

| User | HK Portfolio | US Portfolio |
|------|--------------|--------------|
| User A | `portfolios/userA` | `us-portfolios/userA` |
| User B | `portfolios/userB` | `us-portfolios/userB` |

### 3. Firestore Structure (per-user)

```
portfolios/
  └── {userId}/           ← Each user has their own data
      ├── positions: []
      ├── closedTrades: []
      ├── transactions: []
      ├── wishlist: []
      ├── wishlistAlertsDismissed: {}
      ├── snapshots: []
      ├── settings: {}
      ├── priceCache: {}
      ├── allowedViewers: []
      └── savedFriends: []
```

### 4. Security Rules (IMPORTANT!)

**Copy these rules to Firestore > Rules:**

```javascript
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    // HK Portfolio
    match /portfolios/{userId} {
      // Owner can read/write their own data
      allow read, write: if request.auth != null
                         && request.auth.uid == userId;
      // Allowed viewers can read (for friend portfolio feature)
      allow read: if request.auth != null
                  && request.auth.token.email in resource.data.allowedViewers;
    }
    // US Portfolio
    match /us-portfolios/{userId} {
      // Owner can read/write their own data
      allow read, write: if request.auth != null
                         && request.auth.uid == userId;
      // Allowed viewers can read (for friend portfolio feature)
      allow read: if request.auth != null
                  && request.auth.token.email in resource.data.allowedViewers;
    }
    // Viewer Invites (notifications when someone shares their portfolio)
    match /viewerInvites/{inviteId} {
      // Anyone authenticated can create invites
      allow create: if request.auth != null;
      // Invitees can read and update (mark as seen) their invites
      allow read, update: if request.auth != null
                          && request.auth.token.email == resource.data.inviteeEmail;
    }
  }
}
```

This ensures:
- ✅ Users can only read/write their own portfolio (HK or US)
- ✅ Authorized friends can READ portfolios where they're in `allowedViewers`
- ✅ Invitees receive notifications when added as viewers
- ✅ Unauthenticated users have no access

### 5. Cron Setup (update.py / update-us.py)

1. Firebase Console > Project Settings > Service Accounts
2. Generate new private key
3. Add as GitHub secret: `FIREBASE_CREDENTIALS_JSON`

**Two separate cron workflows:**

| Workflow | Script | Schedule | Collection |
|----------|--------|----------|------------|
| `daily-update-hk.yml` | `update.py` | Mon-Fri 08:30 UTC (16:30 HKT) | `portfolios` |
| `daily-update-us.yml` | `update-us.py` | Mon-Fri 21:00 UTC (16:00 ET) | `us-portfolios` |

Both share the same `FIREBASE_CREDENTIALS_JSON` secret. To trigger manually: GitHub > Actions > Select workflow > "Run workflow".

---

## Deployment

```bash
# Push changes to deploy via GitHub Pages
git add .
git commit -m "Update"
git push
```

GitHub Pages auto-deploys from `main` branch.

### ⚠️ CRITICAL DEPLOYMENT RULE ⚠️

**Every code change MUST be committed AND pushed to GitHub in the same session. No exceptions.**

This app has THREE execution environments that ALL read from the GitHub `main` branch:
1. **GitHub Pages** — serves `index.html` / `index-us.html` to the browser
2. **GitHub Actions cron** — runs `update.py` / `update-us.py` at market close
3. **Local browser** — for testing only (via `python -m http.server`)

If you edit code locally but forget to push:
- The **local browser** sees the new code (works correctly during testing)
- **GitHub Pages** still serves the OLD code (users see old bugs)
- The **cron** still runs the OLD `update.py` (writes wrong data to Firestore)
- The cron's wrong Firestore data then **overwrites** whatever the local browser fixed

**This is exactly what caused the Mar 5 2026 incident** — code was fixed locally, tested, confirmed working, but never pushed. The cron ran the old code at 16:30 HKT, wrote wrong `closingPrices` and `changePercent` to Firestore, and the "fixed" data reverted to wrong values. The fix had to be applied THREE times before this was identified as the root cause.

**Rule: `git add + git commit + git push` is ONE atomic operation. Never do one without the others.**

---

## Roadmap / TODO

### Completed ✅
- [x] Firebase Firestore integration
- [x] Real-time multi-device sync
- [x] Dark mode with toggle switch
- [x] Light mode with lime-tinted background
- [x] Modern donut pie chart
- [x] Compact table layout
- [x] Daily P&L calendar
- [x] Position duration alerts
- [x] Danger/warning row highlighting (Positions & Performance tabs)
- [x] Stop-loss visual alerts (🚨 for ≥10% loss)
- [x] Firebase Authentication (Email/Password)
- [x] Multi-user support with data isolation
- [x] Compact mobile metric cards (4 per row)
- [x] Detailed error reporting (failed tickers by name)
- [x] Wishlist tab with target price alerts (v2.5)

### Planned 🚧

#### ~~US Portfolio Version~~ ✅ Done (v2.4, synced v2.6)
Created `index-us.html` - US stock portfolio tracker with same features.

| Component | HK Version | US Version |
|-----------|------------|------------|
| File | `index.html` | `index-us.html` |
| Ticker format | `9961.HK` | `AAPL`, `MSFT` |
| Currency | HKD | USD |
| Firebase collection | `portfolios/{userId}` | `us-portfolios/{userId}` |
| Title | "Portfolio HK" | "Portfolio US" |
| Market holidays | HKEX (14 days/year) | NYSE (10 days/year) |
| closingPrices in snapshots | ✅ | ✅ |

#### Future Enhancements
- [x] Authentication (Firebase Auth) ✅ v2.3
- [ ] Multiple portfolios per user
- [ ] Dividend tracking improvements
- [ ] Export to CSV/Excel
- [ ] Profit target alerts
- [ ] Sector allocation chart
- [ ] Benchmark comparison (HSI, S&P500)

---

## Firebase Costs (Spark Plan - Free)

| Resource | Limit |
|----------|-------|
| Reads | 50K/day |
| Writes | 20K/day |
| Storage | 1GB |
| Transfer | 10GB/month |

Sufficient for personal portfolio tracking.

---

## Local Development

```bash
# Test HK cron locally
GOOGLE_APPLICATION_CREDENTIALS=firebase-credentials.json python update.py

# Test US cron locally
GOOGLE_APPLICATION_CREDENTIALS=firebase-credentials.json python update-us.py

# Serve locally (optional)
python -m http.server 8000
```

---

## Maintenance

### Documentation
- **PRD.md** - Product Requirements Document avec:
  - Data models (positions, snapshots, transactions, etc.)
  - Business rules (fees, thresholds, calculations)
  - Known issues et recent fixes
  - Future roadmap ideas

### Before Making Changes
1. Lire `PRD.md` pour comprendre l'architecture et les règles métier
2. Tester en local avec `python -m http.server 8000`
3. Vérifier que les calculs de fees et seuils respectent les règles documentées

### After Making Changes
1. Mettre à jour `PRD.md` si:
   - Nouveau data model ou champ ajouté
   - Nouvelle règle métier
   - Bug fixé (ajouter dans "Known Issues / Recent Fixes")
   - Nouvelle feature (ajouter dans "Features by Tab")
2. Mettre à jour le Changelog ci-dessous
3. **Commit AND push immediately** — see Deployment Rule below

### Key Business Rules (Quick Reference)
| Rule | HK | US |
|------|----|----|
| Warning threshold | P&L <= -8% | P&L <= -8% |
| Danger threshold | P&L <= -10% | P&L <= -10% |
| Weekend snapshots | Disabled | Disabled |
| Fee calculation | See PRD.md (7 components) | See PRD.md |
| Ticker format | `XXXX.HK` | `AAPL`, `MSFT` |
| Firestore collection | `portfolios/{userId}` | `us-portfolios/{userId}` |
| Cron schedule | 08:30 UTC (16:30 HKT) | 21:00 UTC (16:00 ET) |
| Currency | HKD | USD |

### Common Maintenance Tasks
- **Add new fee component**: Update `calcTradingFees()` in index.html + PRD.md
- **Change alert thresholds**: Search `isWarning` and `isDanger` in index.html
- **Price data source**: TradingView Scanner API (browser + cron), no CORS proxy needed
- **Debug snapshots**: Check browser console for snapshot logs

---

## Changelog

### Mar 5, 2026 — Incident: Unpushed code caused wrong closingPrices + cascading dailyPnL corruption

**Incident summary:** Mar 5 calendar showed +3.8k instead of the correct +6.6k. Mar 4 closingPrices in Firestore did not match TradingView's official exchange closes, causing Mar 5 dailyPnL to be calculated from wrong baselines.

**Timeline:**
1. v2.19 + v2.20 code changes were made locally (browser TradingView migration + official % usage)
2. Changes were tested locally via `python -m http.server` — everything looked correct
3. **Code was NOT pushed to GitHub** (the critical mistake)
4. The HK cron ran at 16:30 HKT (08:30 UTC) using the OLD `update.py` from GitHub
5. Old cron stored `closingPrices` derived from yesterday's snapshot (not TradingView official closes)
6. Old cron stored `changePercent` recomputed from stale `previousClose` (not TradingView's official %)
7. Browser reloaded from GitHub Pages (old code) → Firestore listener pushed cron's wrong data → percentages reverted to wrong values
8. Fix was applied 3 times locally before root cause (unpushed code) was identified

**Data corruption details (Mar 4 closingPrices: snapshot vs TradingView official):**
- 1913.HK: 42.90 vs 42.38 (diff -0.52)
- 2643.HK: 31.30 vs 30.50 (diff -0.80)
- 1316.HK: 6.80 vs 6.66 (diff -0.14)
- 0434.HK: 2.71 vs 2.73 (diff +0.02)
- Plus 7 other tickers with smaller discrepancies

**Data fix applied:**
- Mar 4 `closingPrices` corrected to TradingView official values
- Mar 4 `dailyPnL` recalculated: -6.8k → -9.6k (using correct Mar 3→4 price changes + sold positions)
- Mar 5 `dailyPnL` recalculated: +3.8k → +6.6k (using correct Mar 4→5 price changes)
- Mar 4 `positionsAtClose` updated with corrected closing prices

**CORS fix:** Browser `fetchTradingViewPrices` sent `Content-Type: application/json` which triggers a CORS preflight. TradingView's preflight response does not include `content-type` in `access-control-allow-headers`, blocking the request. Fixed by removing the header (browser sends `text/plain` = simple request, no preflight needed, TradingView accepts JSON body regardless).

**Root cause:** Code changes were not pushed to GitHub. See **CRITICAL DEPLOYMENT RULE** section above.

**Prevention:** All three environments (GitHub Pages, GitHub Actions cron, local browser) must run the same code. The only way to guarantee this is to push every change immediately. The deployment rule has been added to this README.

### Mar 5, 2026 — v2.20: Use TradingView's official % directly (never recompute)

**Root cause:** Daily % change was recomputed as `(currentPrice - previousClose) / previousClose * 100` everywhere. But `previousClose` came from different sources (browser TradingView fetch vs cron's snapshot closingPrices vs manual override) that could disagree. The cron stored `previousClose` from yesterday's snapshot — which may differ from TradingView's official previous session close (settlement differences, rounding). After market close, auto-refresh is blocked, so the browser showed the cron's stale % which didn't match TradingView.

**Fix — Use TradingView's `changePercent` and `change` directly:**
- **Cron (`update.py`, `update-us.py`):** Now fetches `change` and `change_abs` columns from TradingView Scanner API (previously only fetched OHLCV). Stores TradingView's official `changePercent` and `change` in priceCache. No more recomputation from snapshot-based previousClose.
- **Performance tab:** Uses `cached.changePercent` directly for the % column and `cached.change * quantity` for the $ column. Falls back to previousClose-based recomputation only for special cases (manual override, new-today positions, pre-market snapshot display).
- **Daily gain (header card + calendar):** Uses `cached.change * quantity` for dollar P&L instead of `(currentPrice - previousClose) * quantity`.
- **Snapshot dailyPnL:** Same change — uses `cached.change` from TradingView.
- **Wishlist:** Uses `cached.changePercent` and `cached.change` directly.
- **Fallback preserved:** Manual previousClose overrides, new-today entry price logic, intraday addition split, and pre-market snapshot display all still work via the recomputation path.
- Applied to both HK and US portfolios + both crons.

### Mar 5, 2026 — v2.19: TradingView Scanner API replaces Yahoo Finance

**Browser now uses TradingView Scanner API for all live price fetching**, matching the cron scripts which already used TradingView. Yahoo Finance is fully removed from the frontend.

- **Root cause:** Daily % change in the portfolio (e.g., 434.HK = +11.72%) didn't match TradingView's % (+12.45%) because the browser used Yahoo Finance's `previousClose`, which differed from TradingView's official exchange close.
- **Fix — TradingView Scanner bulk fetch:** Replaced `fetchYahooPrice` (sequential, one-by-one via CORS proxy) with `fetchTradingViewPrices` (single bulk POST to `scanner.tradingview.com/{market}/scan`). No CORS proxy needed — TradingView allows cross-origin from GitHub Pages. `previousClose` derived from TradingView's `change_abs` field: `prevClose = close - change_abs`.
- **Fix — All callers migrated:** `refreshPrices` (bulk), `refreshSinglePrice` (per-row), `addPosition` (auto-fetch), `addWishlistItem` (auto-fetch) — all now use TradingView.
- **Removed:** CORS proxy dropdown from Settings tab (no longer needed). Proxy migration code left as harmless dead code.
- **Simplified `addPosition`:** Removed Yahoo historical timeseries backfill for past entry dates. TradingView Scanner only returns current data.
- **TradingView links:** US portfolio links now include saved chart layout ID (`b8EBWJ7k`), opening in edit mode instead of view-only.
- **Performance:** Bulk refresh is now a single API call (~200ms) instead of N sequential requests with 500ms delays.
- **No impact on historical data:** Past snapshots' `closingPrices` and `dailyPnL` were already sourced from TradingView via the cron. Only live intraday display is affected.
- Applied to both HK and US portfolios.

### Mar 4, 2026 — v2.18: Fix stale `today` snapshot corruption

**Critical bug fix:** Selling a position could corrupt a PAST day's snapshot if the browser tab was left open overnight.

- **Root cause:** `const [today] = useState(...)` froze the UTC date at component mount time. If the user left the tab open from Mar 3 and sold positions on Mar 4 morning, `today` was still `"2026-03-03"`. The snapshot useEffect then overwrote the Mar 3 snapshot with Mar 4 data (wrong prices, wrong positions, wrong realizedPnL).
- **Incident (2026-03-04):** Mar 3 snapshot was overwritten when 0564.HK and 2510.HK were sold on Mar 4. The corrupt snapshot had 15 tickers (instead of 17), Mar 4 intraday prices, and post-sale realizedPnL. Displayed dailyPnL shifted from -19,323 to wrong value. Fixed via `patch-fix-mar3.py` — rebuilt with correct yfinance closing prices.
- **Fix 1 — Reactive `today` with midnight auto-update:** Changed `const [today] = useState(...)` to `useState(getMarketToday)` with a 60-second interval that detects date changes and triggers a re-render. Prevents stale date even if the tab is left open overnight without any user interaction.
- **Fix 2 — Past snapshot immutability guard:** Added a hard block: if a snapshot already has `closingPrices` and its date doesn't match the current market date, the useEffect refuses to overwrite it. Defense-in-depth layer that prevents any future code path from corrupting historical snapshots.
- **Fix 3 — Market-timezone `today`:** Replaced all UTC-based date calculations with market-timezone-aware `getMarketToday()`. HK uses `toLocaleString('en-CA', { timeZone: 'Asia/Hong_Kong' })`, US uses ET via `Intl.DateTimeFormat`. This ensures the portfolio date follows the market, not the user's local timezone — critical when traveling (e.g., Latin America while tracking HK market).
- **Fix 4 — All HKT helpers via Intl:** `isMarketOpen()`, `isPreMarket()`, `isAfterClose()`, `isBeforeMarketOpen()` all used the same broken manual offset (`hktOffset + localOffset` on `getTime()`). Since `getTime()` already returns UTC ms, adding `localOffset` double-converted — producing Mar 5 dates from Latin America when HKT was still Mar 4. Replaced all with shared `getHktNow()` helper using `toLocaleString('en-GB', { timeZone: 'Asia/Hong_Kong' })`. Zero manual offset calculations remain.
- Applied to both HK and US portfolios.

### Mar 3, 2026 — v2.17: Data Correction + Weekly Verification + Holiday Awareness

**Data correction:** Fixed wrong closing prices caused by Yahoo Finance returning stale/wrong data for HK stocks. Source of truth: Stooq individual stock pages (verified manually).

- **Feb 13 & Feb 16**: Replaced closingPrices with correct Stooq data (15 and 8 tickers affected respectively). Recalculated portfolioValue, dailyPnL, positionsAtClose
- **Mar 2**: Yahoo prices were wrong; corrected with real Stooq closes (e.g., 2643.HK: 35.08, not 31.60). dailyPnL: -19,516 HKD
- **Mar 3**: Created correct snapshot from Stooq (was previously a duplicate of Mar 2 data from FinMC mislabeling). dailyPnL: -19,323 HKD
- **dailyPnL cascade**: Recalculated all successor snapshots whose baselines changed
- **priceCache**: Updated with Mar 3 closes as `price`, Mar 2 closes as `previousClose`

**New: `verify-weekly.py`** — Compares Firebase snapshot closingPrices against FinMC/Stooq parquet data. Flags mismatches > 0.02 HKD and optionally fixes them with cascading dailyPnL recalculation.
```bash
python verify-weekly.py --dry-run     # Preview only
python verify-weekly.py --days 14     # Check last 14 days, fix mismatches
```

**New: HKEX holiday awareness in `update.py`** — Cron now skips weekends and HKEX holidays (2025-2026 calendar) instead of creating phantom snapshots with stale Yahoo data. Uses `is_trading_day()` check with early exit in `run()`.

**Root cause analysis:** Yahoo Finance is unreliable for HK stocks — returns stale prices, skips dates, and has timezone labeling issues. FinMC's yfinance gap-fill also missed Mar 2 entirely (jumped from Feb 27 to "Mar 3"). The weekly verification script and holiday awareness prevent these issues going forward.

### Feb 27, 2026 — v2.16
- **Post-close data protection** — Prevents Yahoo post-settlement values from overwriting cron's authoritative closing data
  - **Root cause:** When opening the app after market close (e.g., evening), the browser auto-refreshes Yahoo prices if cache is >5 min old. Yahoo can return slightly different post-settlement values, which overwrites the cron's closing prices in `priceCache` and recalculates today's snapshot with wrong data. This caused the daily value and Performance tab % changes to shift after hours.
  - **Gap 1 — Block auto-refresh after close:** Added `isAfterClose()` helper (HK: >=16:00 HKT, US: >=16:00 ET). The auto-refresh `useEffect` now returns early after market close or on closed days. Manual refresh button still works (explicit user choice).
  - **Gap 2 — Lock snapshot after close:** Today's snapshot is locked once market closes and cron data exists (`closingPrices` present). Only structural changes (position added/removed, trade closed) can update the snapshot — price-only recalculations are blocked.
  - **What still works:** Manual refresh button, cron updates (write directly to Firestore), structural snapshot changes, Firestore listener for cron updates.
  - Applied to both HK and US portfolios.
- **Fixed HKT timezone bug in `isMarketOpen`, `isPreMarket`, `isAfterClose`** — "pre" indicator was showing on weekends
  - **Root cause:** All three functions used `now.toISOString()` (UTC date) for the `isTradingDay()` check but converted to HKT for the time check. On the Friday UTC / Saturday HKT boundary (e.g., Saturday 7 AM HKT = Friday 11 PM UTC), the function saw Friday (trading day) + before 9:30 HKT → incorrectly returned "pre-market" on a Saturday.
  - **Fix:** Use the HKT date (`hktTime.toISOString()`) for the trading day check, matching the timezone used for the time check.
- **Patched Feb 27 snapshot** — Restored correct closing prices from cron #18 (16:30 HKT) via `patch-feb27.py`
  - Browser had overwritten cron data before the post-close protection was deployed. One-time Firestore patch restored the authoritative values (portfolio value: 967,745 HKD).
- **Renamed HK workflow** — "Daily Portfolio Update" → "Daily HK Portfolio Update" for clarity in GitHub Actions.

### Feb 24, 2026 — v2.15
- **Fixed TOTAL row alignment on mobile** (Positions + Performance tabs)
  - **Root cause:** The "Nom" column is hidden on mobile (`hidden md:table-cell`), but the TOTAL footer row used a fixed `colSpan` that counted the Nom column. On mobile, this caused all total values (%, Daily $, Weight) to shift one column to the right.
  - **Fix:** Replaced single `colSpan` with two responsive cells — `md:hidden` (reduced colSpan for mobile) and `hidden md:table-cell` (full colSpan for desktop). Applied to both Positions and Performance tables in both HK and US files.

### v2.14 (Feb 2026)
- **Fixed calendar vs Performance tab P&L discrepancy** — Calendar showed -2.9k while Performance summary showed -1288 for the same day
  - **Root cause 1:** Two separate P&L calculations existed — `dailyGain` (useEffect, used by header card + calendar) and `totalDailyDollar` (Performance tab render). They had different previousClose fallback behavior: the useEffect gated on `cached?.success && prevClose` (skipping positions without Yahoo data, contributing 0), while the Performance tab always computed a value for every position (falling back to `p.currentPrice`). When some tickers had stale cache data, the useEffect excluded them while the Performance tab included them.
  - **Root cause 2:** The useEffect's `yesterdaySnapshot` lookup did NOT filter by `isTradingDay()`, while the Performance tab's did. This could cause different `closingPrices` sources.
  - **Fix (calendar):** Calendar now uses `totalDailyDollar` directly (same computation as "Today's P&L" summary), eliminating any possible discrepancy between them.
  - **Fix (useEffect):** Rewrote dailyGain calculation to use the exact same previousClose priority chain as the Performance tab: override → newToday entryPrice → Yahoo previousClose → snapshot closingPrices → currentPrice. Removed the `cached?.success && prevClose` gate — every position always contributes to the gain.
  - **Fix (snapshot):** Same previousClose logic applied to `calculatedDailyPnL` stored in snapshots (immutable daily P&L for past days).
  - **Fix (yesterdaySnapshot):** Added `isTradingDay()` filter to the useEffect's snapshot lookup, matching the Performance tab's behavior.
  - **Applied to US portfolio only.** HK left unchanged.

### v2.13 (Feb 2026)
- **Fixed US snapshot persistence to Firestore** — Browser-created snapshots were lost on page refresh
  - **Root cause:** The auto daily snapshot `useEffect` saved snapshots to `localStorage` only (via `storage.set()`), never to Firestore. On page reload, Firestore is the source of truth and `localStorage` is cleared (line 882). Any snapshot created by the browser that wasn't also saved by the cron was permanently lost.
  - **Why HK was unaffected:** Same bug exists in HK code, but HK users (in Asia timezone) rarely keep the app open across midnight, reducing exposure. The cron reliably creates HK snapshots. US portfolio has wider timezone usage and more race conditions with the cron.
  - **Fix:** Replaced `storage.set()` (localStorage-only) with `saveData()` (Firestore primary, localStorage fallback) in the snapshot auto-save `useEffect`. Now browser-created snapshots survive page refreshes independently of the cron.
  - **Note:** This fix is US-only per user request (HK portfolio left unchanged since it works correctly).

### v2.12 (Feb 2026)
- **Fixed HK cron writing to wrong Firestore document** — Root cause of incorrect daily % changes
  - **Root cause:** `update.py` had `PORTFOLIO_DOC = "portfolios/main"` hardcoded, but the browser reads/writes to `portfolios/{userId}`. This created TWO separate documents — the cron-generated snapshots (with `closingPrices`) never reached Marc's actual document, so the browser fell back to Yahoo's `previousClose` (stale/wrong reference prices).
  - **Why dcharnal saw correct numbers:** When viewing Marc's portfolio as a friend, the email query (`where('ownerEmail', '==', ...)`) found `portfolios/main` (cron-updated), not `portfolios/{uid}`.
  - **Fix:** Refactored `update.py` to iterate ALL documents in the `portfolios` collection (same pattern as `update-us.py`). Extracted `update_portfolio()` function, replaced hardcoded path with `COLLECTION = "portfolios"` + `collection_ref.stream()`.
  - **Migration:** Created `migrate-main-to-uid.py` to merge cron-generated snapshots from `portfolios/main` into `portfolios/{marc_uid}`. Merges by date, preferring cron data (has `closingPrices`, `dailyPnL`, `positionsAtClose`). Run with `--delete-main` to clean up the orphan document.
- **Fixed previousClose extraction from Yahoo Finance** — Caused wrong daily % change (+2.35% or 0% instead of correct +1.25%)
  - **Root cause:** Both browser and cron extracted `previousClose` from Yahoo's timeseries `closes` array. When Yahoo returned `null` for recent trading days, the extraction logic picked wrong values (skipped to older days or landed on the same value as current price).
  - **Why `meta.previousClose` didn't work:** Yahoo returns `null` for `meta.previousClose` on HK stocks. `meta.chartPreviousClose` returns the close before the chart range (e.g., Feb 3), not yesterday's close.
  - **Fix (browser + cron):** New timestamp-based extraction — iterates backwards through raw timeseries, finds the most recent non-null close where `timestamp < UTC midnight today`. Correctly handles null gaps and timezone differences.
  - **Priority chain (Performance tab):** manual override → new today (entry price) → Yahoo `meta.previousClose` from priceCache → yesterday's snapshot closingPrices → current price
- **Fixed stale daily P&L in header/calendar** — Calendar showed -1600 while Performance tab showed -3895
  - **Root cause:** Header used stored `todaySnapshot.dailyPnL` (calculated earlier with wrong priceCache) instead of live data. Calendar copied the header value.
  - **Fix:** Header now always calculates today's daily P&L live from current priceCache. Past days still use stored snapshot values (immutable). Calendar and header are always consistent.
- **Fixed snapshotChanged not detecting dailyPnL changes** — Corrected live P&L was never saved back to Firestore
  - **Root cause:** The `snapshotChanged` check only compared `realizedPnL`, `positionCount`, and `capitalEngaged`. When only `dailyPnL` changed (e.g., from -1600 to -3895 after price fix), the save was skipped because no checked field had changed.
  - **Fix:** Added `Math.abs((todaySnapshot.dailyPnL || 0) - newDailyPnL) > 1` to the `snapshotChanged` condition.
- **Calendar: stored dailyPnL is immutable track record** — Past calendar values must NEVER be recalculated
  - **Lesson learned:** Attempted to "fix" past calendar values by recalculating from `closingPrices` instead of using stored `dailyPnL`. This broke correct historical values (Feb 2: -14.9k became -22k) because the recalculation doesn't account for position additions/removals between snapshots. Stored `dailyPnL` is the source of truth for past days — it captures the exact P&L at the moment it was recorded.
  - **Rule:** Calendar uses `snap.dailyPnL` for all past days. Only today is calculated live. If a past day's stored value is wrong, it must be patched directly in Firestore (one-time data fix), never recalculated from code.
  - **Patch applied:** Feb 10 `dailyPnL` was corrupted (-1615) because it was saved by the browser before the previousClose fix. Patched to -3895 via `patch-feb10.py` (one-time Firestore update).
- **Lowered auto-refresh cache threshold** from 30 min to 5 min — Prevents stale priceCache data from persisting after code fixes
- **Auto-redirect between HK/US portfolios at login** — Detects wrong-market tickers and redirects
- **Ported v2.11 `viewingFriendRef` race condition fixes from US to HK**
- **Emptied hardcoded `INITIAL_POSITIONS`** for new users (both HK and US)

### v2.11 (Feb 2026)
- **Fixed friend portfolio return bug** — Applied to both `index.html` (HK) and `index-us.html` (US)
  - Root cause 1: Async race in `refreshPrices` — stale closure could overwrite restored backup with friend's positions
  - Root cause 2: Snapshot useEffect could save friend data to own localStorage (state-based guard had timing gap)
  - Root cause 3: `returnToOwnPortfolio` silently failed when backup was missing
  - Fix: Added `viewingFriendRef` guards to auto-refresh, snapshot save, and refreshPrices save path
  - Fix: `returnToOwnPortfolio` now clears friend state FIRST, falls back to Firestore reload if backup is null, and switches to portfolio tab
  - **Incident (2026-02-10):** HK version was missing `viewingFriendRef` guards while US had them. Marc's HK portfolio got stuck showing friend's US data. Ported all 7 guards from US to HK — resolved.
- **Dynamic currency label** - Shows HKD when viewing a friend's HK portfolio, USD otherwise
  - All UI labels (P&L, charts, tooltips, inputs) switch dynamically
  - Previously hardcoded "USD" everywhere
- **Friend daily P&L now shows friend's data** - Was stuck showing own P&L when viewing friend
  - Split snapshot useEffect: dailyGain calculation runs for friend views (read-only), snapshot saving remains guarded
- **Dual portfolio setting** - New `enableDualPortfolio` toggle in Settings > Configuration
  - When off (default): "Autre Portfolio" link hidden in Settings
  - When on: Portfolio switch link appears
  - Prevents accidental navigation for users with only one portfolio
- **UI: Friend input button renamed** - "Voir" → "Ajouter" for clarity (the button adds + views)
- **Removed hardcoded personal data from `INITIAL_POSITIONS`** - New users were getting Marc's portfolio as default
  - `INITIAL_POSITIONS`, `INITIAL_CLOSED_TRADES`, `INITIAL_TRANSACTIONS` now empty `[]`
  - Each user's data lives exclusively in Firestore — no hardcoded fallback
  - `index-us.html` already had empty defaults; HK version now matches
  - **Incident (2026-02-10):** dcharnal@gmail.com (new account) loaded Marc's 16 HK positions on first login. Fixed by emptying defaults + Reinitialiser on the affected account.

### v2.10 (Feb 2026)
- **Fixed US portfolio price refresh** - All positions were failing to update
  - **Root cause 1: Dead CORS proxies** - `allorigins.win` (408/522), `corsproxy.io` (403), `cors.sh` (308) all broken
  - Fix: Added Cloudflare Worker (`yahoo-proxy.marccharnal.workers.dev`) as primary proxy (same as HK version)
  - Auto-migration: existing users with dead proxy saved in Firestore are automatically switched to Cloudflare Worker on load
  - Migration persists to Firestore so it sticks across sessions
  - **Root cause 2: Tickers stored with `.HK` suffix** - Positions entered as `GOOG.HK` instead of `GOOG`, causing Yahoo Finance 404
  - Fix: `convertOldTicker()` now strips `.HK` suffix and trims whitespace (also caught `COIN ` with trailing space)
  - Migration cleans positions, closedTrades, wishlist tickers, and priceCache keys
  - Cleaned data auto-persists to Firestore
  - **Root cause 3: GitHub Actions cron never ran** - `daily-update-us.yml` had YAML syntax error (fixed in `bafe854`, first successful run triggered manually)
- **Fixed auto-refresh race condition** - Price refresh was firing before proxy migration completed
  - Auto-refresh `useEffect` now depends on `settings.corsProxy` to wait for correct proxy
- **US friend viewing: prioritize US collection** - `viewFriendPortfolio` now searches `us-portfolios` before `portfolios`
  - Falls through to HK if friend has no US portfolio
- **Cron safety** (`update-us.py`) - Strips `.HK` suffix and whitespace from tickers before Yahoo API calls
- **Updated README** - Files table, cron docs, and HK/US business rules reference table

### v2.9 (Feb 2026)
- **Friend viewing is now READ-ONLY** - When viewing a friend's portfolio:
  - Purple-tinted background (visual distinction from your own portfolio)
  - All edit buttons hidden (add position, delete, close position)
  - All wishlist edit buttons hidden
  - All transaction edit buttons hidden
  - Prevents accidental modifications to friend's data
- **Invite notifications** - When someone adds you as a viewer:
  - Popup appears on login: "X a partagé son portfolio avec toi"
  - Shows portfolio type (🇭🇰 HK or 🇺🇸 US)
  - "Voir" button to immediately view their portfolio
  - Invites stored in `viewerInvites` Firestore collection
  - Requires updated security rules (see README)
- **Fixed US portfolio friend viewing bug** - Was querying wrong Firestore collection
  - Bug: friend viewing in `index-us.html` queried `portfolios` (HK) instead of `us-portfolios`
  - Result: US portfolio was showing HK positions when viewing a friend
  - Fix: Changed line 1536 to query `us-portfolios` collection
- **Fixed daily P&L on weekends** - Now correctly shows $0 on Saturday/Sunday
  - Bug: Was showing Friday's P&L value on weekends
  - User expectation: $0 because no trading happened on Saturday
  - Fix: Simplified weekend logic to always show 0
- **UI: Removed dashed border from Prev Close field** - Cleaner look in Performance tab
- **UI: Settings tab reorganized** - Share/View friend sections moved to top for easier access

### v2.8 (Feb 2026)
- **Intraday position additions** - Accurate daily P&L when adding shares during market hours
  - Previously: adding 9000 shares to existing 10000 shares would calculate daily P&L using yesterday's close for ALL 19000 shares (incorrect)
  - Now: splits calculation between old shares (use previous close) and new shares (use purchase price)
  - Example: 10000 old @ prev close 3.08, add 9000 new @ 2.90, current 2.88
    - Old: (2.88 - 3.08) × 10000 = -2000
    - New: (2.88 - 2.90) × 9000 = -180
    - Total: -2180 (not -3800 as before)
  - Temporary fields stored on position: `addedTodayDate`, `addedTodayQty`, `addedTodayPrice`, `qtyBeforeToday`
  - Fields automatically cleaned up after daily snapshot
  - Supports multiple additions in same day (accumulates correctly)
  - Applied to: live daily gain, snapshot P&L, Performance tab, backend cron

### v2.7 (Feb 2026)
- **Enriched cron snapshots** - `update.py` now stores complete snapshot data
  - `closingPrices` for all positions (enables accurate next-day % change)
  - `dailyPnL` calculated from yesterday's closing prices
  - `positionsAtClose` with full position details (audit trail)
  - Previously only stored basic metrics (portfolioValue, capitalEngaged)
- **Calendar backfill** - Missing trading days are automatically estimated
  - If a day has no snapshot, P&L is estimated from surrounding snapshots
  - Distributes unrealized+realized change evenly across gap days
  - Prevents empty holes in the calendar
- **Calendar uses dailyGain state for today** - Today's calendar cell uses the same value as the header "Aujourd'hui" card, ensuring consistency
- **3-layer data protection for daily snapshots:**
  1. Cron (`update.py`) runs every weekday at 16:30 HKT with complete data
  2. Frontend creates/updates snapshot when app is open
  3. Backfill estimates missing days from adjacent data
- **Colored P&L tooltips** - Weekly/Monthly chart tooltips now show P&L in green (positive) or red (negative) instead of hard-to-read black text
- **History starts Feb 2026** - January data excluded (unreliable without starting point)
- **Immutable dailyPnL** - Calendar P&L values no longer change when snapshots are modified
  - Each snapshot stores `dailyPnL` at creation time
  - Historical values are preserved even when positions change
- **Position audit trail** - Snapshots now store `positionsAtClose` array
  - Full details: ticker, name, qty, entry price, closing price, P&L
  - Useful for recovery and historical analysis
- **Calendar day click modal** - Click any day to view snapshot details
  - Shows positions held at close
  - Edit portfolioValue and dailyPnL if needed
  - Debug section with calculation breakdown
- **Improved P&L calculation** - Calendar fallback now uses closingPrices difference
  - Handles new purchases correctly (old method used unrealizedPnL diff)
  - Uses positionsAtClose when available for accurate calculation
- **Live market indicator** - Orange pulsing "live" dot on "Aujourd'hui" tile
  - Shows when HK market is open (9:30-12:00, 13:00-16:00 HKT)
- **TradingView links** - Click tickers to open personal TradingView chart (owner only)
- **Performance tab sorting** - Click column headers to sort by % Change, Daily $, Weight

### v2.6 (Feb 2026)
- **Accurate daily % change** - Performance tab now uses stored closing prices
  - Snapshots now store `closingPrices` for all positions at end of day
  - Daily % change calculated from our own data (not Yahoo's unreliable previousClose)
  - Yahoo's `meta.previousClose` was returning stale data (2+ days old)
  - Priority: manual override → yesterday's stored price → Yahoo previousClose → current price
- **Manual previousClose editing** - Edit previousClose directly in Performance tab
  - Click on the Prev Close cell to edit the value
  - Useful for positions added after snapshot creation (missing closingPrices)
  - Stored in priceCache as `previousCloseOverride`
- **Market Holiday support** - Market closed days handled correctly
  - HK: HKEX holidays (14 days/year)
  - US: NYSE holidays (10 days/year)
  - No snapshots created on holidays
  - Previous close uses last trading day (skips holidays)
  - Calendar greys out holidays
  - Holidays hardcoded for 2025-2027
- **Cloudflare Worker CORS proxy** - Custom proxy for reliable Yahoo Finance API
  - Primary proxy: `https://yahoo-proxy.marccharnal.workers.dev/`
  - Fallback to allorigins and corsproxy.io
- **Per-row refresh button** - Manually refresh individual stock prices in Performance tab
- **US Portfolio synced** - index-us.html now has all v2.6 features (closingPrices, NYSE holidays)

### v2.5 (Feb 2025)
- **Wishlist Tab** - Track stocks you want to buy
  - Add tickers with target buy price
  - Live price fetching from Yahoo Finance (included in Refresh)
  - Gap calculation (current price vs target)
  - **Target reached alerts** - Banner notification when price hits target
  - Dismissible alerts (persisted - won't show again until price cycles)
  - Date added tracking
  - Notes field for buy rationale
  - Visual highlighting: green for target reached, yellow for close (≤5%)
- **Friend Portfolio Viewing** - Share your portfolio with friends
  - In Settings, add emails of people who can view your portfolio
  - Friends can then enter your email to view your portfolio (read-only)
  - Visual banner indicates viewing mode
  - Easy "Return to my portfolio" button
  - Requires updated Firebase security rules (see README)
- **Weekend handling** - Market closed on Saturday/Sunday
  - No snapshots created on weekends
  - Calendar excludes weekend days from P&L display
  - "Aujourd'hui" tile shows "Vendredi" with Friday's P&L on weekends
  - Timezone-safe weekend detection
- **Partial sell cost basis adjustment** - When selling part of a position:
  - Profit from sold shares reduces the entry price of remaining shares
  - Example: Buy 1000 @ $10, sell 500 @ $12 → remaining 500 @ $8
  - Ensures accurate P&L tracking on remaining position
- **Position averaging** - Adding to existing positions:
  - If ticker already exists, quantities are merged
  - Entry price recalculated as weighted average
  - Example: 1000 @ $10 + 500 @ $13 → 1500 @ $11
  - See v2.8 for intraday addition P&L accuracy fix
- **Wishlist alert popup** - On login notification:
  - Popup appears when stocks reach target price
  - Shows all triggered alerts with current vs target price
  - Quick navigation to Wishlist tab
- **UI improvements**
  - Wider price input field for 5-6 digit prices
  - Entry price now editable in positions table
- **US Portfolio synced** - index-us.html now has all v2.5 features

### v2.4 (Jan 2025)
- **US Portfolio Version** - New `index-us.html` for US stocks
- Same layout and features as HK portfolio
- USD currency formatting
- US ticker format (AAPL, MSFT) - no suffix required
- Separate Firestore collection (`us-portfolios/{userId}`)
- Updated security rules for both HK and US portfolios
- **Portfolio switch** - Navigate between HK/US via Settings tab (🇭🇰/🇺🇸 buttons)
- Separate localStorage keys to prevent data mixing

### v2.3 (Jan 2025)
- **Firebase Authentication** - Email/password login required
- **Multi-user support** - Each user has their own isolated portfolio
- Secure Firestore rules (users can only access their own data)
- Login screen with error handling (French UI)
- Logout button in Settings tab
- Account info displayed in Settings
- Compact metric cards on mobile (4 per row, smaller fonts)
- Failed tickers shown by name in price refresh alerts

### v2.2 (Jan 2025)
- Light mode: soft lime-tinted background (#f4f6ef) inspired by Zentry app
- Danger row highlighting on Performance tab (same as Positions)
- More visible red/orange backgrounds for danger/warning rows in light mode
- Stop-loss emoji (🚨) visible on both Positions and Performance tabs

### v2.1 (Jan 2025)
- Added dark mode with toggle (sun/moon icon)
- Dark mode enabled by default
- Modern donut pie chart with muted colors
- Compact positions table layout
- Improved text readability in dark mode
- Blue active tab styling
- Reordered tabs: Positions/Performance/Trades/History/Settings

### v2.0 (Jan 2025)
- Migrated from localStorage to Firebase Firestore
- Real-time multi-device sync
- Removed manual Push/Pull sync buttons
- Daily cron via GitHub Actions
