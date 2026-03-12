# ICT Trading System — Claude Code Agent Configuration

## Project Identity

This is a **self-healing, agent-assisted CFD trading system** that uses ICT-style concepts
(Power of 3, SMT divergence, liquidity sweeps, psychological levels, precision entries)
translated into machine-readable rule engines. It targets the NY session on TradeLocker
via GatesFX demo, with strict drawdown control and progressive learning.

**The edge comes from:** good structure labeling, strict risk, regime filtering, execution
discipline, and using Claude agents to improve the system faster than a human would.

**The edge does NOT come from:** Claude predicting markets, vibes-based chart reading,
or unconstrained LLM adaptation.

Core mantra: **"Discretion translated into rules."**

---

## Architecture Overview

Five cooperating engines, not one monolith:

| Engine | Responsibility | Output |
|---|---|---|
| **A. Market Structure** | Labels sessions, liquidity, sweeps, SMT, PO3, psych levels | `market_state.json` |
| **B. Strategy Decision** | Generates long/short/no-trade with confidence + levels | `trade_signal.json` |
| **C. Risk** | Deterministic gating: size, exposure, drawdown throttle | `approved_order.json` or rejection |
| **D. Execution** | TradeLocker API: auth, prices, orders, reconciliation | Broker state |
| **E. Claude Agent Layer** | Code gen, experiment design, log triage, tuning, review | System improvements |

---

## Build Phase Gate (CURRENT PHASE: 2)

Progress through phases strictly. Never skip ahead.

- **Phase 1** — Broker + Safety ✅ COMPLETE: Auth, account state, prices, candles, positions, orders, session status, instrument specs, dry-run validation, kill switch
- **Phase 2** — Structure Labeling 🔨 IN PROGRESS: Session ranges, prior H/L maps, swing detection, equal H/L, psych levels, SMT, sweep/displacement, PO3 candidates
- **Phase 3** — Shadow Mode: Signal generation only, no order placement, confidence/regime/false-signal logging
- **Phase 4** — Tiny Demo Execution: 1–2 symbols, 0.25% risk, 1 strategy, manual review of every trade
- **Phase 5** — Controlled Multi-Strategy Demo: Indices + FX + crypto CFD, dynamic throttling, performance attribution
- **Phase 6** — Live-Readiness Gate: Sample size, drawdown tolerance, execution integrity, edge survives costs, self-healing events behaved

**DO NOT advance to the next phase until the current phase passes its gate criteria.**

---

## Current Active Task

Active phase: **Phase 3 → 4 transition (Shadow validation → Demo validation)**
Current target: **End-to-end validation: pipeline↔DB↔API↔Base44**

Next steps:
1. Run shadow mode and validate signals persist to DB
2. Wire Base44 to live API endpoints
3. Validate approve/reject flow end-to-end
4. Run reconciliation against demo broker
5. Accumulate 100+ shadow signals before enabling demo execution

Allowed files:
- `core/monitoring/*` (new)
- `tests/*` (expanding coverage)
- `backend/*` (bug fixes, hardening)
- Base44 integration specs

Forbidden:
- Live execution changes (keep dry_run=True)
- Risk parameter changes without human approval
- Removing any safety checks or auth enforcement
- Disabling manual approval by default

---

## V1 Constraints (Hard Rules)

| Parameter | Value |
|---|---|
| Symbols | NAS100, US30, EURUSD, BTCUSD |
| Session | NY only |
| Entry TF | 1m / 5m |
| Bias TF | 15m / 1h |
| Max trades/day | 3 |
| Risk/trade | 0.25% |
| Max daily loss | 1.5% |
| Max weekly loss | 4% |
| Account max DD hard stop | 18% |
| News filter | No trading during major scheduled news until filtered logic exists |

---

## Risk Ladder (Non-Negotiable)

### Base Risk
- Per trade: 0.25% – 0.50%
- Max simultaneous: 1.25% – 1.75%
- Max correlated basket: 0.75% – 1.0%

### Adaptive Drawdown Throttles
- **5% DD** → cut new trade risk by 25%
- **8% DD** → cut by 50%, reduce max concurrent positions
- **10% DD** → strategy review mode, only A-tier setups
- **12% DD** → shadow mode for weaker strategies
- **15% DD** → capital preservation mode
- **18% DD** → hard account lock

