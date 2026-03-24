# ICT Trade Mission Control — Frontend Build Plan

## Overview

Build a Palantir/Bloomberg-grade trading intelligence dashboard from scratch using React + Vite + Tailwind. Deploy on Render as a static site alongside the existing API backend at `https://v5-algo.onrender.com`.

**Purpose**: Analytical intelligence for a manual execution team. Not a trading bot UI — a research & signal platform that helps traders find and execute profitable trades on BTCUSD, NAS100, US30, EURUSD, Gold, and Oil.

**Proof it works**: We made $6,122 profit on USOIL positions using insights from this system.

---

## Architecture

```
┌──────────────────────────────────────────────┐
│  Frontend (React + Vite)                      │
│  Deployed on: Render Static Site              │
│  Repo: ict-trade-mission-control              │
│  URL: https://ict-desk.onrender.com           │
├──────────────────────────────────────────────┤
│  Makes fetch() calls to ↓                     │
├──────────────────────────────────────────────┤
│  Backend API (FastAPI)                        │
│  Deployed on: Render Web Service              │
│  Repo: v5-algo                                │
│  URL: https://v5-algo.onrender.com/api        │
│  43 endpoints — prices, candles, analysis,    │
│  positions, news, signals, review, safety     │
├──────────────────────────────────────────────┤
│  Data Sources (all free)                      │
│  CoinGecko → BTCUSD                          │
│  Yahoo Finance → NAS100, US30, EURUSD,        │
│                  XAUUSD, USOIL                │
│  free-crypto-news → Sentiment, headlines      │
│  TradeLocker SDK → Candles, positions, prices  │
└──────────────────────────────────────────────┘
```

---

## Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Framework | React 18 + Vite | Fast builds, ESM-native, hot reload |
| Styling | Tailwind CSS | Utility-first, dark theme, dense layouts |
| Charts | Lightweight Charts (TradingView) | Professional candlestick charts, free |
| Data fetching | TanStack Query (React Query) | Polling, caching, stale-while-revalidate |
| Routing | React Router v6 | Standard, file-based-ish |
| Icons | Lucide React | Clean, consistent |
| State | Zustand | Minimal, no boilerplate |
| Deploy | Render Static Site | Same platform as backend |

---

## File Structure

