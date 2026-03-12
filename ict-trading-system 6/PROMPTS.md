# Claude Code Operating Pack

## How to use this file

This is your **copy-paste prompt library** for Claude Code sessions.
Each section is a self-contained prompt you paste into Claude Code at the project root.
Work through them in order. Do not skip phases.

Before every session:
1. Open the project in Claude Code
2. Claude auto-reads CLAUDE.md
3. Paste the appropriate prompt below
4. Let Claude work
5. Review, test, iterate

---

## PHASE 1 PROMPTS (Broker + Safety)

These are for getting the TradeLocker connection working.

### Prompt 1.1: Broker Connection Check

```
Read CLAUDE.md, config/broker.yaml, and core/execution/client.py.

Task: Run scripts/check_broker_connection.py and fix any issues.

If environment variables are not set, tell me which ones I need and stop.
If the broker URL or API paths need adjustment for GatesFX, identify what needs changing.

Do not modify risk limits or strategy code.
```

### Prompt 1.2: Instrument Mapping

```
Read CLAUDE.md, core/execution/mapper.py, and core/execution/client.py.

Task:
1. Run check_broker_connection.py to get a list of available instruments
2. Map our V1 symbols (NAS100, US30, EURUSD, BTCUSD) to actual TradeLocker instrument IDs
3. Create a fallback mapping in config/broker.yaml if names differ from what TradeLocker returns
4. Verify mapper.get_instrument_id works for all 4 symbols
5. Add a test in tests/test_mapper.py

Do not change risk parameters or strategy logic.
```

### Prompt 1.3: Kill Switch Verification

```
Read CLAUDE.md and core/execution/client.py.

Task:
1. Write a test that simulates the kill switch
2. Verify it correctly attempts to close all positions and cancel all orders
3. Verify it handles errors gracefully (broker down, partial failures)
4. Add the test to tests/test_execution.py

This is the most critical safety module. It must NEVER raise an unhandled exception.
```

---

## PHASE 2 PROMPTS (Market Structure Engine)

These build the feature extraction layer.

### Prompt 2.1: Session Labeling (Start Here)

```
Read CLAUDE.md, skills/structure-mapper/SKILL.md, config/structure.yaml, and core/market_structure/session.py.

Task:
1. Run the existing tests: pytest tests/test_market_structure.py -v
2. Fix any failures
3. If session.py is working, verify edge cases:
   - Midnight crossing sessions
   - Pre-NY to NY transition
   - Weekend detection for Friday evening to Sunday
4. Add any missing test cases

Do not modify risk or execution code.
```

### Prompt 2.2: Swing Detection + Bias

```
Read skills/structure-mapper/SKILL.md and core/market_structure/swings.py.

Task:
1. Run pytest tests/test_market_structure.py::TestSwingDetector -v
2. Fix any failures
3. Create better synthetic test data with clear swing patterns:
   - A clearly bullish sequence (HH + HL)
   - A clearly bearish sequence (LH + LL)
   - A ranging sequence
4. Verify BOS and CHoCH detection work
5. Add tests for broken swing marking

Output only: changes to swings.py and test_market_structure.py
```

### Prompt 2.3: Liquidity Pool Mapping

```
Read skills/structure-mapper/SKILL.md and core/market_structure/liquidity.py.

Task:
1. Run tests for LiquidityMapper
2. Fix any failures
3. Add tests for:
   - Equal highs/lows detection with tight tolerance
   - Opening range calculation
   - Sweep detection on liquidity levels (wick above level, close below)
4. Verify the sweep checker correctly marks pools as swept

Do not modify risk or execution code.
```

### Prompt 2.4: Displacement + FVG

```
Read skills/structure-mapper/SKILL.md and core/market_structure/displacement.py.

Task:
1. Run FVG tests
2. Create synthetic data with a clear 3-candle bullish FVG
3. Create synthetic data with a clear bearish FVG
4. Test FVG fill detection (price returns and fills the gap)
5. Test displacement candle detection with ATR threshold
6. Add all tests to test_market_structure.py
```

### Prompt 2.5: SMT Divergence

```
Read skills/structure-mapper/SKILL.md, config/structure.yaml (smt section), and core/market_structure/smt.py.

Task:
1. Create test data for two correlated instruments where:
   - Instrument A makes a new high, Instrument B fails to
   - This should produce a bearish SMT signal
2. Create test data for bullish divergence (A new low, B fails)
3. Test the ATR filter (should skip when volatility too low)
4. Test the session validity filter
5. Add all tests to test_market_structure.py

Do not create tests that require live broker data.
```

### Prompt 2.6: Power of 3

