---
name: structure-mapper
description: "Converts ICT trading concepts into machine-readable numeric features and labels. Use this skill whenever working on: session range detection, liquidity pool mapping, swing point detection, equal highs/lows identification, psychological price level engines, SMT divergence detection, sweep/displacement detection, Power of 3 sequence identification, fair value gap detection, or any market structure labeling logic. Also trigger when translating a discretionary trading concept into a testable rule, building feature extraction pipelines, or debugging structure detection accuracy."
---

# Structure Mapper Agent Skill

## Role
You translate ICT-style discretionary concepts into structured, testable, numeric feature extractors.
Your output feeds the Market Structure Engine (`core/market_structure/`).

## Core Principle
**Never trade ICT as a vibe.** Every concept must become a measurable feature with:
- A clear definition
- Numeric thresholds (configurable via `config/structure.yaml`)
- A boolean or scored output
- Unit tests with known candle data

## Feature Modules to Build

### 1. `session_ranges.py` — Session Box Detection
**ICT concept:** Trading sessions have distinct ranges.

**Machine version:**
- Define Asia session box (configurable hours in UTC)
- Define London session box
- Define NY session box (primary)
- Pre-NY overnight range = Asia + London combined
- Output: `session_range` object with `high`, `low`, `mid`, `range_atr_ratio`

### 2. `liquidity_pools.py` — Liquidity Map
**ICT concept:** Liquidity rests at prior highs/lows, equal levels, session boundaries.

**Machine version:**
- Prior Day High/Low (PDH/PDL)
- Asia Range High/Low
- Weekly High/Low
- Equal highs/lows (cluster detection: N swing points within X ticks)
- Opening range highs/lows (first 15–30 min of NY)
- Output: sorted list of `liquidity_level` objects with `price`, `type`, `strength_score`, `age_bars`

### 3. `swing_detection.py` — Swing Point Identification
**ICT concept:** Market structure is defined by swing highs and swing lows.

**Machine version:**
- Rolling swing detection with configurable lookback (default: 5 bars each side)
- Label: swing_high, swing_low
- Break of structure (BOS): price closes beyond prior swing
- Change of character (CHoCH): BOS against prevailing trend
- Output: list of `swing_point` objects + `structure_bias` (bullish/bearish/ranging)

### 4. `smt_divergence.py` — SMT Divergence Detection
**ICT concept:** When correlated instruments diverge at key levels, it signals a reversal.

**Machine version:**
- Define correlation pairs in config: EURUSD↔DXY, NAS100↔US30, BTCUSD↔ETHUSD
- Rolling swing point detection on both instruments
- Divergence flag: instrument A breaks prior swing high/low, instrument B fails to within N bars
- Only valid during configured session window
- Volatility filter: skip if ATR below minimum threshold
- Output: `smt_signal` with `pair`, `direction`, `strength`, `timestamp`, `session_valid`

### 5. `po3_detector.py` — Power of 3 Sequence
**ICT concept:** Accumulation → Manipulation → Distribution within a session.

**Machine version:**
- **Accumulation:** identify tight range during pre-NY (range < X% of daily ATR)
- **Manipulation:** detect price sweep beyond accumulation range by Y ATR/pips
- **Distribution:** confirm expansion in opposite direction of manipulation
- Sequence state machine: IDLE → ACCUMULATING → MANIPULATED → DISTRIBUTING → COMPLETE
- Output: `po3_state` with `phase`, `accumulation_range`, `manipulation_extreme`, `distribution_bias`, `confidence`

### 6. `psych_levels.py` — Psychological Price Level Grid
**ICT concept:** Round numbers and big figures attract price action.

**Machine version:**
- Build dynamic level grid per symbol:
  - FX: 00, 20, 50, 80 levels (e.g., 1.0800, 1.0820, 1.0850)
  - Indices: 00, 25, 50, 75 levels (e.g., 18000, 18025, 18050)
  - Crypto: round 100s, 500s, 1000s depending on price
- Score setups higher when sweep/reversal occurs within `config.psych_proximity_ticks` of a level
- Output: nearest levels above/below current price + `proximity_score`

### 7. `displacement.py` — Displacement & Fair Value Gap Detection
**ICT concept:** Strong moves leave gaps (FVGs) that act as future support/resistance.

**Machine version:**
- Displacement candle: body > X * ATR, close near extreme
- Fair value gap: 3-candle pattern where candle 1 high < candle 3 low (bullish) or candle 1 low > candle 3 high (bearish)
- Track open vs filled FVGs
- Output: list of `fvg` objects with `type`, `upper`, `lower`, `filled`, `age_bars`

### 8. `market_state_assembler.py` — Combine All Features
- Collect outputs from all detectors
- Assemble into unified `market_state.json` per schema
- Tag with timestamp, symbol, timeframe context
- Write to `data/signals/market_state_{symbol}_{timestamp}.json`

## Config File: `config/structure.yaml`
```yaml
sessions:
  asia:
    start_utc: "00:00"
    end_utc: "08:00"
  london:
    start_utc: "08:00"
    end_utc: "13:00"
  ny:
    start_utc: "13:00"
    end_utc: "21:00"
  ny_killzone:
    start_utc: "13:30"
    end_utc: "16:00"

swing_detection:
  lookback_bars: 5
  min_swing_distance_atr: 0.3

smt:
  pairs:
    - ["EURUSD", "DXY"]
    - ["NAS100", "US30"]
    - ["BTCUSD", "ETHUSD"]
  max_divergence_bars: 8
  min_atr_filter: 0.5

po3:
  accumulation_max_range_atr_pct: 0.4
  manipulation_min_sweep_atr: 0.3
  distribution_min_expansion_atr: 0.6

psych_levels:
  fx_granularity: [0, 20, 50, 80]
  index_granularity: [0, 25, 50, 75]
  proximity_ticks: 10

fvg:
  displacement_min_body_atr: 1.5
  max_age_bars: 50
```

## Testing
- Create synthetic candle datasets that exhibit known patterns
- Each detector must identify the pattern in synthetic data with >95% accuracy
- Each detector must NOT false-positive on random/flat data
- Store test fixtures in `tests/fixtures/candles/`
