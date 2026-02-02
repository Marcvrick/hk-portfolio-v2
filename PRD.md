# Portfolio Tracker v2 - Product Requirements Document

## Overview

Single-page React applications for tracking stock portfolio performance with Firebase authentication and cloud sync.

**Stack:** React 18, Tailwind CSS, Recharts, Firebase (Auth + Firestore)
**Target Markets:** HKEX (Hong Kong) and NYSE/NASDAQ (US)
**Language:** French UI

### Portfolio Versions

| Feature | HK (`index.html`) | US (`index-us.html`) |
|---------|-------------------|----------------------|
| Ticker format | `XXXX.HK` | `AAPL`, `MSFT` |
| Currency | HKD | USD |
| Firebase collection | `portfolios/{userId}` | `us-portfolios/{userId}` |
| Market holidays | HKEX (14 days/year) | NYSE (10 days/year) |
| All other features | ✅ Same | ✅ Same |

---

## Data Models

### Position
```javascript
{
  id: number,           // Unix timestamp at creation
  ticker: "XXXX.HK",    // HKEX ticker format
  name: string,         // Company name
  quantity: number,     // Number of shares
  entryPrice: number,   // Average entry price (HKD)
  currentPrice: number, // Latest price (HKD)
  entryDate: "YYYY-MM-DD"
}
```

### Closed Trade
```javascript
{
  id: number,
  ticker: "XXXX.HK",
  name: string,
  quantity: number,
  entryPrice: number,
  exitPrice: number,
  entryDate: "YYYY-MM-DD",
  exitDate: "YYYY-MM-DD",
  totalFees?: number    // Optional: calculated fees at close
}
```

### Transaction
```javascript
{
  id: number,
  type: "deposit" | "withdrawal" | "dividend",
  amount: number,       // HKD
  date: "YYYY-MM-DD",
  notes: string,
  linkedTicker?: string // For dividends
}
```

### Snapshot (Daily Portfolio State)
```javascript
{
  date: "YYYY-MM-DD",
  capitalEngaged: number,    // Cost basis of open positions
  portfolioValue: number,    // Market value
  unrealizedPnL: number,     // portfolioValue - capitalEngaged
  realizedPnL: number,       // Sum of closed trade P&L
  totalDividends: number,
  positionCount: number,
  closingPrices: {           // Added v2.6 - for accurate daily % change
    "XXXX.HK": number        // Closing price per ticker
  }
}
```
- Snapshots auto-save daily on weekdays only (market closed weekends)
- Used for P&L calendar and equity curve calculations
- `closingPrices` stores actual closing prices for next day's % change calculation (more reliable than Yahoo's previousClose)

### Wishlist Item
```javascript
{
  id: number,
  ticker: "XXXX.HK",
  name: string,
  targetPrice: number,  // Alert when price <= target
  notes: string,
  dateAdded: "YYYY-MM-DD"
}
```

### Price Cache
```javascript
{
  "XXXX.HK": {
    success: boolean,
    price: number,
    previousClose: number,
    previousCloseOverride?: number,  // Manual override for previousClose (v2.6+)
    change: number,
    changePercent: number,
    currency: "HKD",
    lastUpdated: "ISO timestamp"
  }
}
```

---

## Features by Tab

### 1. Positions (Portfolio)
- Add new positions (auto-merges if ticker exists with weighted average price)
- Edit entry price, current price, entry date inline
- Close positions (full or partial) with fee calculation
- Visual alerts:
  - **Warning (⚠️)**: P&L between -8% and -10%
  - **Danger (🚨)**: P&L <= -10%
- Holding period badges (color-coded by days held)
- Auto-fetch Yahoo prices for new positions

### 2. Performance
- Daily movers table with % change from previous close
- Today's P&L summary (gainers/losers count)
- Top 3 gainers/losers badges
- **P&L Calendar**: Monthly heatmap of daily gains/losses
- **Equity Curve**: Total P&L over time chart

### 3. Completed Trades (History)
- All closed positions with net P&L (after fees)
- Holding duration stats
- Bucket analysis (performance by holding period)

### 4. Wishlist
- Track stocks with target prices
- Alert popup on login when price target reached
- Dismissable alerts

### 5. Transactions (History Tab)
- Deposits, withdrawals, dividends
- Capital flow tracking

### 6. History Tab (Analytics)
- Equity curve chart
- Weekly/Monthly performance tables
- Win rate statistics

### 7. Settings
- CORS proxy selection (for Yahoo Finance API)
- Dark mode toggle
- Export/Import JSON data
- Portfolio sharing (allow other emails to view)
- View friend's portfolio (read-only)

---

## Business Rules