---

## Agent Roles

Each skill in `./skills/` defines a specialized agent. Key rules:

1. **Builder** — builds broker client, schemas, tests, pipelines
2. **Structure Mapper** — turns ICT concepts into numeric features and labels
3. **Strategy Researcher** — tests rule combos, proposes versioned strategies
4. **Risk Governor** — audits every signal, blocks violations
5. **Session Monitor** — watches spread, latency, rejection rate, broker mismatch
6. **Journal Analyst** — daily/weekly reviews: what worked, failed, regime, tuning
7. **Self-Improver** — measures skill performance, proposes skill edits, runs evals

---

## What Claude Agents Must NEVER Do

- Change risk parameters without explicit human approval
- Add new instruments automatically
- Deploy untested strategies to live execution
- Widen stops after entry
- Martingale after losses
- Interpret ambiguous chart patterns live without strict rules
- Overfit to recent demo trades
- Let the LLM rewrite strategy and keep firing trades unchecked

---

## Self-Healing Scope

### Infra Self-Healing (Automated)
- Re-auth if JWT expires
- Retry transient API errors with exponential backoff
- Resync positions if local ≠ broker state
- Pause new orders if reconciliation fails
- Auto-disable a broken module
- Rotate into safe mode on data feed anomalies

### Model Self-Healing (Semi-Automated, Human Approval for Promotion)
- Detect rising error rate
- Detect regime breakdown
- Reduce size after drawdown thresholds
- Disable underperforming strategies automatically
- Fall back to shadow mode if metrics degrade
- Promote only previously validated backup variants (requires human gate)

### Risk Self-Healing (Automated)
- Volatility spike → cut size
- Spread expansion → skip trade
- Correlation concentration → block new entries
- Losing streak threshold → de-lever
- Drawdown band breach → lower max risk
- Account DD near limit → freeze

---

## Scoring Each Trade Candidate

Every signal must pass through a prediction-market-style confidence scorer:

1. Probability setup works (0.0–1.0)
2. Expected reward/risk ratio
3. Regime confidence
4. Execution quality confidence
5. Structural clarity score
6. Correlated market confirmation (SMT)
7. Session timing score

**Trade only when:** confidence > threshold AND EV > threshold AND risk limits pass AND session/spread filters pass.

---

## File Conventions

- All config in `config/` as YAML
- All inter-engine data as JSON matching schemas in `schemas/`
- All logs structured JSON in `logs/`
- Trade data in `data/trades/` as dated JSONL
- Candle cache in `data/candles/`
- Signal history in `data/signals/`
- Review outputs in `data/reviews/`

---

## How to Use This Repo with Claude Code

```bash
# From project root, Claude Code reads this CLAUDE.md automatically.
# Skills are in ./skills/ — each has a SKILL.md.
# To work on a specific engine:
#   1. Read the relevant skill SKILL.md
#   2. Check schemas/ for the expected I/O
#   3. Check config/ for parameters
#   4. Build in core/<engine>/
#   5. Test in tests/
#   6. Log everything

# To improve a skill:
#   1. Read skills/self-improver/SKILL.md
#   2. Run the eval loop
#   3. Propose changes
#   4. Human reviews and approves
```

---

## Strategy Family (V1 — Three NY-Session Systems)

### 1. NY Open Sweep Reversal
- Identify overnight/pre-NY range → detect sweep of external liquidity → confirm SMT divergence or failed continuation → enter on LTF displacement/retest → target opposite internal liquidity or OR midpoint/extension

### 2. NY Continuation After Sweep
- Detect liquidity run → confirm continuation (not reversal) → trade with trend after pullback into imbalance/structure shift proxy

### 3. Psychological Level Rejection/Break
- Focus on round levels + session H/L → require confluence from SMT + liquidity + displacement → tighter stops, smaller target ladder

---

## Key Schemas (see schemas/ for full definitions)

- `market_state.json` — session ranges, liquidity pools, sweep events, SMT flags, PO3 candidates, psych level interactions
- `trade_signal.json` — direction, confidence, entry type, stop, targets, invalidation, strategy_id
- `approved_order.json` — sized order after risk gate, or rejection reason
- `trade_result.json` — execution record with fills, slippage, P&L, tags
- `review_report.json` — daily/weekly analytics output
