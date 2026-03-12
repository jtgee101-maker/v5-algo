---
name: risk-governor
description: "Audits every trade signal and blocks risk violations. Use this skill whenever working on: position sizing, exposure limits, drawdown throttling, correlation caps, daily/weekly loss limits, the risk engine in core/risk/, kill switch triggers, safe mode logic, or any decision about whether a trade should be allowed. Also trigger when reviewing risk parameters, analyzing drawdown events, debugging position size calculations, or implementing the adaptive drawdown staircase. This skill is NON-NEGOTIABLE — every trade must pass through the Risk Governor."
---

# Risk Governor Agent Skill

## Role
You are the final gatekeeper. No trade reaches the broker without your approval.
You are deterministic — no ML, no vibes, no discretion. Pure rules.

## Core Principle
**The Risk Engine is the only module that can NEVER be overridden by any other agent.**
If Risk says no, the answer is no. Period.

## Risk Engine Module: `core/risk/`

### `position_sizer.py`
Calculate position size from:
- Account equity (from execution engine)
- Risk per trade % (from config, adjusted by drawdown throttle)
- Stop distance in price units
- Instrument tick value and contract specs

```python
def calculate_position_size(
    equity: float,
    risk_pct: float,       # e.g., 0.0025 for 0.25%
    stop_distance: float,  # in price units
    tick_value: float,
    tick_size: float,
    min_lot: float,
    max_lot: float
) -> PositionSize:
    risk_amount = equity * risk_pct
    ticks_at_risk = stop_distance / tick_size
    raw_size = risk_amount / (ticks_at_risk * tick_value)
    # Round DOWN to min_lot increment
    size = floor_to_lot(raw_size, min_lot)
    size = min(size, max_lot)
    return PositionSize(lots=size, risk_amount=size * ticks_at_risk * tick_value)
```

### `exposure_checker.py`
Before approving any new trade, check:

| Check | Rule | Action if violated |
|---|---|---|
| Per-trade risk | ≤ config risk_per_trade (adjusted) | Reject |
| Total open risk | ≤ config max_simultaneous_risk | Reject |
| Correlated basket | ≤ config max_correlated_risk | Reject |
| Daily P&L | loss < config max_daily_loss | Reject + daily lockout |
| Weekly P&L | loss < config max_weekly_loss | Reject + weekly lockout |
| Account DD | < config max_drawdown | Reject + kill switch |
| Symbol exposure | ≤ config max_per_symbol | Reject |
| Spread | ≤ config max_spread_atr_pct | Reject (skip) |
| Session | NY active | Reject |

### `drawdown_throttle.py`
Implement the adaptive drawdown staircase:

```python
THROTTLE_LEVELS = [
    {"dd_pct": 0.05, "risk_reduction": 0.25, "action": "cut_risk"},
    {"dd_pct": 0.08, "risk_reduction": 0.50, "action": "cut_risk_and_positions"},
    {"dd_pct": 0.10, "risk_reduction": 0.75, "action": "a_tier_only"},
    {"dd_pct": 0.12, "risk_reduction": 0.90, "action": "shadow_weak_strategies"},
    {"dd_pct": 0.15, "risk_reduction": 1.00, "action": "capital_preservation"},
    {"dd_pct": 0.18, "risk_reduction": 1.00, "action": "hard_lock"},
]

def get_throttle_state(current_dd_pct: float) -> ThrottleState:
    active_level = None
    for level in THROTTLE_LEVELS:
        if current_dd_pct >= level["dd_pct"]:
            active_level = level
    if active_level is None:
        return ThrottleState(risk_multiplier=1.0, action="normal")
    return ThrottleState(
        risk_multiplier=1.0 - active_level["risk_reduction"],
        action=active_level["action"]
    )
```

### `correlation_manager.py`
- Define correlation groups in config
- Default groups: {NAS100, US30}, {EURUSD, GBPUSD}, {BTCUSD, ETHUSD}
- If already holding a position in one group member, cap additional exposure in same group
- Track realized correlation from recent data, flag if correlation breaks down

### `order_gate.py` — The Final Gate
This is the main entry point. For every `trade_signal.json`:

1. Validate signal schema
2. Check session status
3. Check spread filter
4. Calculate position size (with throttle-adjusted risk)
5. Check exposure limits
6. Check correlation limits
7. Check daily/weekly loss limits
8. Check drawdown state
9. If ALL pass → output `approved_order.json`
10. If ANY fail → output rejection with reason code + log

### `approved_order.json` output:
```json
{
  "approved": true,
  "signal_ref": "trade_signal_NAS100_20250115T1432.json",
  "symbol": "NAS100",
  "direction": "long",
  "entry_type": "limit",
  "entry_price": 18245.50,
  "stop_price": 18210.00,
  "targets": [...],
  "position_size": 0.5,
  "risk_amount": 25.00,
  "risk_pct_actual": 0.0025,
  "throttle_state": "normal",
  "checks_passed": ["session", "spread", "size", "exposure", "correlation", "daily", "weekly", "drawdown"],
  "timestamp": "2025-01-15T14:32:01Z"
}
```

### Rejection output:
```json
{
  "approved": false,
  "signal_ref": "trade_signal_NAS100_20250115T1432.json",
  "rejection_reason": "daily_loss_limit_reached",
  "rejection_detail": "Daily P&L: -1.52% exceeds limit of -1.50%",
  "throttle_state": "cut_risk",
  "timestamp": "2025-01-15T14:32:01Z"
}
```

## Config: `config/risk.yaml`
```yaml
base_risk:
  risk_per_trade: 0.0025        # 0.25%
  max_simultaneous_risk: 0.0150 # 1.50%
  max_correlated_risk: 0.0080   # 0.80%
  max_per_symbol: 0.0050        # 0.50%

limits:
  max_daily_loss: 0.015         # 1.5%
  max_weekly_loss: 0.04         # 4.0%
  max_drawdown: 0.18            # 18%
  max_trades_per_day: 3
  max_spread_atr_pct: 0.15      # skip if spread > 15% of ATR

correlation_groups:
  indices: ["NAS100", "US30"]
  fx_majors: ["EURUSD", "GBPUSD"]
  crypto: ["BTCUSD", "ETHUSD"]

throttle_levels:
  - dd_pct: 0.05
    risk_reduction: 0.25
  - dd_pct: 0.08
    risk_reduction: 0.50
  - dd_pct: 0.10
    risk_reduction: 0.75
  - dd_pct: 0.12
    risk_reduction: 0.90
  - dd_pct: 0.15
    risk_reduction: 1.00
  - dd_pct: 0.18
    action: hard_lock
```

## Testing Requirements
- Test every gate independently
- Test throttle transitions at exact boundary values
- Test that kill switch fires at 18% DD
- Test that no combination of inputs can bypass a limit
- Fuzz test with random signals to ensure no crashes
- The Risk Engine must NEVER raise an unhandled exception — it must always return approve or reject
