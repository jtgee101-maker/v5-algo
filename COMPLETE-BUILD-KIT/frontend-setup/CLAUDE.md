# CLAUDE.md — ICT Trade Mission Control

You are building a Palantir/Public.com-level trading intelligence terminal.
This is a React + Vite + Tailwind frontend connecting to a live FastAPI backend.

## Context

The team made $23K profit on USOIL trades using a Displacement Rebalance Model (DRM).
This system encodes that edge into automated detection + visualization.
The team executes trades MANUALLY — the system provides intelligence, not automation.

## Live Backend

```
API: https://v5-algo.onrender.com/api
Docs: https://v5-algo.onrender.com/docs
46 endpoints — all live, CORS enabled
```

## Symbols

| Symbol | Display | Type | Session |
|--------|---------|------|---------|
| BTCUSD | BTC | Crypto | 24/7 |
| NAS100 | NAS | Index | NY Mon-Fri |
| US30 | DJ30 | Index | NY Mon-Fri |
| EURUSD | EUR | FX | London+NY |
| XAUUSD | GOLD | Commodity | London+NY |
| USOIL | OIL | Commodity | NY Mon-Fri |

## Design System — Bloomberg/Palantir Dark Terminal

```
Background: #08080d
Card: #0f1117
Border: #1a1d2e
Hover: #1e2235
Green (profit/bull): #00e676
Red (loss/bear): #ff1744
Gold (high conf): #ffd740
Blue (info): #448aff
Muted: #8a8f98
Text primary: #e8eaed

Font numbers: 'JetBrains Mono', 'SF Mono', monospace
Font text: 'Inter', system-ui, sans-serif

Rules:
- Dark theme ONLY
- Monospace for ALL numbers, prices, percentages
- Green positive, red negative, EVERYWHERE
- Dense layout — minimal padding, 1px borders, no shadows
- Cards: bg #0f1117, border 1px solid #1a1d2e, border-radius 4px
- No rounded corners > 4px
- Right-align all numbers in tables
```

## Tech Stack

- React 18 + Vite (already scaffolded)
- Tailwind CSS via @tailwindcss/vite
- TanStack React Query (polling, caching)
- React Router v6
- Zustand (global state)
- Lucide React (icons)
- lightweight-charts (TradingView candlestick charts)

## API Endpoints (46 total)

### Prices (free sources — always work)
```
GET /prices                          → all 6 symbols
GET /prices/{symbol}                 → detail: 52w, MAs, volume
GET /market-overview                 → everything in one call
GET /chart/btc?days=7                → BTC chart data
```

### TradeLocker (broker data)
```
GET /tl/instruments                  → available instruments
GET /tl/candles/{sym}?resolution=1h&lookback=5D → OHLCV candles
GET /tl/positions                    → open positions with P&L
GET /tl/price/{sym}                  → latest broker price
```

### DRM — Displacement Rebalance Model (the $23K edge)
```
GET /drm/{sym}?resolution=1h&lookback=5D → FVGs, displacements, signals
POST /drm/scan                       → DRM across ALL 6 symbols
GET /probability?current=X&target=Y&atr=Z&days=N → barrier-touch probability
```

### Analysis + Signals
```
POST /analyze                        → full multi-source analysis
GET /signals?limit=50                → signal queue
POST /approve-signal                 → body: {signal_id, approved_by}
POST /reject-signal                  → body: {signal_id, rejected_by, reason}
```

### News + Sentiment
```
GET /news/sentiment                  → BTC sentiment + headlines
GET /news/latest?limit=20            → news articles
GET /news/bitcoin                    → BTC-specific news
```

### Review + Journal
```
GET /review/daily?date=              → daily P&L + breakdown
GET /review/weekly                   → 7-day rollup
GET /review/streak                   → win/loss streak
GET /review/trade-journal            → full reasoning per trade
POST /review/auto-journal/{id}       → generate journal entry
```

### Safety
```
GET /safety/status                   → circuit breaker + cooldown
POST /safety/reset-breaker           → manual reset
```

### System
```
GET /health                          → system health
GET /account-state                   → balance, equity, margin
POST /broker-test                    → test TradeLocker connection
GET /config                          → current config
POST /set-mode                       → shadow/demo
POST /kill-switch                    → emergency stop
GET /scratchpad/sessions             → reasoning session list
GET /scratchpad/{id}                 → full reasoning trail
```

## File Structure

