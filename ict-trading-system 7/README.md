# ICT Trading System — Claude Code Agent Architecture

A self-healing, agent-assisted CFD trading system that translates ICT-style discretionary
concepts into machine-readable rule engines, built with Claude Code agents.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Claude Agent Layer (E)                           │
│  Builder │ Structure Mapper │ Researcher │ Risk Gov │ Monitor │ JA │
│                    + Self-Improver (meta-agent)                     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Market Structure (A) → Strategy Decision (B) → Risk Engine (C)    │
│       market_state.json      trade_signal.json    approved_order   │
│                                                         │          │
│                                              Execution Engine (D)  │
│                                              TradeLocker / GatesFX │
└─────────────────────────────────────────────────────────────────────┘
```

## Quick Start

```bash
# 1. Clone and set up
cd ict-trading-system
pip install -e ".[dev]"

# 2. Configure broker credentials (never commit these)
export TRADELOCKER_EMAIL="your-email"
export TRADELOCKER_PASSWORD="your-password"
export TRADELOCKER_SERVER="your-server"
export TRADELOCKER_ACCOUNT_ID="your-account-id"

# 3. Run in shadow mode (signals only, no orders)
python -m core.pipeline --mode shadow

# 4. Run tests
pytest tests/ -v
```

## Build Phases

| Phase | What | Status |
|-------|------|--------|
| 1 | Broker + Safety (auth, prices, orders, kill switch) | 🔨 In Progress |
| 2 | Structure Labeling (sessions, liquidity, SMT, PO3) | ⏳ Planned |
| 3 | Shadow Mode (signal gen, no execution) | ⏳ Planned |
| 4 | Tiny Demo Execution (1-2 symbols, 0.25% risk) | ⏳ Planned |
| 5 | Controlled Multi-Strategy Demo | ⏳ Planned |
| 6 | Live-Readiness Gate | ⏳ Planned |

## V1 Constraints

- **Symbols:** NAS100, US30, EURUSD, BTCUSD
- **Session:** NY only
- **Max trades/day:** 3
- **Risk/trade:** 0.25%
- **Max drawdown:** 18% (hard lock)

## Agent Skills

Each agent has a dedicated skill in `skills/`:

| Agent | Skill | Purpose |
|-------|-------|---------|
| Builder | `skills/builder/` | Infrastructure, broker client, tests |
| Structure Mapper | `skills/structure-mapper/` | ICT concepts → numeric features |
| Strategy Researcher | `skills/strategy-researcher/` | Strategy design, testing, versioning |
| Risk Governor | `skills/risk-governor/` | Order gating, position sizing, drawdown |
| Session Monitor | `skills/session-monitor/` | Execution health, spread, latency |
| Journal Analyst | `skills/journal-analyst/` | Post-trade review, analytics |
| Self-Improver | `skills/self-improver/` | Measure → diagnose → propose → test → promote |

## Using with Claude Code

This project is designed to be used with Claude Code. The `CLAUDE.md` file provides
full context for Claude Code agents. Each skill in `skills/` contains a `SKILL.md`
that Claude Code reads when working on that domain.

```bash
# Open the project in Claude Code
claude-code .

# Claude Code will read CLAUDE.md and understand the full architecture.
# Ask it to work on any component:
#   "Build the SMT divergence detector"
#   "Write tests for the kill switch"
#   "Run the weekly improvement cycle"
#   "Review the latest daily journal"
```

## Self-Improvement Loop

```
MEASURE → DIAGNOSE → PROPOSE → SANDBOX TEST → HUMAN REVIEW → PROMOTE/REJECT
```

The Self-Improver agent measures all system components, finds weaknesses,
proposes changes, tests them in sandbox, and presents evidence for human approval.
No changes are applied without human sign-off.

## Project Structure

```
ict-trading-system/
├── CLAUDE.md                    # Master agent configuration
├── pyproject.toml               # Python project setup
├── config/                      # All configuration (YAML)
│   ├── broker.yaml              # TradeLocker connection
│   ├── risk.yaml                # Risk ladder (NON-NEGOTIABLE)
│   ├── strategy.yaml            # V1 strategy parameters
│   ├── structure.yaml           # Market structure detection thresholds
│   └── monitoring.yaml          # Session health monitoring
├── schemas/                     # JSON schemas for inter-engine data
│   ├── market_state.json
│   ├── trade_signal.json
│   ├── approved_order.json
│   └── trade_result.json
├── core/                        # Engine implementations
│   ├── models.py                # Shared Pydantic models
│   ├── pipeline.py              # Main orchestrator
│   ├── execution/               # Engine D: Broker communication
│   │   └── client.py            # TradeLocker API client
│   ├── market_structure/        # Engine A: Feature extraction
│   ├── strategy/                # Engine B: Signal generation
│   ├── risk/                    # Engine C: Order gating
│   │   └── engine.py            # Risk engine
│   └── agents/                  # Engine E: Claude agent utilities
├── skills/                      # Claude Code agent skills
│   ├── builder/SKILL.md
│   ├── structure-mapper/SKILL.md
│   ├── strategy-researcher/SKILL.md
│   ├── risk-governor/SKILL.md
│   ├── session-monitor/SKILL.md
│   ├── journal-analyst/SKILL.md
│   └── self-improver/SKILL.md
├── scripts/                     # Utility scripts
│   ├── gather_improvement_data.py
│   └── diagnose.py
├── tests/                       # Test suite
│   └── test_risk_engine.py
├── data/                        # Runtime data (gitignored)
│   ├── candles/
│   ├── signals/
│   ├── trades/
│   └── reviews/
└── logs/                        # Structured logs (gitignored)
```