```
ict-trade-desk/
├── index.html
├── package.json
├── vite.config.js
├── tailwind.config.js
├── postcss.config.js
├── render.yaml                      # Render static site config
├── .env                             # VITE_API_URL=https://v5-algo.onrender.com/api
├── .env.example
├── public/
│   └── favicon.ico
├── src/
│   ├── main.jsx                     # Entry point
│   ├── App.jsx                      # Router + layout
│   ├── index.css                    # Tailwind base + custom vars
│   │
│   ├── api/
│   │   ├── client.js                # Base fetch wrapper + error handling
│   │   ├── prices.js                # /prices, /prices/{symbol}
│   │   ├── tradelocker.js           # /tl/candles, /tl/positions, /tl/instruments
│   │   ├── analysis.js              # /analyze, /market-overview
│   │   ├── news.js                  # /news/sentiment, /news/latest, /news/bitcoin
│   │   ├── signals.js               # /signals, /approve-signal, /reject-signal
│   │   ├── review.js                # /review/daily, /review/weekly, /review/streak
│   │   ├── safety.js                # /safety/status, /safety/reset-breaker
│   │   ├── account.js               # /account-state, /broker-test, /health
│   │   └── scratchpad.js            # /scratchpad/sessions, /scratchpad/{id}
│   │
│   ├── hooks/
│   │   ├── usePolling.js            # Generic polling hook
│   │   ├── usePrices.js             # Live price data with 45s polling
│   │   ├── usePositions.js          # Open positions with 30s polling
│   │   ├── useAnalysis.js           # Analysis results
│   │   └── useSession.js            # Current trading session logic
│   │
│   ├── store/
│   │   └── appStore.js              # Zustand: theme, auto-scan, preferences
│   │
│   ├── components/
│   │   ├── layout/
│   │   │   ├── Shell.jsx            # Main layout: sidebar + topbar + content
│   │   │   ├── Sidebar.jsx          # Nav sidebar with icons + badges
│   │   │   ├── TopBar.jsx           # Account strip + connection status
│   │   │   └── PriceTicker.jsx      # Horizontal scrolling price bar
│   │   │
│   │   ├── shared/
│   │   │   ├── Card.jsx             # Dense card container
│   │   │   ├── Badge.jsx            # Status/sentiment badges
│   │   │   ├── Metric.jsx           # Single metric display (label + value)
│   │   │   ├── PriceDisplay.jsx     # Monospace price with delta
│   │   │   ├── ConfidenceMeter.jsx  # Visual confidence bar
│   │   │   ├── SessionDot.jsx       # Green/red/gray dot + label
│   │   │   ├── Spinner.jsx          # Loading indicator
│   │   │   ├── ErrorBanner.jsx      # "Backend unavailable" banner
│   │   │   └── TimeAgo.jsx          # Relative time display
│   │   │
│   │   ├── charts/
│   │   │   ├── CandlestickChart.jsx # TradingView Lightweight Charts wrapper
│   │   │   ├── PriceLineChart.jsx   # Simple line chart for BTC
│   │   │   ├── PnLBarChart.jsx      # Daily P&L bars (green/red)
│   │   │   └── RangeBar.jsx         # Horizontal range indicator
│   │   │
│   │   ├── desk/
│   │   │   ├── SymbolCard.jsx       # One symbol's price + momentum + bias
│   │   │   ├── SymbolGrid.jsx       # 6-card grid of all symbols
│   │   │   ├── SessionPanel.jsx     # Session status for all symbols
│   │   │   ├── CryptoOverview.jsx   # Total market cap, BTC dominance
│   │   │   ├── SentimentPanel.jsx   # News sentiment badge + headlines
│   │   │   └── AccountStrip.jsx     # Balance, equity, P&L footer
│   │   │
│   │   ├── positions/
│   │   │   ├── PositionsTable.jsx   # Live positions from TradeLocker
│   │   │   └── PositionRow.jsx      # Single position with P&L
│   │   │
│   │   ├── signals/
│   │   │   ├── SignalCard.jsx       # Signal idea with reasoning
│   │   │   ├── SignalList.jsx       # List of signal ideas
│   │   │   ├── ReasoningList.jsx    # Bullet list of reasons
│   │   │   └── SignalActions.jsx    # Take Trade / Pass / Flag buttons
│   │   │
│   │   ├── news/
│   │   │   ├── NewsFeed.jsx         # Article list
│   │   │   ├── NewsCard.jsx         # Single article
│   │   │   └── SentimentGauge.jsx   # -1 to +1 visual gauge
│   │   │
│   │   └── scratchpad/
│   │       ├── SessionList.jsx      # List of reasoning sessions
│   │       └── SessionTimeline.jsx  # Step-by-step reasoning display
│   │
│   └── pages/
│       ├── TradingDesk.jsx          # PAGE 1: Main dashboard (hero)
│       ├── Charts.jsx               # PAGE 2: Candlestick charts per symbol
│       ├── Scanner.jsx              # PAGE 3: Market analysis scanner
│       ├── Signals.jsx              # PAGE 4: Signal ideas queue
│       ├── News.jsx                 # PAGE 5: Sentiment + headlines
│       ├── Positions.jsx            # PAGE 6: Live positions + P&L
│       ├── DeepDive.jsx             # PAGE 7: Per-symbol deep analysis
│       ├── Scratchpad.jsx           # PAGE 8: Reasoning audit trail
│       ├── Journal.jsx              # PAGE 9: Trade journal
│       ├── DailyReview.jsx          # PAGE 10: Daily P&L + streak
│       ├── RiskConsole.jsx          # PAGE 11: Safety modules
│       └── Admin.jsx                # PAGE 12: System config
```

---

## API Client Layer

### `src/api/client.js` — Base