```
Read skills/structure-mapper/SKILL.md and core/market_structure/po3.py.

Task:
1. Create test data that simulates a full PO3 sequence:
   - Tight pre-NY range (accumulation)
   - Sweep above the range (manipulation)
   - Expansion downward (distribution)
2. Verify the state machine transitions: IDLE → ACCUMULATING → MANIPULATED → DISTRIBUTING
3. Test the reset function
4. Test timeout behavior (too many bars without transition)
5. Add all tests
```

### Prompt 2.7: Full Market Structure Engine Integration

```
Read CLAUDE.md and core/market_structure/engine.py.

Task:
1. Run ALL market structure tests: pytest tests/test_market_structure.py -v
2. Fix any remaining failures
3. Create one integration test that:
   - Builds 50+ synthetic candles with known patterns
   - Calls engine.build_state()
   - Verifies the output MarketState has correct session, bias, pools, and swings
4. Wire engine.build_state into pipeline.py (verify it's already done)
5. Run the full test suite to ensure nothing is broken

Keep shadow/demo safety intact.
```

---

## PHASE 3 PROMPTS (Shadow Mode)

### Prompt 3.1: Strategy Implementation

```
Read skills/strategy-researcher/SKILL.md, config/strategy.yaml, schemas/trade_signal.json, and core/strategy/ny_sweep_reversal.py.

Task:
1. Create synthetic MarketState objects that would trigger a sweep reversal signal:
   - Session = NY killzone
   - Overnight range present
   - Sweep event detected
   - FVG available for entry
2. Test that the strategy produces a valid TradeSignal
3. Test that the confidence scorer produces reasonable scores
4. Test that the strategy rejects setups below min_confidence
5. Test that R:R below threshold is rejected
6. Add all tests to tests/test_strategy.py

Do not modify risk limits or execution code.
```

### Prompt 3.2: Shadow Pipeline End-to-End

```
Read CLAUDE.md and core/pipeline.py.

Task:
1. Run scripts/validate_configs.py — fix any issues
2. Verify that pipeline.py has NO stubs or TODOs remaining
3. Create a test that:
   - Mocks the broker client
   - Feeds synthetic candle data through the full pipeline
   - Verifies a signal is generated and logged
   - Verifies the risk gate approves or rejects correctly
   - Verifies no orders are placed in shadow mode
4. Add to tests/test_pipeline.py

Do not enable live execution.
```

### Prompt 3.3: Run Shadow Mode

```
Task:
1. Ensure all tests pass: pytest -v
2. Run: python scripts/run_shadow.py
3. Monitor the first few minutes of output
4. Check data/signals/ for logged signals
5. If errors occur, diagnose and fix
6. Report: what worked, what failed, what needs attention
```

---

## PHASE 4 PROMPTS (Tiny Demo Execution)

### Prompt 4.1: Demo Gate Check

```
Read CLAUDE.md.

Before enabling demo execution:
1. Count signals from shadow mode in data/signals/
2. How many were approved by risk gate?
3. What was the average confidence?
4. Were there any throttle events?
5. Were there any errors in logs/?

Produce a gate check report. Do NOT enable demo mode yet.
```

### Prompt 4.2: Enable Demo (After Human Approval)

```
Read CLAUDE.md. I have approved demo mode.

Task:
1. Run scripts/run_demo.py
2. Verify orders are sent as dry-run
3. Monitor for 1 session
4. Check that all risk limits are respected
5. Produce a session report
```

---

## MAINTENANCE PROMPTS (Use Anytime)

### Gap Report

```
Read CLAUDE.md, README.md, config/, schemas/, and all core/ modules.

Create a gap report with three sections:
1. Fully implemented (tests pass, no stubs)
2. Partially implemented (code exists but has TODOs or untested paths)
3. Missing but required for the current phase

Be specific: list exact file paths and function names.
```

### Daily Improvement Cycle

```
Read skills/self-improver/SKILL.md.

Task:
1. Run python scripts/gather_improvement_data.py --period daily
2. Run python scripts/diagnose.py --data <output file>
3. Review the diagnosis report
4. Propose up to 3 specific improvements with evidence
5. Do NOT apply changes — present them for my review

Format each proposal as:
- What to change
- Why (evidence from data)
- Expected impact
- Risk of the change
```

### Weekly Review

```
Read skills/journal-analyst/SKILL.md.

Task:
1. Gather all signals, trades, and logs from this week
2. Produce a weekly review covering:
   - Strategy scoreboard (trades, win rate, avg R, expectancy)
   - Regime analysis (what type of market this week?)
   - Confidence calibration (were high-confidence trades actually better?)
   - Self-healing events (any throttles, safe mode, kills?)
   - Top 3 recommendations
3. Save to data/reviews/weekly_<date>.json
4. Present a summary
```