```
src/
├── main.jsx
├── App.jsx
├── index.css                        (Tailwind + custom vars)
├── api/
│   ├── client.js                    (fetch wrapper)
│   ├── prices.js
│   ├── tradelocker.js
│   ├── drm.js
│   ├── analysis.js
│   ├── news.js
│   ├── signals.js
│   ├── review.js
│   ├── safety.js
│   ├── account.js
│   └── scratchpad.js
├── hooks/
│   ├── usePolling.js
│   ├── usePrices.js
│   └── usePositions.js
├── store/
│   └── appStore.js                  (Zustand)
├── components/
│   ├── layout/
│   │   ├── Shell.jsx
│   │   ├── Sidebar.jsx
│   │   ├── TopBar.jsx
│   │   └── PriceTicker.jsx
│   ├── shared/
│   │   ├── Card.jsx
│   │   ├── Badge.jsx
│   │   ├── PriceDisplay.jsx
│   │   ├── ConfidenceMeter.jsx
│   │   └── Spinner.jsx
│   ├── charts/
│   │   ├── CandlestickChart.jsx     (lightweight-charts wrapper)
│   │   └── RangeBar.jsx
│   ├── desk/
│   │   ├── SymbolCard.jsx
│   │   ├── SymbolGrid.jsx
│   │   ├── SessionPanel.jsx
│   │   ├── SentimentPanel.jsx
│   │   └── AccountStrip.jsx
│   ├── drm/
│   │   ├── DRMSignalCard.jsx        (FVG + entry zone + probability)
│   │   ├── FVGList.jsx
│   │   └── ProbabilityGauge.jsx
│   ├── positions/
│   │   └── PositionsTable.jsx
│   └── signals/
│       ├── SignalCard.jsx
│       └── ReasoningList.jsx
└── pages/
    ├── TradingDesk.jsx              (hero dashboard)
    ├── DRMAnalysis.jsx              (your edge — FVG detection)
    ├── Charts.jsx                   (candlestick charts)
    ├── Scanner.jsx                  (market analysis)
    ├── Signals.jsx                  (signal ideas)
    ├── News.jsx                     (sentiment + headlines)
    ├── Positions.jsx                (live P&L)
    ├── DeepDive.jsx                 (per-symbol detail)
    ├── Scratchpad.jsx               (reasoning trail)
    ├── Journal.jsx                  (trade journal)
    ├── DailyReview.jsx              (daily P&L + streak)
    ├── RiskConsole.jsx              (safety modules)
    └── Admin.jsx                    (system config)
```

## Build Phases — Execute Sequentially

### PHASE 1: API Layer + Tailwind Config

Create all files in src/api/ with fetch wrappers.
Create src/index.css with Tailwind directives and custom CSS vars.
Create src/hooks/usePolling.js using React Query.
Verify: fetch('https://v5-algo.onrender.com/api/prices') returns data.

### PHASE 2: Layout Shell

Build Shell.jsx, Sidebar.jsx, TopBar.jsx, PriceTicker.jsx.
Set up React Router with all 13 page routes.
Sidebar: 13 nav items with Lucide icons.
PriceTicker: horizontal bar showing all 6 symbols, polls every 45s.
Verify: app loads with working nav and price ticker.

### PHASE 3: Trading Desk (HERO PAGE — most important)

Build TradingDesk.jsx with these sections:
1. Session Status (6 symbols, green/gray dots)
2. Crypto Overview (market cap, BTC dominance)
3. News Sentiment (BULLISH/BEARISH badge + score gauge)
4. Symbol Grid (6 cards: price, change, momentum, bias)
5. Live Positions table (from /tl/positions)
6. DRM Signals panel (from /drm/scan)
7. Account Strip (balance, equity, P&L)

Data: GET /market-overview (poll 45s) + GET /tl/positions (poll 30s)
DRM: POST /drm/scan (on button click or auto 2min)

### PHASE 4: DRM Analysis Page (YOUR EDGE)

Build DRMAnalysis.jsx — the page that finds $23K trades:
- Symbol selector
- Fetch GET /drm/{symbol}?resolution=1h&lookback=5D
- Show: displacement events (violent candles)
- Show: fair value gaps (imbalance zones) with fill percentage
- Show: DRM signals with entry zone, targets, stop, R:R
- Show: barrier-touch probability gauges
- Show: reasoning bullets (✅ checkmarks)
- Probability calculator widget: input current/target/ATR/days

Build components: DRMSignalCard, FVGList, ProbabilityGauge.

### PHASE 5: Candlestick Charts

Build Charts.jsx with TradingView Lightweight Charts.
Symbol dropdown + resolution tabs (5m/15m/1h/4h/1D).
Fetch GET /tl/candles/{symbol}.
Map candle data: {t,o,h,l,c} → lightweight-charts format.
Dark theme: bg #08080d, up #00e676, down #ff1744.
Below chart: OHLCV data table.

### PHASE 6: Scanner + Signals

Build Scanner.jsx: POST /analyze button + auto toggle.
6 panels, one per symbol, showing analysis results.
Build Signals.jsx: GET /signals with Take Trade/Pass/Flag buttons.

### PHASE 7: News + Deep Dive + Positions

Build News.jsx: sentiment dashboard + article feed.
Build DeepDive.jsx: per-symbol detail with all data.
Build Positions.jsx: live positions with today's P&L.

### PHASE 8: Journal + Review + Scratchpad + Risk + Admin

Build remaining pages. Wire all endpoints.
Add loading spinners and error handling.

### PHASE 9: Final Polish + Deploy

Test all pages. Fix console errors.
Run: npm run build
Create render.yaml (already in root).
Push to GitHub. Deploy on Render as static site.

## Rules

- NEVER create files outside src/ except config files in root
- ALWAYS use the dark theme colors specified above
- ALWAYS use monospace font for numbers
- Test each phase by running `npm run dev` before moving to next
- If an API endpoint returns null or errors, show an error state — don't crash
- Poll active data every 45 seconds using React Query refetchInterval
- Every price must be green (positive) or red (negative)
- The DRM page is the MOST IMPORTANT page after Trading Desk — it's the edge
- Use Ruflo sub-agents for parallel work when building multiple pages