```javascript
const API_URL = import.meta.env.VITE_API_URL || 'https://v5-algo.onrender.com/api';

export async function get(path) {
  try {
    const res = await fetch(`${API_URL}${path}`);
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    const data = await res.json();
    return data.items || data;
  } catch (err) {
    console.error(`API GET ${path}:`, err);
    return null;
  }
}

export async function post(path, body = {}) {
  try {
    const res = await fetch(`${API_URL}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    return await res.json();
  } catch (err) {
    console.error(`API POST ${path}:`, err);
    return null;
  }
}
```

### Endpoint Modules

Each module wraps specific endpoints:

```javascript
// src/api/prices.js
import { get } from './client';
export const getAllPrices = () => get('/prices');
export const getSymbolDetail = (sym) => get(`/prices/${sym}`);

// src/api/tradelocker.js
import { get } from './client';
export const getCandles = (sym, res='1h', lb='5D') =>
  get(`/tl/candles/${sym}?resolution=${res}&lookback=${lb}`);
export const getPositions = () => get('/tl/positions');
export const getInstruments = () => get('/tl/instruments');
export const getLatestPrice = (sym) => get(`/tl/price/${sym}`);

// src/api/analysis.js
import { get, post } from './client';
export const getMarketOverview = () => get('/market-overview');
export const runAnalysis = () => post('/analyze');

// src/api/news.js
import { get } from './client';
export const getSentiment = () => get('/news/sentiment');
export const getLatestNews = (limit=20) => get(`/news/latest?limit=${limit}`);
export const getBitcoinNews = () => get('/news/bitcoin');