### Trading Fees (HKEX)
Calculated per trade (buy or sell):
```javascript
brokerage = max(amount * 0.25%, HKD 100)
depositCharge = min(max(lots * 5, 30), 200)  // Buy only
stampDuty = ceil(amount * 0.1%)
sfcLevy = amount * 0.0027%
afrcLevy = amount * 0.00015%
hkexFee = amount * 0.00565%
settlementFee = min(max(amount * 0.002%, 2), 100)
```

### Alert Thresholds
| Condition | Visual |
|-----------|--------|
| P&L <= -8% and > -10% | ⚠️ Orange row + icon |
| P&L <= -10% | 🚨 Red row + animated icon |

### Holding Period Colors
| Days | Color |
|------|-------|
| 0-30 | Lime/Green |
| 31-60 | Yellow |
| 61-120 | Orange |
| 120+ | Red |

### Market Closed Days (Weekends + Holidays)
- Snapshots not saved on market closed days (weekends and holidays)
- Performance tab shows last trading day's % change on closed days
- Calendar greys out market closed days
- Holidays are hardcoded for 2025-2027 (update yearly)

**HKEX Holidays 2026 (14 days):**
Jan 1, Feb 17-19 (LNY), Apr 3/6/7 (Easter/Ching Ming), May 1/25, Jun 19, Jul 1, Oct 1/19, Dec 25

**NYSE Holidays 2026 (10 days):**
Jan 1 (New Year), Jan 19 (MLK), Feb 16 (President's), Apr 3 (Good Friday), May 25 (Memorial), Jun 19 (Juneteenth), Jul 3 (Independence), Sep 7 (Labor), Nov 26 (Thanksgiving), Dec 25 (Christmas)

### Position Adding with Past Date
When a position is added with an entry date before today:
- Historical prices are fetched from Yahoo (range based on date difference)
- All snapshots from entry date onwards are recalculated to include the position

### TWR Calculation (Time-Weighted Return)
Accounts for cash flows between periods:
```javascript
periodReturn = currentValue / (previousValue + capitalChange)
TWR = product(all periodReturns) - 1
```

---

## External APIs

### Yahoo Finance
**Endpoint:** `https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=5d`

Requires CORS proxy. Available proxies:
- `https://api.allorigins.win/raw?url=`
- `https://corsproxy.io/?`
- `https://api.codetabs.com/v1/proxy?quest=`

**Data extracted:**
- `meta.regularMarketPrice` → current price
- `indicators.quote[0].close[-2]` → previous close
- `meta.currency` → currency (fallback to HKD)

---

## Known Issues / Recent Fixes

### Fixed (2026-02-02)
1. **Accurate daily % change**: Performance tab now uses yesterday's stored closing prices (from snapshot) instead of Yahoo's unreliable `meta.previousClose`. Yahoo's previousClose was returning data 2+ days old, causing incorrect % change calculations.

2. **Manual previousClose editing**: For positions added after snapshot creation (missing closingPrices), users can now manually edit the previousClose value directly in the Performance tab. Click on the Prev Close cell to edit.

### Fixed (2025-02-01)
1. **Weekend % change for new positions**: Positions added on weekends now show the last trading day's market change instead of 0% (was using entry price as previousClose)

2. **Historical snapshot recalculation**: When adding a position with a past entry date, snapshots are now automatically updated to include the position's value

### Known Limitations
- closingPrices only stored from Feb 2026 onwards (older snapshots use Yahoo fallback)
- Snapshots not created for dates before app installation
- Friend portfolio viewing is read-only (no price refresh)

---

## Future Roadmap Ideas
- [ ] Recalculate all snapshots button (for retroactive position adds)
- [ ] Export to Excel/CSV
- [ ] Position notes/tags
- [ ] Sector allocation pie chart
- [ ] Dividend tracking with yield calculation
- [ ] Multi-currency support (USD, CNY)
- [ ] Mobile PWA optimization
- [ ] Price alerts (push notifications)

---

## File Structure
```
/hk-portfolio-v2-firebase/
├── index.html          # Main app (single HTML with embedded React)
├── index-us.html       # US market version
├── index-dev.html      # Development version
├── README.md           # Setup/deployment instructions
├── PRD.md              # This file
└── update.py           # Utility script
```

---

## Firebase Structure
```
Firestore:
└── portfolios/
    └── {userId}/
        ├── positions: []
        ├── closedTrades: []
        ├── transactions: []
        ├── priceCache: {}
        ├── snapshots: []
        ├── settings: {}
        ├── wishlist: []
        ├── wishlistAlertsDismissed: []
        ├── allowedViewers: []      # Emails who can view this portfolio
        └── ownerEmail: string      # For friend lookup
```
