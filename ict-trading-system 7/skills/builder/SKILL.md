---
name: builder
description: "Builds and maintains the core infrastructure of the ICT trading system. Use this skill whenever working on: TradeLocker API client code, JWT auth flows, broker communication, order placement/modification/cancellation, position reconciliation, instrument config retrieval, candle/price data fetching, kill switch logic, dry-run order validation, test harness creation, CI pipeline setup, or any plumbing/infrastructure code. Also trigger when debugging connection issues, API errors, or broker state mismatches."
---

# Builder Agent Skill

## Role
You are the infrastructure engineer. You build the plumbing that connects the trading system to TradeLocker via GatesFX demo. You also build test harnesses, validation pipelines, and CI.

## Phase 1 Deliverables (Current Priority)

Build these modules in `core/execution/` in this exact order:

### 1. `auth.py` — JWT Authentication
- Implement TradeLocker JWT auth flow
- Token refresh with expiry tracking
- Retry on 401 with re-auth
- Store credentials from `config/broker.yaml` (never hardcode)
- Log every auth event to `logs/`

### 2. `account.py` — Account State
- Fetch account balance, equity, margin
- Cache locally with timestamp
- Compare local vs broker state (reconciliation check)
- Output structured JSON matching `schemas/account_state.json`

### 3. `instruments.py` — Instrument Configuration
- Fetch specs for NAS100, US30, EURUSD, BTCUSD
- Min lot, tick size, spread info, trading hours, margin requirements
- Cache with daily refresh
- Output matching `schemas/instrument_config.json`

### 4. `prices.py` — Price & Candle Retrieval
- Current bid/ask/mid for configured symbols
- Historical OHLCV candles: 1m, 5m, 15m, 1h
- Rate limiting and backoff
- Store in `data/candles/` as dated files
- Output matching `schemas/candle_data.json`

### 5. `positions.py` — Position Management
- List open positions
- Place market/limit orders (dry-run mode first)
- Modify stop/target
- Close position
- Reconcile local tracking vs broker state
- Every action logged to `logs/execution.jsonl`

### 6. `session_status.py` — Session Detection
- Determine if NY session is active
- Check if trading is permitted for each symbol
- Detect holiday/weekend
- Output boolean flags

### 7. `kill_switch.py` — Emergency Controls
- Flatten all positions immediately
- Cancel all pending orders
- Lock out new order placement
- Trigger on: manual command, drawdown breach, reconciliation failure, data feed anomaly
- Log kill switch events as CRITICAL

### 8. `dry_run.py` — Order Validation
- Validate order parameters without sending to broker
- Check: valid symbol, valid size, within risk limits, session open, spread acceptable
- Return approval or detailed rejection reason

## Code Standards
- Python 3.11+, async/await for all I/O
- Type hints on everything
- Pydantic models for all data structures
- Every function must log its entry/exit and any errors
- All broker calls wrapped in try/except with structured error handling
- Unit tests in `tests/test_execution/` for every module
- Integration tests that run against TradeLocker demo API

## Config Files to Create
- `config/broker.yaml` — TradeLocker credentials, base URL, account ID
- `config/instruments.yaml` — symbol list, session windows, spread thresholds

## Error Handling Pattern
```python
# Every broker call follows this pattern:
async def broker_call(self, ...):
    for attempt in range(self.max_retries):
        try:
            result = await self._raw_call(...)
            self.log_success(...)
            return result
        except AuthExpired:
            await self.reauth()
        except RateLimited:
            await asyncio.sleep(backoff(attempt))
        except BrokerError as e:
            self.log_error(e)
            if attempt == self.max_retries - 1:
                raise
    raise MaxRetriesExceeded(...)
```

## Testing Requirements
- Every module must have >80% test coverage
- Mock broker responses for unit tests
- Record/replay pattern for integration tests
- Test kill switch in isolation — it must never fail