// src/api/signals.js
import { get, post } from './client';
export const getSignals = (limit=50) => get(`/signals?limit=${limit}`);
export const approveSignal = (id) => post('/approve-signal', {signal_id: id, approved_by: 'operator'});
export const rejectSignal = (id, reason='pass') => post('/reject-signal', {signal_id: id, rejected_by: 'operator', reason});
```

---

## Page Specifications

### PAGE 1: Trading Desk (hero page)

**Data**: `GET /market-overview` (polls every 45s)
**Also**: `GET /tl/positions` (polls every 30s)
**Also**: `POST /analyze` (on button click or auto every 2 min)

**Layout**:
```
┌─────────────────────────────────────────────────────┐
│ BTC $83,421 ▲2.1% │ NAS 18,245 │ OIL $98.17 ▲1.2% │  ← PriceTicker
├────────────┬──────────────┬─────────────────────────┤
│ SESSION    │ CRYPTO MKT   │ SENTIMENT               │  ← 3 intel cards
│ STATUS     │ Cap: $2.1T   │ 📰 BULLISH              │
│ ● BTC 24/7 │ BTC Dom 52% │ Score: ══●══            │
│ ● OIL NY   │ 24h: +1.2%  │ "Oil hits $98..."       │
├────────────┴──────────────┴─────────────────────────┤
│ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌────┐│
│ │ BTC  │ │ NAS  │ │ DJ30 │ │ EUR  │ │ GOLD │ │OIL ││  ← SymbolGrid
│ │$83.4K│ │18245 │ │42100 │ │1.084 │ │$2185 │ │$98 ││
│ │▲2.1% │ │▼0.3% │ │▲0.1% │ │▼0.2% │ │▲0.8% │ │▲1%││
│ └──────┘ └──────┘ └──────┘ └──────┘ └──────┘ └────┘│
├─────────────────────────────────────────────────────┤
│ LIVE POSITIONS                                       │
│ USOIL.R BUY 1.00  95.909→98.167  +$2,258  ▲        │  ← PositionsTable
│ USOIL.R BUY 0.50  93.620→98.167  +$2,273  ▲        │
│ USOIL.R BUY 0.50  93.648→98.167  +$1,591  ▲        │
│                            Total: +$6,122.95         │
├─────────────────────────────────────────────────────┤
│ SIGNAL IDEAS  [ANALYZE]  ○ Auto: OFF                 │
│ ┌─────────────────────────────────────────────┐      │
│ │ ⚡ HIGH  USOIL LONG  $98.17 ▲1.2%          │      │  ← SignalCards
│ │ ✅ Strong bullish momentum                  │      │
│ │ ✅ Above 50-day average                     │      │
│ │ ⚠️ Already have open position               │      │
│ │ Confidence: ████████░░ 5/7                  │      │
│ │ [TAKE TRADE] [PASS] [FLAG]                  │      │
│ └─────────────────────────────────────────────┘      │
├─────────────────────────────────────────────────────┤
│ Bal: $85,337 │ Eq: $91,460 │ P&L: +$6,122 │ Shadow │  ← AccountStrip
└─────────────────────────────────────────────────────┘
```

### PAGE 2: Charts

**Data**: `GET /tl/candles/{symbol}?resolution={res}&lookback={lb}`

- Symbol dropdown: BTCUSD, NAS100, US30, EURUSD, XAUUSD, USOIL
- Resolution tabs: 5m | 15m | 1h | 4h | 1D
- Candlestick chart using TradingView Lightweight Charts
- Below chart: latest candle data as OHLCV table
- For BTC: also show `GET /chart/btc?days=7` as overlay

### PAGE 3: Scanner

**Data**: `POST /analyze` (on button click)

- "Run Analysis" button + auto-run toggle (every 2 min)
- 6 panels (3×2 grid), one per symbol
- Each panel: price, momentum bar, bias badge, reasoning bullets, confidence
- Summary bar: "3 LONG │ 1 SHORT │ 2 WAIT"
- Scratchpad session link for audit trail

### PAGE 4: Signals

**Data**: `GET /signals?limit=50` (polls every 10s)

- Table: Time | Symbol | Bias | Confidence | Status | Actions
- Status badges: pending (yellow), taken (green), passed (gray), flagged (orange)
- Actions: [Take Trade] [Pass] [Flag for Review]
- Filter tabs: All | Pending | Taken | Passed
- Each row expandable to show reasoning

### PAGE 5: News & Sentiment

**Data**: `GET /news/latest?limit=20` + `GET /news/sentiment`

- Sentiment dashboard: large badge + score gauge
- News feed: cards with title, source, relative time
- Bitcoin tab: `GET /news/bitcoin`
- Poll every 2 minutes

### PAGE 6: Positions & P&L

**Data**: `GET /tl/positions` + `GET /review/daily` + `GET /review/streak`

- Live positions table (like TradeLocker screenshot)
- Today's P&L card
- Streak display: 🔥 X Win Streak
- Daily/weekly breakdown

### PAGE 7: Deep Dive

**Data**: `GET /prices/{symbol}` + `GET /tl/candles/{symbol}`

- Symbol selector
- All available data: price, 52w range, MAs, golden cross, volume
- Candle data table
- For BTC: market cap, dominance, supply chart

### PAGE 8-12: Scratchpad, Journal, Review, Risk, Admin

(Keep same data mappings as defined in previous prompts)

---

## Build Phases

### Phase 1: Scaffold + API Layer (Day 1)

```bash
# Create project
npm create vite@latest ict-trade-desk -- --template react
cd ict-trade-desk
npm install
npm install -D tailwindcss @tailwindcss/vite
npm install @tanstack/react-query react-router-dom zustand lucide-react
npm install lightweight-charts

# Setup
# - tailwind.config.js with dark theme colors
# - src/api/client.js
# - src/api/*.js (all endpoint modules)
# - src/hooks/usePolling.js
# - .env with VITE_API_URL
```

**Verify**: `fetch('https://v5-algo.onrender.com/api/prices')` returns data.

### Phase 2: Layout + Trading Desk (Day 1-2)

```
Build:
- Shell.jsx (sidebar + topbar + content area)
- Sidebar.jsx (12 nav items with icons)
- PriceTicker.jsx (horizontal price bar)
- TradingDesk.jsx with:
  - SessionPanel
  - CryptoOverview
  - SentimentPanel
  - SymbolGrid (6 SymbolCards)
  - AccountStrip
