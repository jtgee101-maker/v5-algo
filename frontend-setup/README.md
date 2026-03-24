# ICT Trade Mission Control — Setup Guide

## What This Is

A Palantir-grade trading intelligence terminal built with React + Claude Code + Ruflo.
Connected to a live FastAPI backend on Render with 46 endpoints.
Encodes your $23K USOIL Displacement Rebalance Model edge.

## Prerequisites

- MacBook Pro with macOS 14+
- Node.js 18+ (`brew install node`)
- Git (`brew install git`)
- Claude Code subscription (Max or Pro)

## Setup (5 minutes)

```bash
# 1. Download and run the setup script
chmod +x setup.sh
./setup.sh

# 2. Navigate to the project
cd ~/ict-trade-desk

# 3. Start Claude Code
claude

# 4. Tell Claude:
#    "Read CLAUDE.md and execute Phase 1"
```

## What setup.sh Does

1. Checks Node.js, Git, Claude Code are installed
2. Installs Ruflo (multi-agent orchestration)
3. Creates `~/ict-trade-desk` project directory
4. Scaffolds React + Vite
5. Installs all dependencies
6. Creates CLAUDE.md (master build instructions)
7. Creates .env with backend URL
8. Initializes Git

## Building with Claude Code

After setup, open Claude Code in the project directory and work through 9 phases:

| Phase | What | Time |
|-------|------|------|
| 1 | API layer + Tailwind config | 30 min |
| 2 | Layout shell + navigation | 1 hour |
| 3 | Trading Desk (hero page) | 2 hours |
| 4 | DRM Analysis (your edge) | 2 hours |
| 5 | Candlestick charts | 1 hour |
| 6 | Scanner + Signals | 1.5 hours |
| 7 | News + Deep Dive + Positions | 1.5 hours |
| 8 | Journal + Review + Risk + Admin | 1.5 hours |
| 9 | Polish + Deploy | 30 min |

## Building with Ruflo (multi-agent parallel)

For faster builds, use Ruflo's agent swarm:

```bash
# Initialize Ruflo swarm
npx ruflo@latest init --wizard

# Run the workflow
npx ruflo automation run-workflow ruflo-workflow.yaml --claude
```

This spawns parallel agents that build multiple pages simultaneously.

## Deploying

```bash
# Build
npm run build

# Test locally
npm run preview

# Deploy on Render
# 1. Push to GitHub
# 2. Render → New → Static Site
# 3. Build command: npm install && npm run build
# 4. Publish: dist/
# 5. Env var: VITE_API_URL = https://v5-algo.onrender.com/api
```

## Backend Push (do this FIRST)

Before building the frontend, push the 13 backend files from `v5-drm-complete.zip` to your `v5-algo` GitHub repo:

```
ict-trading-system 7/backend/app.py
ict-trading-system 7/backend/api/routers.py
ict-trading-system 7/backend/services/daily_review_service.py
ict-trading-system 7/backend/settings.py
ict-trading-system 7/core/execution/client.py
ict-trading-system 7/core/safety.py
ict-trading-system 7/core/intelligence.py
ict-trading-system 7/core/market_data.py
ict-trading-system 7/core/tradelocker_data.py
ict-trading-system 7/core/strategy/drm.py   ← NEW: Your $23K edge
ict-trading-system 7/config/broker.yaml
ict-trading-system 7/requirements.txt
```

After Render deploys, verify: `curl https://v5-algo.onrender.com/api/drm/USOIL`

## Architecture

```
MacBook Pro
├── Claude Code (Opus 4.6)
├── Ruflo (multi-agent orchestration)
└── ~/ict-trade-desk (React frontend)
    ↓ fetch()
Render (cloud)
├── ict-trade-desk (static site)
└── v5-algo (FastAPI + 46 endpoints)
    ├── CoinGecko (free prices)
    ├── Yahoo Finance (free prices)
    ├── free-crypto-news (free sentiment)
    └── TradeLocker SDK (candles + positions)
```