### Do Not Drift Prompt (Reuse Often)

```
Stay inside the current task only.
Do not refactor unrelated files.
Do not modify risk limits.
Do not change execution mode.
Do not add new strategies.
Do not leave placeholders or TODOs in files you touch.
Add or update tests for every functional change.
If a dependency is missing, state it explicitly and stop there.
```

---

## IMPLEMENTATION ORDER CHECKLIST

Use this to track progress. Work top-to-bottom.

### Phase 1: Broker + Safety
- [ ] pip install -e ".[dev]" works
- [ ] pytest runs without import errors
- [ ] validate_configs.py passes
- [ ] Broker env vars set
- [ ] check_broker_connection.py passes
- [ ] Instrument mapper resolves all 4 V1 symbols
- [ ] Kill switch test passes
- [ ] Dry-run order validation works

### Phase 2: Market Structure
- [ ] Session detection tests pass (all edge cases)
- [ ] Swing detection tests pass (bullish, bearish, ranging)
- [ ] Liquidity mapper tests pass (PDH/PDL, Asia, equal levels, sweeps)
- [ ] Displacement/FVG tests pass (bullish FVG, bearish FVG, fill detection)
- [ ] Psych levels tests pass (indices, FX, proximity scoring)
- [ ] SMT divergence tests pass (bearish div, bullish div, filters)
- [ ] PO3 state machine tests pass (full sequence, reset, timeout)
- [ ] Full engine integration test passes
- [ ] pipeline._build_market_state calls real engine
- [ ] No stubs remain in market_structure/

### Phase 3: Shadow Mode
- [ ] NY Sweep Reversal strategy tests pass
- [ ] Confidence scorer tests pass
- [ ] Strategy engine correctly wraps active strategies
- [ ] Pipeline end-to-end test passes (mocked broker)
- [ ] run_shadow.py runs without errors for a full session
- [ ] Signals are logged to data/signals/
- [ ] Risk gate approves/rejects correctly
- [ ] No orders placed in shadow mode
- [ ] At least 20 shadow signals generated

### Phase 4: Tiny Demo
- [ ] Gate check report produced
- [ ] Human approves demo mode
- [ ] run_demo.py runs with dry-run orders
- [ ] All risk limits respected
- [ ] Session report produced

### Phase 5: Multi-Strategy
- [ ] NY Continuation strategy implemented + tested
- [ ] Psych Level model implemented + tested
- [ ] Dynamic throttling verified
- [ ] Performance attribution by strategy works
- [ ] Journal analyst produces weekly reviews

### Phase 6: Live Readiness
- [ ] 100+ shadow trade sample
- [ ] Drawdown stayed inside tolerance
- [ ] Execution integrity stable
- [ ] Edge survives spread + costs
- [ ] Self-healing events behaved correctly
- [ ] Human final sign-off

---

## FILE INVENTORY (What Exists Now)

### Fully Implemented
- config/broker.yaml
- config/risk.yaml
- config/strategy.yaml
- config/structure.yaml
- config/monitoring.yaml
- schemas/market_state.json
- schemas/trade_signal.json
- schemas/approved_order.json
- schemas/trade_result.json
- core/models.py
- core/risk/engine.py
- core/execution/client.py
- core/execution/mapper.py
- core/market_structure/session.py
- core/market_structure/swings.py
- core/market_structure/liquidity.py
- core/market_structure/psych_levels.py
- core/market_structure/displacement.py
- core/market_structure/smt.py
- core/market_structure/po3.py
- core/market_structure/engine.py
- core/strategy/scorer.py
- core/strategy/ny_sweep_reversal.py
- core/strategy/engine.py
- core/pipeline.py (no stubs)
- scripts/run_shadow.py
- scripts/run_demo.py
- scripts/validate_configs.py
- scripts/check_broker_connection.py
- scripts/gather_improvement_data.py
- scripts/diagnose.py
- tests/test_risk_engine.py
- tests/test_market_structure.py
- CLAUDE.md
- README.md

### Not Yet Built (Future Phases)
- core/strategy/continuation.py (Phase 5)
- core/strategy/psych_rejection.py (Phase 5)
- core/execution/reconciliation.py (Phase 4)
- core/monitoring/health.py (Phase 3+)
- core/monitoring/alerts.py (Phase 4+)
- core/journaling/recorder.py (Phase 3+)
- core/journaling/reviewer.py (Phase 3+)
- tests/test_strategy.py (Phase 3 — prompt provided above)
- tests/test_pipeline.py (Phase 3 — prompt provided above)
