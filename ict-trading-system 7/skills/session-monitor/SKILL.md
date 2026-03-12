---
name: session-monitor
description: "Monitors live execution health and broker state during trading sessions. Use this skill when working on: spread monitoring, latency tracking, fill quality analysis, broker state reconciliation, data feed anomaly detection, order rejection rate tracking, safe mode triggers, or any real-time operational health metric. Also trigger when debugging execution issues, investigating slippage, or building alerting/notification systems."
---

# Session Monitor Agent Skill

## Role
You are the operational health watchdog. You run during every active trading session
and detect problems before they cause losses.

## What You Monitor

### 1. Spread Health
- Track bid-ask spread for each symbol continuously during session
- Compare to historical average and ATR-normalized threshold
- Flag WIDE_SPREAD if spread > `config.max_spread_atr_pct`
- Action: block new entries until spread normalizes

### 2. Execution Latency
- Measure round-trip time for every broker API call
- Track rolling p50, p95, p99
- Flag HIGH_LATENCY if p95 > `config.max_latency_ms`
- Action: log warning; if sustained, switch to safe mode

### 3. Fill Quality
- For every executed order, record:
  - Requested price vs fill price (slippage)
  - Time from signal to fill
  - Partial fills
- Flag POOR_FILLS if average slippage > threshold
- Action: log for journal analyst, reduce size if sustained

### 4. Order Rejection Rate
- Track rejections from broker (not from our risk engine)
- Flag HIGH_REJECTION if > 2 broker rejections in 10 minutes
- Action: pause new orders, investigate, log

### 5. Position Reconciliation
- Every 60 seconds during session: compare local position state to broker state
- Flag STATE_MISMATCH if they differ
- Action: if mismatch found, pause new orders, attempt resync, log as WARNING
- If resync fails 3 times: trigger kill switch

### 6. Data Feed Health
- Detect stale prices (no update for > `config.stale_price_seconds`)
- Detect price jumps (gap > `config.max_gap_atr`)
- Flag DATA_ANOMALY
- Action: pause trading, wait for stable data, log

### 7. Heartbeat
- Emit a heartbeat event every 30 seconds during session
- If heartbeat stops, external monitor should alert

## Output: `session_health.json`
```json
{
  "timestamp": "2025-01-15T14:35:00Z",
  "session": "ny",
  "status": "healthy",
  "spreads": {
    "NAS100": {"current": 1.2, "avg": 1.0, "status": "ok"},
    "EURUSD": {"current": 0.8, "avg": 0.6, "status": "ok"}
  },
  "latency": {"p50_ms": 120, "p95_ms": 280, "status": "ok"},
  "fill_quality": {"avg_slippage_ticks": 0.3, "status": "ok"},
  "rejection_rate": {"last_10min": 0, "status": "ok"},
  "reconciliation": {"synced": true, "last_check": "2025-01-15T14:34:30Z"},
  "data_feed": {"stale_symbols": [], "status": "ok"},
  "flags": [],
  "safe_mode": false
}
```

## Safe Mode
When any critical flag persists for > `config.safe_mode_delay_seconds`:
- Block all new entries
- Keep existing positions (don't auto-flatten unless kill switch triggers)
- Log safe mode entry
- Resume only when all flags clear for > `config.safe_mode_clear_seconds`

## Config: `config/monitoring.yaml`
```yaml
spread:
  max_spread_atr_pct: 0.15
  check_interval_seconds: 5

latency:
  max_p95_ms: 500
  check_interval_seconds: 10

fills:
  max_avg_slippage_ticks: 2.0
  lookback_trades: 20

rejections:
  max_per_10min: 2

reconciliation:
  check_interval_seconds: 60
  max_resync_attempts: 3

data_feed:
  stale_price_seconds: 30
  max_gap_atr: 3.0

safe_mode:
  delay_seconds: 30
  clear_seconds: 120

heartbeat:
  interval_seconds: 30
```

## Implementation in `core/agents/session_monitor.py`
- Async event loop running during NY session
- Each check runs on its own timer
- All events logged to `logs/session_health.jsonl`
- Aggregate status written to `data/signals/session_health.json`
