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

**Backend:**
- Firebase Firestore (database)
- GitHub Actions (daily cron)
- Python + firebase-admin (price updates)

---

## Files

| File | Description |
|------|-------------|
| `index.html` | HK Portfolio - Production app (dark mode default) |
| `index-us.html` | US Portfolio - Same layout, USD currency |
| `index-dev.html` | Development version |
| `update.py` | Cron script for Yahoo Finance prices |
| `.github/workflows/daily-update.yml` | GitHub Actions workflow |

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
      └── priceCache: {}
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

### 5. Cron Setup (update.py)

1. Firebase Console > Project Settings > Service Accounts
2. Generate new private key
3. Add as GitHub secret: `FIREBASE_CREDENTIALS_JSON`

---

## Deployment

```bash
# Push changes to deploy via GitHub Pages
git add .
git commit -m "Update"
git push
```

GitHub Pages auto-deploys from `main` branch.

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
# Test cron locally
GOOGLE_APPLICATION_CREDENTIALS=firebase-credentials.json python update.py

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
3. Commit et push

### Key Business Rules (Quick Reference)
| Rule | Value |
|------|-------|
| Warning threshold | P&L <= -8% |
| Danger threshold | P&L <= -10% |
| Weekend snapshots | Disabled |
| Fee calculation | See PRD.md for 7 components |
| Ticker format | XXXX.HK |

### Common Maintenance Tasks
- **Add new fee component**: Update `calcTradingFees()` in index.html + PRD.md
- **Change alert thresholds**: Search `isWarning` and `isDanger` in index.html
- **Fix Yahoo API issues**: Check CORS proxy list in Settings section
- **Debug snapshots**: Check browser console for snapshot logs

---

## Changelog

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
