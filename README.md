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
| `verify-daily.py` | Post-cron self-check: per-ticker close/changePct + dailyPnL drift vs TradingView (`hk` / `us` arg). Fails the GitHub Actions run on >0.02 close, >0.05pp changePct, or >50 in dailyPnL drift |
| `patch-snapshot-dailypnl.py` | Reusable backfill: corrects any snapshot's `dailyPnL` given `TARGET_DATE PREV_DATE` args. Use when a cron ran before a formula fix. Run: `GOOGLE_APPLICATION_CREDENTIALS=... python3 patch-snapshot-dailypnl.py 2026-05-05 2026-05-04 --dry-run` |
| `patch-may6-2865-fix.py` | One-time fix: delete erroneous 2865.HK closed trade (fake 900-share sale from qty entry mistake); correct open position qty to 900; remove stale `addedToday*` fields |
| `patch-may6-closes-from-yahoo.py` | One-time fix: replace 12 wrong May 6 stored closes with Yahoo's settled values; recompute `dailyPnL` (295 → 3,863 HKD), `portfolioValue`, `unrealizedPnL`, and per-ticker `priceCache.previousClose`. Root cause was the 16:30 cron capturing pre-CAS prints (1913.HK off by 1.02 HKD). Idempotent — safe to re-run. |
| `verify-yesterday-pnl.py` | Audits a past snapshot's stored `dailyPnL` against the cron formula (open positions session move + closed-today `(exit − prior_close) × qty`). Skips false positives from retroactive `realizedPnL` patches. Usage: `python3 verify-yesterday-pnl.py hk 2026-05-06`. |
| `patch-may4-dailypnl.py` | One-off predecessor to `patch-snapshot-dailypnl.py` — left for reference |
| `audit-month.py` | Monthly P&L audit: verifies all snapshots in any calendar month against closing-price derivation (open positions, new-position entry-day, closed-trade session move). Usage: `python3 audit-month.py 2026-03`. Drift threshold: 50 HKD. |
| `patch-apr13-dailypnl.py` | One-time fix: Apr 13 dailyPnL −14,821 → −17,329 (closingPrices were patched post-cron in the Apr 13 incident series; dailyPnL was not realigned at the time) |
| `patch-apr14-dailypnl.py` | One-time fix: Apr 14 dailyPnL +10,558.9 → +12,444 (1167.HK closed that day; session move (exit − prior_close) × qty was not fully captured by the cron) |
| `patch-data-correction.py` | One-time patch: fix Feb 13/16, Mar 2 closingPrices from Stooq |
| `verify-weekly.py` | Weekly verification: Firebase snapshots vs FinMC/Stooq parquet data |
| `migrate-main-to-uid.py` | One-time migration: portfolios/main → portfolios/{uid} |
| `patch-apr24.py` | One-time fix: Apr 24 dailyPnL 9,720→6,134, 2175.HK 3.43→3.41, phantom Apr 27 deletion |
| `patch-apr23-closes.py` | One-time fix: Apr 23 closingPrices realigned to TradingView settlement (CAS-vs-settlement drift) |
| `patch-april-dailypnl.py` | One-time fix: align April dailyPnL fields with current totalPnL deltas |
| `patch-all-months-dailypnl.py` | Generalization of the above across all months — reconciles calendar `monthTotal` with chart endpoint after retroactive closingPrices patches |
| `.github/workflows/daily-update-hk.yml` | GitHub Actions workflow (HK, **16:45 HKT** — moved from 16:30 on 2026-05-07 to clear the Closing Auction settlement window) — runs `update.py` then `verify-daily.py hk` |
| `.github/workflows/daily-update-us.yml` | GitHub Actions workflow (US, **16:10 ET** — moved from 16:00 on 2026-05-07 to clear the closing-cross settlement window) — runs `update-us.py` then `verify-daily.py us` |

---

## HK / US Sync Status

Both `index.html` (HK) and `index-us.html` (US) share the same core features but are maintained as separate files. When making changes, **always apply to both files** unless the change is market-specific.

