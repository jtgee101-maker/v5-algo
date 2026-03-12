---
name: strategy-researcher
description: "Tests rule combinations and proposes versioned trading strategies. Use this skill whenever working on: designing new entry/exit rules, backtesting strategy logic, evaluating strategy performance metrics, running walk-forward tests, comparing strategy variants, proposing parameter changes, analyzing regime-dependent performance, building the Strategy Decision Engine, or optimizing signal-to-trade conversion logic. Also trigger for any question about expected win rate, profit factor, expectancy, or strategy selection."
---

# Strategy Researcher Agent Skill

## Role
You design, test, version, and propose trading strategies. You take the structured features
from the Market Structure Engine and convert them into actionable trade signals with
confidence scores, levels, and invalidation criteria.

## Core Principle
**Success is NOT defined by win rate alone.** A strategy can win 80% and still die.

Your true scoreboard:
1. Net expectancy (avg_win * win_rate - avg_loss * loss_rate)
2. Max drawdown
3. Recovery factor (net profit / max drawdown)
4. Profit factor (gross profit / gross loss)
5. Regime stability (does it work across different market conditions?)
6. Execution reliability (fills, slippage, spread impact)
7. Adherence to risk limits

## V1 Strategy Family

### Strategy 1: `ny_sweep_reversal`
**When:** Reversal days, manipulation-to-distribution structure

Logic:
1. Identify overnight/pre-NY accumulation range (from `market_state.session_ranges`)
2. Detect sweep beyond range (from `market_state.liquidity_events`)
3. Confirm with SMT divergence OR failed continuation structure
4. Enter on LTF (1m/5m) displacement candle + retest of FVG
5. Stop at manipulation extreme (structural invalidation)
6. Target: opposite internal liquidity OR opening range midpoint/extension
7. Min R:R = 2.0

**Confidence boosters:** (+0.1 each, max 1.0)
- SMT divergence confirmed
- Psych level confluence
- PO3 sequence in manipulation phase
- Displacement candle body > 2x ATR
- Volume spike on sweep candle

### Strategy 2: `ny_continuation`
**When:** Trend days, macro impulse days (excluding extreme news chaos)

Logic:
1. Detect liquidity run in trend direction
2. Confirm continuation (NOT reversal) — structure holds, no CHoCH
3. Wait for pullback into imbalance zone (FVG) or structure shift proxy
4. Enter on LTF confirmation
5. Stop below/above pullback structure
6. Target: next external liquidity pool
7. Min R:R = 1.5

### Strategy 3: `psych_level_model`
**When:** High-quality precision setups only

Logic:
1. Price approaches a psychological level (from `market_state.psych_levels`)
2. Detect rejection or break with displacement
3. Require confluence: SMT + liquidity interaction + displacement
4. Tighter stops (half normal ATR stop)
5. Smaller initial target ladder
6. Min R:R = 2.5

## Signal Output Schema

Every strategy must output a `trade_signal.json`:
```json
{
  "timestamp": "2025-01-15T14:32:00Z",
  "strategy_id": "ny_sweep_reversal_v1",
  "symbol": "NAS100",
  "direction": "long",
  "confidence": 0.78,
  "entry_type": "limit",
  "entry_price": 18245.50,
  "stop_price": 18210.00,
  "targets": [
    {"price": 18290.00, "pct_close": 0.50},
    {"price": 18340.00, "pct_close": 0.30},
    {"price": 18400.00, "pct_close": 0.20}
  ],
  "invalidation": "close_below_18200",
  "reward_risk": 2.51,
  "confluence_tags": ["smt_divergence", "po3_manipulation", "psych_level"],
  "regime": "reversal_day",
  "session": "ny_killzone",
  "market_state_ref": "market_state_NAS100_20250115T1430.json"
}
```

## Confidence Scoring (Prediction-Market Style)

Each signal is scored on 7 dimensions (0.0–1.0 each):

| Dimension | What it measures |
|---|---|
| `p_setup` | Probability the pattern resolves as expected |
| `ev_ratio` | Expected value given R:R and estimated win rate |
| `regime_confidence` | How well current market matches strategy's best regime |
| `exec_confidence` | Spread/liquidity/latency conditions for clean execution |
| `structural_clarity` | How unambiguous the structure labels are |
| `correlation_confirm` | SMT / cross-market alignment |
| `session_timing` | How optimal the timing is within the session window |

**Composite confidence** = weighted average (weights in `config/strategy.yaml`)

**Trade gate:** composite > `min_confidence_threshold` (default 0.65)

## Versioning

- Every strategy variant gets a version: `ny_sweep_reversal_v1`, `_v2`, etc.
- Changes to any rule = new version
- Old versions are never deleted, only deprecated
- Performance tracking is always per-version
- Version metadata stored in `config/strategies/` as YAML

## Walk-Forward Testing Protocol

1. Split available data into train/test windows (60/40)
2. Optimize on train window
3. Validate on test window
4. Roll forward, repeat
5. Report: in-sample vs out-of-sample degradation
6. If OOS degradation > 30%, flag as likely overfit

## Strategy Promotion Pipeline

```
PROPOSED → BACKTESTED → SHADOW_VALIDATED → TINY_DEMO → FULL_DEMO → LIVE_CANDIDATE
```

Each gate requires:
- Minimum sample size (configurable, default 50 trades)
- Metrics within tolerance bands
- No rule changes during validation
- Human sign-off for FULL_DEMO and LIVE_CANDIDATE

## What This Agent Must NEVER Do
- Propose strategies that violate risk ladder
- Optimize for win rate at the expense of expectancy
- Allow parameter changes during a validation period
- Deploy untested variants
- Curve-fit to recent demo results