```

**Verify**: Dashboard shows live prices from all 6 symbols.

### Phase 3: Positions + Signals (Day 2)

```
Build:
- PositionsTable.jsx (live from /tl/positions)
- SignalCard.jsx + SignalList.jsx
- Scanner.jsx page
- Signals.jsx page
- ReasoningList.jsx
- ConfidenceMeter.jsx
```

**Verify**: USOIL positions show with real P&L. Analysis generates signal ideas.

### Phase 4: Charts (Day 2-3)

```
Build:
- CandlestickChart.jsx (TradingView Lightweight Charts)
- Charts.jsx page
  - Symbol selector
  - Resolution tabs
  - Candle rendering from /tl/candles/{symbol}
```

**Verify**: USOIL 1h candles render as candlestick chart.

### Phase 5: News + Deep Dive (Day 3)

```
Build:
- News.jsx page (sentiment + feed)
- DeepDive.jsx page (per-symbol analysis)
- SentimentGauge.jsx
- NewsFeed.jsx
```

### Phase 6: Journal + Review + Risk + Admin (Day 3-4)

```
Build remaining pages:
- Scratchpad.jsx
- Journal.jsx
- DailyReview.jsx (with P&L bars chart)
- RiskConsole.jsx
- Admin.jsx
```

### Phase 7: Polish + Deploy (Day 4)

```
- Responsive layout adjustments
- Loading states + error handling
- Render static site deployment
- render.yaml for frontend
- Final screenshot verification
```

---

## Render Deployment (Frontend)

### `render.yaml` for frontend repo:

```yaml
services:
  - type: web
    name: ict-trade-desk
    runtime: static
    buildCommand: npm install && npm run build
    staticPublishPath: dist
    envVars:
      - key: VITE_API_URL
        value: https://v5-algo.onrender.com/api
    routes:
      - type: rewrite
        source: /*
        destination: /index.html
```

### Or deploy manually:

1. Push frontend repo to GitHub
2. Render → New → Static Site
3. Connect GitHub repo
4. Build command: `npm install && npm run build`
5. Publish directory: `dist`
6. Add env var: `VITE_API_URL = https://v5-algo.onrender.com/api`

---

## Tailwind Config (dark trading terminal)

```javascript
// tailwind.config.js
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        desk: {
          bg: '#08080d',
          card: '#0f1117',
          border: '#1a1d2e',
          hover: '#1e2235',
        },
        profit: '#00e676',
        loss: '#ff1744',
        gold: '#ffd740',
        info: '#448aff',
        muted: '#8a8f98',
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'SF Mono', 'Fira Code', 'monospace'],
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
};
```

---

## Backend Endpoints — Complete Reference

### Market Data (free sources)
| Endpoint | Method | Returns |
|---|---|---|
| `/api/prices` | GET | All 6 symbols: price, change_24h_pct, volume |
| `/api/prices/{symbol}` | GET | Detail: 52w range, MAs, volume, market state |
| `/api/market-overview` | GET | Everything: prices + sessions + sentiment + crypto global |
| `/api/chart/btc?days=7` | GET | BTC chart data points |

### TradeLocker Data (broker)
| Endpoint | Method | Returns |
|---|---|---|
| `/api/tl/instruments` | GET | Available instruments + IDs |
| `/api/tl/candles/{symbol}?resolution=1h&lookback=5D` | GET | OHLCV candle data |
| `/api/tl/positions` | GET | Open positions with P&L |
| `/api/tl/price/{symbol}` | GET | Latest broker price |

### Analysis
| Endpoint | Method | Returns |
|---|---|---|
| `/api/analyze` | POST | Full scan: prices + candles + sentiment → signal ideas |
| `/api/news/sentiment` | GET | BTC sentiment + headlines |
| `/api/news/latest?limit=20` | GET | News articles |
| `/api/news/bitcoin` | GET | BTC-specific news |

### Signals & Review
| Endpoint | Method | Returns |
|---|---|---|
| `/api/signals?limit=50` | GET | Signal ideas list |
| `/api/approve-signal` | POST | Take trade (body: {signal_id, approved_by}) |
| `/api/reject-signal` | POST | Pass (body: {signal_id, rejected_by, reason}) |
| `/api/review/daily?date=` | GET | Daily P&L + breakdown |
| `/api/review/weekly` | GET | 7-day rollup |
| `/api/review/streak` | GET | Win/loss streak |
| `/api/review/trade-journal` | GET | Full trade reasoning chain |

### Safety & System
| Endpoint | Method | Returns |
|---|---|---|
| `/api/safety/status` | GET | Circuit breaker + cooldown state |
| `/api/safety/reset-breaker` | POST | Manual reset |
| `/api/health` | GET | System health |
| `/api/account-state` | GET | Account balance, equity, margin |
| `/api/config` | GET | Current config |
| `/api/set-mode` | POST | Change shadow/demo |
| `/api/kill-switch` | POST | Emergency stop |
| `/api/broker-test` | POST | Test TradeLocker connection |

### Scratchpad (reasoning logs)
| Endpoint | Method | Returns |
|---|---|---|
| `/api/scratchpad/sessions?count=20` | GET | Recent analysis sessions |
| `/api/scratchpad/{session_id}` | GET | Full reasoning trail |

---

## Claude Code Prompt

Paste this into Claude Code at the new repo root:

```
Read this entire BUILD_PLAN.md first.

Create a React + Vite + Tailwind frontend for the ICT Trade Mission Control.

Phase 1 — Scaffold:
1. Initialize with: npm create vite@latest . -- --template react
2. Install: tailwindcss @tailwindcss/vite @tanstack/react-query react-router-dom zustand lucide-react lightweight-charts
3. Configure Tailwind with the dark trading terminal theme from BUILD_PLAN.md
4. Create src/api/client.js with the base fetch wrapper
5. Create all API modules in src/api/
6. Create .env with VITE_API_URL=https://v5-algo.onrender.com/api
7. Verify the API is reachable

Phase 2 — Layout + Trading Desk:
1. Build Shell.jsx, Sidebar.jsx, TopBar.jsx, PriceTicker.jsx
2. Build TradingDesk.jsx as the main page per BUILD_PLAN.md
3. Build all desk components: SymbolCard, SymbolGrid, SessionPanel, etc.
4. Wire to /market-overview with 45s polling via React Query
5. The dashboard must show live prices for BTC, NAS100, US30, EUR, GOLD, OIL

Phase 3 — Positions + Signals:
1. Build PositionsTable.jsx reading from /tl/positions
2. Build SignalCard.jsx, SignalList.jsx, ReasoningList.jsx
3. Build Scanner.jsx and Signals.jsx pages
4. Wire POST /analyze for market scanning

Phase 4 — Charts:
1. Build CandlestickChart.jsx using lightweight-charts library
2. Build Charts.jsx page with symbol selector + resolution tabs
3. Fetch candles from /tl/candles/{symbol}

Phase 5 — Remaining pages:
News, DeepDive, Scratchpad, Journal, DailyReview, RiskConsole, Admin

Phase 6 — Deploy:
1. Create render.yaml for Render static site
2. Build command: npm install && npm run build
3. Publish: dist/
4. Env: VITE_API_URL=https://v5-algo.onrender.com/api

Rules:
- Dark theme only. Background #08080d. Cards #0f1117.
- Monospace font for ALL numbers and prices.
- Green #00e676 for profit. Red #ff1744 for loss.
- Dense layout — think Bloomberg Terminal, not consumer app.
- Every price right-aligned.
- Poll active data every 45 seconds.
- If API fails, show error banner, don't crash.
- Build in phases. Test each phase before moving on.
```

---

## Symbols Reference

| Our Name | Display | Type | TradeLocker | Yahoo | CoinGecko | Session |
|---|---|---|---|---|---|---|
| BTCUSD | BTC | Crypto | BTCUSD | — | bitcoin | 24/7 |
| NAS100 | NAS | Index | NAS100 | ^IXIC | — | NY Mon-Fri |
| US30 | DJ30 | Index | US30 | ^DJI | — | NY Mon-Fri |
| EURUSD | EUR | FX | EURUSD | EURUSD=X | — | London+NY |
| XAUUSD | GOLD | Commodity | XAUUSD | GC=F | — | London+NY |
| USOIL | OIL | Commodity | USOIL.R | CL=F | — | NY Mon-Fri |