| Feature / Fix | `index.html` (HK) | `index-us.html` (US) | Date Synced |
|---|:---:|:---:|---|
| Cron cross-checks TradingView vs Yahoo per held ticker; Yahoo wins beyond tolerance (HK: 0.05 HKD/0.5%, US: 0.05 USD/0.3%); snapshot stores `settledAt` / `sources` / `provisional` / `priceProvenance` | ✅ | ✅ | 2026-05-07 |
| Cron retimed past closing-auction window — HK 16:30 → **16:45 HKT**, US 16:00 → **16:10 ET** | ✅ | ✅ | 2026-05-07 |
| `~` marker on calendar tiles flagged provisional (Yahoo unreachable for ≥1 ticker) | ✅ | ✅ | 2026-05-07 |
| Snapshot modal shows green "Settled" / amber "Provisional" pill with timestamp; per-ticker source tag (`· yahoo` / `· ✓` / `· tv-only`) in debug breakdown | ✅ | ✅ | 2026-05-07 |
| Snapshot modal "P&L recalculé" debug breakdown now includes closed-today trades (`(exit − prior_close) × qty`) — was off by 846 HKD on May 6 (missed the 2865.HK closure leg) | ✅ | ✅ | 2026-05-07 |
| Trash icon on sold rows in Today's Movers; `deleteClosedTrade(id)` removes erroneous closed trades from Firestore | ✅ | ✅ | 2026-05-07 |
| Editable quantity field in Positions tab; `updateQuantity(id, qty)` saves to Firestore on blur/Enter | ✅ | ✅ | 2026-05-07 |
| Block manual Refresh button outside market hours (pre-market + after-close); add `isPreMarketUS()` helper to US file | ✅ | ✅ | 2026-05-05 |
| Fix cron `dailyPnL` overcount: replace `realized_pnl−yesterday_realized` with `(exitPrice−prevClose)×qty` for positions closed today | ✅ | ✅ | 2026-05-06 |
| Pre-market Performance tab: `totalDailyDollar` reads `yesterdaySnapshot.dailyPnL` directly (authoritative cron value); drop `closedLastSessionDollar` IIFE | ✅ | ✅ | 2026-05-06 |
| Fix `verify-daily.py` Check 3 formula (was using same overcount as cron bug); add Check 4 (8% sanity cap on dailyPnL vs portfolio value) | ✅ | ✅ | 2026-05-06 |
| Cron `dailyPnL` uses TV `change_abs × qty` (not yesterday's stored closingPrices) — fixes calendar/Performance divergence | ✅ | ✅ | 2026-04-26 |
| Performance tab pre-market path uses `cached.change` directly (drop `!preMarketActive` from `useTvDirect` gate) | ✅ | n/a (US already had this) | 2026-04-26 |
| Pre-market guard against phantom future-date snapshots when opening from a westward timezone | ✅ | n/a (US already had this) | 2026-04-26 |
| Post-cron self-check (`verify-daily.py`) wired into GitHub Actions for both markets | ✅ | ✅ | 2026-04-26 |
| Fix HKT midnight bug: correct `entryDate` for positions added after midnight UTC (shows as next-day, breaking `isNewToday` logic) | ✅ | ✅ | 2026-04-14 |
| Add position: green checkmark feedback (1.5s) on successful add | ✅ | ✅ | 2026-04-14 |
| Fix pre-market P&L for new-today positions: use `cached.previousClose` instead of missing snapshot data | ✅ | ✅ | 2026-04-14 |
| Fix timezone bug: `hktDateStr()` replaces `toISOString()` in calendar (weekTotal + backfill) | ✅ | — | 2026-04-10 |
| Fix weekTotal week 1: exclude previous-month days from sum | ✅ | — | 2026-04-10 |
| Fix HKEX_HOLIDAYS 2026: remove incorrect `2026-04-07` (Easter Monday = Apr 6) | ✅ | — | 2026-04-10 |
| Fix `update.py` HKEX_HOLIDAYS: same `2026-04-07` removal | ✅ | — | 2026-04-10 |
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
                  && request.auth.token.email_verified == true
                  && request.auth.token.email in resource.data.allowedViewers;
    }
    // US Portfolio
    match /us-portfolios/{userId} {
      // Owner can read/write their own data
      allow read, write: if request.auth != null
                         && request.auth.uid == userId;
      // Allowed viewers can read (for friend portfolio feature)
      allow read: if request.auth != null
                  && request.auth.token.email_verified == true
                  && request.auth.token.email in resource.data.allowedViewers;
    }
    // Viewer Invites (notifications when someone shares their portfolio)
    match /viewerInvites/{inviteId} {
      // Only owner can create invites (ownerUid must match auth uid)
      allow create: if request.auth != null
                    && request.resource.data.ownerUid == request.auth.uid;
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
git add index.html index-us.html update.py update-us.py .github/
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
1. Lire [PRD.md](PRD.md) pour comprendre l'architecture et les règles métier
2. Tester en local avec `python -m http.server 8000`
3. Vérifier que les calculs de fees et seuils respectent les règles documentées

### After Making Changes
1. Mettre à jour [PRD.md](PRD.md) si:
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

### May 7, 2026 — v2.28: TV+Yahoo two-source reconciliation, cron moved to 16:45 HKT, settled/provisional badges

**Symptom (Thu May 7 morning, Paris time):** the calendar tile for Wed May 6 showed +295 HKD when it had been ~3k HKD the night before. User frustrated — "every day there is an issue with this app."

**Root cause — single-source CAS-vs-settlement drift on illiquid HK names:**
The 16:30 HKT cron pulled TradingView Scanner once and stored its `close` field as the day's official close. But TV's scanner at 16:30 occasionally serves the last traded price *before* the Closing Auction Session settles, not the post-CAS settlement. Cross-checking [Marc's May 6 snapshot](#) against Yahoo (which derives daily close from HKEX's published settlement) revealed **12 of 14 tickers were wrong**, with 1913.HK the worst at **35.76 stored vs 36.78 real (-1.02 HKD × 2,300 qty = -2,346 HKD)**. Total impact on stored `dailyPnL`: -3,568 HKD. Real settled P&L was +3,863 HKD, not the +295 the cron locked in.

**This isn't a one-off** — the same class of bug appeared on Mar 5, Apr 23-24, Apr 26. Each time we patched the affected closes manually after the user noticed. Today's fix attacks the source: never trust a single price feed on settlement day.

**Fix v2.28 — `update.py` Yahoo cross-check:**
- New `reconcile_with_yahoo(tv_prices, positions, target_date)` runs after the TV bulk fetch. For each held ticker, it queries Yahoo's daily close (tries 4 ticker-format candidates: unpadded, 4-digit, 5-digit; gracefully skips on Yahoo unreachable).
- Tolerance: **0.05 HKD or 0.5%**, whichever is larger. Inside tolerance → both sources agree, keep TV. Outside → Yahoo wins (it's exchange-aligned), and `tv_prices[ticker].close` / `changeAbs` / `changePercent` are mutated in place so all downstream snapshot logic uses the reconciled value.
- If Yahoo is unreachable for a ticker, that ticker is marked `provisional` and TV is kept as fallback.
- Snapshot now persists four new fields: `settledAt` (ISO timestamp), `sources` (`["tradingview", "yahoo"]`), `provisional` (true if any held ticker couldn't be confirmed), and `priceProvenance` (per-ticker `{source, tvClose, yahooClose, chosen, drift}` map).

**Cron retiming — `daily-update-hk.yml`:** `08:30 UTC → 08:45 UTC` (16:30 HKT → **16:45 HKT**). 35 min after CAS ends (16:10 HKT) gives both TV and Yahoo time to flush post-auction settlement.

**Mirrored to US — `update-us.py`, `daily-update-us.yml`, `index-us.html`:** Same architecture applied to the US side. Cron retimed `21:00 UTC → 21:10 UTC` (16:00 ET → **16:10 ET**). Tolerance tightened to 0.05 USD / 0.3% because US names are deeper-liquidity. Full UI parity later the same day: clickable calendar tiles + snapshot detail modal (Settled/Provisional pill, positions table, debug breakdown with closed-today + per-ticker source tag), `~` provisional marker, editable quantity field on Positions tab, and trash icon on sold rows in Today's Movers — every HK-side row in the sync table now reads ✅ ✅.

**Fix — UI surfaces reconciliation status:**
- Snapshot modal header gains a pill: green "Settled · tradingview + yahoo" with HKT lock time, or amber "Provisional — réconciliation incomplète" if `provisional: true`.
- Calendar tiles flagged provisional get a small amber `~` glyph in the top-right corner.
- Debug breakdown ("Recalcul via closingPrices") now tags each row with the source: `· yahoo` (corrected), `· ✓` (TV+Yahoo agreed), `· tv-only` (Yahoo unreachable).

**Bonus fix — closed-today contributions in the P&L breakdown:**
The "Recalcul via closingPrices" inside the snapshot modal was iterating `positionsAtClose` only and **missing the closed-today trade leg entirely**. On May 6 it summed to -551 HKD (open positions only) and disagreed with the stored 295 by exactly the 2865.HK closure (+846), making the stored value look corrupted when it wasn't. Added closed-today rows with `(exit − prior_close) × qty` and a `✖ closed` tag.

**Fix — `verify-yesterday-pnl.py` formula:**
Old version computed `derived = closingPrices Δ + total realizedPnL Δ`. When a phantom-trade cleanup patch retroactively modified `realizedPnL` (as `patch-may6-2865-fix.py` did), the verifier flagged the day as "drifted" even though the session P&L was correct. Replaced with the cron formula: `(close − prior_close) × qty` for open positions + `(exit − prior_close) × qty` for closed-today trades. Reports realized-Δ separately as a book-keeping sanity check, doesn't fail the run on it.

**Data patch applied:** `patch-may6-closes-from-yahoo.py` — corrected May 6 stored closes for 12 tickers (0177, 0285, 0434, 113, 1316, 1585, 1698, 1913, 1999, 2643, 9690, 9988), recomputed `dailyPnL` 295 → 3,863 HKD, `portfolioValue` 897,948 → 901,516 HKD, `unrealizedPnL` -124,803 → -121,235 HKD, and updated each ticker's `priceCache.previousClose` so today's UI uses the correct baseline.

**Lessons:**
1. **Two sources beat one, every time.** A single feed at a fixed time captures whatever that feed serves at that moment. CAS prints, settlement reconciliations, and exchange data lags all break single-source freshness assumptions on HK names. Yahoo + TV agreement is much harder to be wrong about than either alone.
2. **Make freshness state visible.** The user couldn't tell whether a calendar tile was settled or still drifting. The new "Settled / Provisional" badge + per-ticker source tag means a glance answers "is this number final?"
3. **Verify scripts must use the same formula as the cron.** `verify-yesterday-pnl.py` was using a different P&L decomposition and reported false drifts after every retroactive patch. Same lesson as v2.25's `verify-daily.py` Check 3 fix — guards that don't mirror the system they guard are noise.
4. **Cron timing matters in microstructure.** 16:30 HKT was 20 min after the CAS auction kicked off and 5 min before settlement was reliably flushed across TV's fan-out. Pushing to 16:45 closes that window cheaply; fundamentally the two-source cross-check is what makes us robust to whatever TV or Yahoo do at the boundary.

### May 6, 2026 — Historical audit: Jan / Mar / Apr P&L verification

**New reusable tool: `audit-month.py`** — verifies every snapshot in a calendar month using the correct dailyPnL formula: open positions `(close − prior_close) × qty`, new positions entered that day `(close − entry_price) × qty`, closed-today positions `(exit − prior_close) × qty`. Drift threshold 50 HKD. Usage: `python3 audit-month.py 2026-03`.

**March 2026:** 22 days audited — all clean. Monthly total −99,006 HKD verified.

**January 2026:** 5 snapshots internally consistent (stored dailyPnL = totalPnL delta for all days). Closing-price verification not possible for Jan 26–29: those early snapshots pre-date the `positionsAtClose` / `closingPrices` fields. All 4 days confirmed correct via totalPnL delta cross-check.

**April 2026 — 2 real drifts found and patched:**
- `patch-apr13-dailypnl.py` — Apr 13: −14,821 → **−17,329** HKD. Root cause: closingPrices for 113.HK and 3680.HK were patched post-cron during the Apr 13 incident series, but dailyPnL was not realigned. The `patch-april-dailypnl.py` run on Apr 26 used the `totalPnL delta` approach, which relied on stale `unrealizedPnL` in the snapshot (written by the original cron, not updated by the closingPrice patches) — so the realignment was incomplete.
- `patch-apr14-dailypnl.py` — Apr 14: +10,558.9 → **+12,444** HKD. Root cause: 1167.HK (14,100 shares) was closed that day; the correct session contribution is `(7.58 exit − 7.05 prior_close) × 14,100 = +7,473 HKD`, but the stored value underweighted it by 1,885 HKD.

### May 6, 2026 — v2.26–v2.27: trash icon on sold rows + editable quantity

**v2.26 — Trash icon on sold rows (Today's Movers):** When a closed trade appears in the Today's Movers table with a `(sold)` label, it now shows a red trash icon in the action column instead of an empty cell. Clicking it triggers a confirmation dialog and permanently deletes the closed trade from Firestore via a new `deleteClosedTrade(id)` function. Hidden in friend-view mode. Motivation: entry mistakes (e.g., typing wrong qty then correcting it) can generate a phantom "sale" in `closedTrades` that never happened — the trash icon lets the user remove it without a patch script.

**v2.27 — Editable quantity field (Positions tab):** The qty column in the Positions table is now an editable input (same style as Entry Price), backed by a new `updateQuantity(id, qty)` function. Click the field, type the correct integer, press Enter or click away — saves to Firestore instantly. Validates: positive integers only, ignores blank/zero input.

**Data patch applied:** `patch-may6-2865-fix.py` — deleted erroneous 2865.HK closed trade (qty 900, entry 33.1, exit 35.2, fake profit ~1,890 HKD) and corrected open position qty to 900, removing stale `addedTodayQty/Price/Date` and `qtyBeforeToday` fields left over from the failed entry.

### May 5-6, 2026 — v2.23–v2.25: fix dailyPnL overcount on days with closed positions

**Symptom:** Header "DERN. SÉANCE fermé" showed +7,507 HKD while Performance tab "Dernière séance P&L" showed +2,267 HKD. Calendar tile for Tuesday May 5 was permanently stuck at 7,507 even after a hard refresh.

**Root cause — the cron's `dailyPnL` overcounted on any day a position was closed:**

`update.py` computed `daily_pnl += (realized_pnl - yesterday_realized)` for the closed-trade contribution. `realized_pnl` is the **full entry-to-exit profit** (e.g. bought at 9.00, sold at 10.62 = +9,720 HKD). But every prior day's tile had already recorded the daily move of that position while it was held. The closing day then replayed the entire realized gain instead of just the session's move (10.62 − 10.56) × qty. Result: the closing day's tile was inflated by every prior session's unrealized gain that had already been counted.

**Fix v2.24 — cron (`update.py`, `update-us.py`):** Replaced the `realized_pnl − yesterday_realized` block with a loop over `closedTrades` where `exitDate == today`, adding `(exitPrice − yesterday_closing[ticker]) × qty` per trade. Session-move only. Same formula the browser already used.

**Fix v2.25 — browser pre-market Performance tab:** In pre-market, `totalDailyDollar` now reads `yesterdaySnapshot.dailyPnL` directly — the same authoritative value already shown in the header card and calendar. Prior approach (`closedLastSessionDollar` IIFE) introduced a delta not reflected in the movers table, causing "Dernière séance P&L" to show a total that didn't match the sum of visible rows.

**Fix v2.23 — Sync button blocked outside market hours:** The auto-refresh was already guarded but the manual Sync button had no `disabled` state. Added the same guard. Added `isPreMarketUS()` helper to `index-us.html`. Prevents priceCache corruption from pre-opening auction prices (9:00–9:30 HKT).

**Historical patches applied to Firestore:**
- `patch-may4-dailypnl.py` — May 4 snapshot: 17,475 → 13,595 HKD (no closed positions; pure unrealized correction)
- `patch-snapshot-dailypnl.py 2026-05-05 2026-05-04` — May 5 snapshot: 7,507 → 2,067 HKD (856.HK 6000 shares closed; session move = (10.62 − 10.56) × 6000 = 360 HKD, not the full realized gain)

**Fix — `verify-daily.py` Check 3 formula (also had the same bug):**
The post-cron verifier was computing `expected_pnl` using `realizedPnL − yesterday_realizedPnL` — the exact same overcount formula. This meant it was approving the inflated values instead of flagging them. Fixed to use `(exitPrice − yesterday_closing) × qty` per closed trade, matching the corrected cron. Also added **Check 4**: if `abs(dailyPnL) / portfolioValue > 8%`, the GitHub Actions run fails regardless of TV agreement — catches any future gross overcount.

**Lessons:**
1. **The cron's `dailyPnL` is authoritative.** In pre-market, the browser must display it directly — not reconstruct it from individual position deltas. Any reconstruction that omits closed positions will silently diverge.
2. **Verify scripts must use the correct formula.** A guard that mirrors the bug it's meant to catch provides zero protection. Both the cron and the verifier had the same `realized_pnl − yesterday_realized` formula — both needed to be fixed.
3. **A `patch-snapshot-dailypnl.py TARGET PREV` script is now the canonical backfill tool** for any future cron formula regression.

### Apr 26, 2026 — v2.22: cron uses TV change_abs, post-cron verifier, phantom-snapshot guard, dailyPnL/calendar reconciled

**Symptom (Sun Apr 26 evening, Paris time):** calendar tile for Friday Apr 24 showed +9,720 HKD while the Performance tab "Daily $" total summed to +6,314 HKD. The 3,586 HKD divergence was the visible end of three independent bugs.

**Bug 1 — cron `dailyPnL` baseline.** `update.py` computed `dailyPnL = (today_close − yesterday_snapshot.closingPrices[t]) × qty`. But yesterday's stored closingPrices were captured at 16:30 HKT during the Closing Auction Session and were 1–12 cents off settlement on most tickers. The browser, by contrast, sums TV's official `change_abs × qty`, so the two views drifted whenever the cron's CAS print and TV's settled close disagreed. **Fix:** `update.py` and `update-us.py` now use `tv_change_abs × qty` as the primary dailyPnL source; yesterday's closingPrices is fallback-only for tickers TV omits.

**Bug 2 — phantom Apr 27 (Monday) snapshot.** Opening the app from a westward timezone (Paris/Asunción) on Sunday meant HKT had already rolled past midnight into Monday but the market hadn't opened. HK's snapshot useEffect had no "before market open" guard (the US file had one — they'd drifted), so it minted a Monday snapshot using Friday's stale priceCache. **Fix:** `index.html` line ~1283 now refuses to create a NEW today-snapshot when `isBeforeMarketOpen() || isPreMarket()`. Existing snapshots can still be updated for structural changes; only the *minting* path is gated.

**Bug 3 — Performance tab pre-market math.** The pre-market path gated `useTvDirect` on `!preMarketActive`, forcing it to recompute Friday's daily change as `(yesterday_snap.closingPrices − day_before_yesterday_snap.closingPrices) × qty`. Same CAS-vs-settlement drift propagated through. **Fix:** `index.html` line 3506 — removed `!preMarketActive` from the gate. The Performance tab now uses TV-direct math at all times of day, matching the US file's existing logic.

**Data patches applied to Firestore:**
- `patch-apr24.py` — Apr 24 dailyPnL 9,720 → +6,134, 2175.HK closingPrice 3.43 → 3.41 (TV settlement), phantom Apr 27 snapshot deleted, priceCache 2175.HK corrected to −1.73%.
- `patch-apr23-closes.py` — Apr 23 closingPrices for 14/15 tickers realigned to TV settlement values (= Apr 24 priceCache previousClose). Fixes pre-market Performance tab math which reads Apr 23 closes as the "day before yesterday" baseline. portfolioValue updated; dailyPnL preserved at the original −12,941 (the v2.12 immutability rule was *don't auto-recompute*, not *never patch*).
- `patch-april-dailypnl.py` / `patch-all-months-dailypnl.py` — 10 stored dailyPnL fields realigned across Jan/Feb/Mar/Apr so calendar `monthTotal` equals the P&L chart endpoint. Same root cause: closingPrices got patched retroactively over the year (Apr 13 incident series, the Apr 23 settlement patch tonight) and dailyPnL was never reconciled. After patch:
  - January (Jan 26-30 only, app launched mid-month): +14,745 HKD calendar / chart legitimately differs because there's no December baseline
  - February: +22,995 HKD ✓ both views agree
  - March: −99,006 HKD ✓
  - April: +37,607 HKD ✓

**Defense for the future — `verify-daily.py`.** New script runs as the final step of both GitHub Actions workflows. After `update.py` (or `update-us.py`) writes the day's snapshot, the verifier re-pulls TradingView and asserts:
  - per-ticker `closingPrice` within 0.02 in market currency of TV settlement
  - per-ticker `priceCache.changePercent` within 0.05 percentage points of TV
  - `dailyPnL` within 50 in market currency of `sum(TV change_abs × qty) + realized delta`

Any violation exits 1 — the Actions run goes red and the failure email lists the offending tickers. Catches the regression class behind Mar 5, Apr 24, and the 2175.HK CAS-vs-settlement gap without needing a separate scheduled agent or external credentials.

**Lessons:**
1. **The cron and the browser must compute `dailyPnL` the same way.** They had drifted: cron used yesterday-closingPrices delta; browser used `cached.change × qty`. Whenever those inputs disagree (CAS vs settlement, intraday vs close, manual patch propagation), the two views diverge and one side becomes "wrong."
2. **Stored `dailyPnL` is immutable for *display*, not *forever*.** When upstream inputs (positionsAtClose, closingPrices, realizedPnL) get retroactively patched, `dailyPnL` must be patched in the same operation — otherwise the calendar's monthly sum drifts away from the P&L chart endpoint silently.
3. **Browser-side timezone math is always wrong somewhere.** Every "phantom snapshot" / "stale today" / "HKT midnight" bug we've shipped traces back to using `Date()` arithmetic instead of `toLocaleString('Asia/Hong_Kong')`. The pre-market guard added today closes one more such hole; index-us.html had this guard already because the US side hit the same class of bug Feb 12 (v2.13).
4. **Self-checks belong inline with the operation that can break them.** A weekly external verifier wouldn't have caught this — the divergence persisted for weeks before manual eyeballing surfaced it. Wiring `verify-daily.py` into the workflow that *creates* the snapshot means any regression fails the same run that introduced it.

### Apr 14, 2026 — v2.21: Pre-market P&L fix for new-today positions + add position feedback

**Pre-market fix:** Positions bought today (entryDate = todayStr) were showing 0% and $0 in the Performance tab during pre-market hours. Root cause: the pre-market branch looked up `dayBeforeClosingPrices[ticker]` / `yesterdayClosingPrices[ticker]` first — but a position just bought has no entry in any previous snapshot, so the fallback was `p.currentPrice` vs `p.currentPrice` = 0%.

**Fix:** Added an `isNewToday` guard before the pre-market branch. When `preMarketActive && isNewToday`, use `cached.previousClose || p.entryPrice` as previousClose (same as open-market behaviour). This makes pre-market consistent: a new position always shows its change from the official previous close, regardless of whether the market is open or not.

**Add position feedback:** Button now turns green with a checkmark ("Ajouté !") for 1.5s after a position is successfully saved to Firestore.

**Data patches applied (Apr 13 snapshot):**
- `priceCache` backfilled for 113.HK (`price=6.17, previousClose=6.10`) and 3680.HK (`price=2.10, previousClose=2.20`) — both positions were missing from priceCache entirely, causing Performance tab to show 0% / $0
- `closingPrices` backfilled for 113.HK (6.17) and 3680.HK (2.10) in Apr 13 snapshot; 113.HK (6.10) and 3680.HK (2.20) in Apr 10 snapshot (for correct pre-market previousClose recalculation)
- 113.HK and 3680.HK added to Apr 13 `positionsAtClose` (both were added to the portfolio after the 16:30 HKT cron ran, so they were absent from the snapshot detail view)
- 1913.HK data corruption fixed: position had been added multiple times, accumulating to qty=6200. Correct state: qty=2300 (1000 pre-existing + 1300 added Apr 13), entry=43.597 HKD avg. `positionsAtClose` updated accordingly.
- `dailyPnL` corrected: -14,421 → **-17,329** (final correct value). Breakdown: base -14,821 + 113.HK +1,400 + 3680.HK -2,400 + 1913.HK extra 1300 shares -1,508 = -17,329

**HKT midnight entryDate bug (data patch):** 3680.HK was added to the portfolio after midnight UTC on April 13, so JavaScript stored `entryDate = "2026-04-14"`. On April 14, this made the app treat the position as `isNewToday = true`, blocking TradingView's direct `changePercent` and using `entryPrice` as `previousClose` instead — the Performance tab showed the same -4.55% as the day before rather than the live move. Fixed by patching `entryDate` to `"2026-04-13"` directly in Firestore (`patch-3680-entrydate.py`).

**Lessons learned (Apr 13-14 debugging session):**

1. **HKT midnight bug** — JavaScript's `new Date().toISOString()` returns UTC, which is 8 hours behind HKT. A position added at 11:30 PM on April 13 HKT has `entryDate = "2026-04-14"` in the app. Always verify the HKT date when a position's date looks one day off. If an `entryDate` is wrong by exactly +1 day, this is the cause.

2. **Positions added after 16:30 HKT cron are invisible to the snapshot** — The cron runs at 16:30 HKT, freezing `positionsAtClose` and `closingPrices`. Any position added after that time won't appear in the snapshot detail modal and won't contribute to `dailyPnL` in the stored snapshot. Fix: patch `positionsAtClose`, `closingPrices`, and `dailyPnL` manually via a Python script.

3. **Three P&L values can diverge on the same day** — The stored tile value (`snap.dailyPnL`), the recalculated value via `closingPrices`, and the movers table total can all differ if positions were patched after the cron. When they diverge, the movers table (live calculation) is most likely to be correct because it uses the current `positionsAtClose` data. The stored `dailyPnL` must be patched to match.

4. **priceCache ticker format** — The app stores priceCache under `"113.HK"` (without leading zero), but HKEX tickers officially have leading zeros (e.g., `"0113.HK"`). When patching priceCache manually, add BOTH `"113.HK"` and `"0113.HK"` to cover all lookup paths.

5. **Position averaging + multiple-add bug** — If a user taps "Ajouter" multiple times for the same position, the quantities accumulate in Firestore. The result is a qty and entryPrice that are both wrong. There is no UI guard. Fix: locate the position in Firestore via a patch script and set `quantity`, `entryPrice`, `addedTodayQty`, `qtyBeforeToday`, `addedTodayDate` to the correct values directly.

6. **macOS uses `python3`, not `python`** — All patch scripts must be invoked as `python3 patch-xxx.py`. The directory path also has a trailing space (`"App portfolio /"`) which requires escaping in shell: `cd ~/Library/Mobile\ Documents/.../App\ portfolio\ /`.

7. **HKT midnight bug persists the next day** — A position added after midnight UTC (= after ~8 AM HKT) gets `entryDate` of the next UTC calendar day. On that next day, `isNewToday = true`, which blocks TradingView's official `changePercent` and replaces `previousClose` with `entryPrice`. Symptom: the position shows the same % as the prior day's closing move rather than today's live move. Fix: patch `entryDate` to the correct HKT date in Firestore.

### Apr 14, 2026 — US Portfolio sync: 3 parity fixes + security hardening

**US: Double-add guard** — `addPosition` button now disabled during async save and shows green checkmark for 1.5s on success. Prevents position qty accumulation from impatient double-taps (same pattern as HK v2.21).

**US: ET midnight bug fix (Performance tab chart)** — `todayStr` in the monthly P&L chart was computed with `now.toISOString().split('T')[0]` (UTC). Replaced with `getMarketToday()` (ET via `America/New_York`). Prevents the chart from mapping today's live P&L to the wrong date after midnight UTC (8 PM ET).

**US: Pre-market P&L for new-today positions** — Added `preMarketActive` check (before 9:30 AM ET on a trading day) in Performance tab. When `preMarketActive && isNewToday`, previousClose uses `cached.previousClose || p.entryPrice` instead of just `p.entryPrice`. Prevents 0% display when TradingView's official previousClose is available before the open.

**Security — Firestore rules updated:**
- Viewer `allow read` now requires `email_verified == true` (prevents unverified-email ACL bypass)
- `viewerInvites` create now requires `ownerUid == request.auth.uid` (prevents invite flooding by authenticated users)
- `git add .` replaced with explicit file list in deployment docs (prevents accidental commit of `firebase-credentials.json`)
- `.gitignore` created: `firebase-credentials.json`, `*.pyc`, `.env`

---

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
