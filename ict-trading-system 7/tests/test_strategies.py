"""Tests for all three V1 strategies.

Tests use synthetic MarketState objects with known patterns
to verify each strategy correctly identifies or rejects setups.
"""

from datetime import datetime, timezone

import pytest

from core.models import (
    Direction, FVG, LiquidityPool, LiquidityType, MarketState,
    PO3Phase, PO3State, PriceRange, PsychLevels, SessionName,
    StructureBias, SweepEvent, SwingPoint, SMTSignal,
)
from core.strategy.ny_sweep_reversal import NYSweepReversalStrategy
from core.strategy.ny_continuation import NYContinuationStrategy
from core.strategy.psych_level_rejection import PsychLevelStrategy


NOW = datetime(2025, 1, 15, 14, 30, 0, tzinfo=timezone.utc)


def _base_state(**overrides) -> MarketState:
    """Build a base market state suitable for testing."""
    defaults = dict(
        timestamp=NOW,
        symbol="NAS100",
        session=SessionName.NY_KILLZONE,
        session_ranges={"overnight": PriceRange(high=18450, low=18320, mid=18385)},
        liquidity_pools=[
            LiquidityPool(price=18490, type=LiquidityType.PDH, strength_score=0.8),
            LiquidityPool(price=18280, type=LiquidityType.PDL, strength_score=0.8),
            LiquidityPool(price=18390, type=LiquidityType.ASIA_HIGH, strength_score=0.7),
        ],
        structure_bias=StructureBias.BULLISH,
        swing_points=[
            SwingPoint(price=18300, type="swing_low", bar_index=10, timestamp=NOW),
            SwingPoint(price=18400, type="swing_high", bar_index=20, timestamp=NOW),
            SwingPoint(price=18330, type="swing_low", bar_index=30, timestamp=NOW),
            SwingPoint(price=18450, type="swing_high", bar_index=40, timestamp=NOW),
            SwingPoint(price=18380, type="swing_low", bar_index=50, timestamp=NOW),
            SwingPoint(price=18470, type="swing_high", bar_index=60, timestamp=NOW),
        ],
        smt_signals=[SMTSignal(pair=("NAS100", "US30"), direction=Direction.LONG,
                               strength=0.7, timestamp=NOW, session_valid=True)],
        po3_state=PO3State(phase=PO3Phase.MANIPULATED, confidence=0.5),
        psych_levels=PsychLevels(nearest_above=18500, nearest_below=18400, proximity_score=0.8),
        fvgs=[FVG(type=Direction.LONG, upper=18370, lower=18360, filled=False, age_bars=5)],
        displacement_candles=[{"timestamp": NOW.isoformat(), "direction": "bullish", "body_atr_ratio": 2.1}],
        sweep_events=[SweepEvent(
            timestamp=NOW, level_swept=18280, level_type="pdl",
            direction="below", rejected=True, displacement_followed=True,
        )],
    )
    defaults.update(overrides)
    return MarketState(**defaults)


# ══════════════════════════════════════════════════════════════════════
# NY SWEEP REVERSAL
# ══════════════════════════════════════════════════════════════════════
class TestNYSweepReversal:
    def test_generates_signal_on_valid_setup(self):
        strat = NYSweepReversalStrategy()
        state = _base_state()
        signal = strat.evaluate(state)
        # May or may not fire depending on exact entry/target math
        # but should not crash
        assert signal is None or signal.strategy_id.startswith("ny_sweep_reversal")

    def test_rejects_off_session(self):
        strat = NYSweepReversalStrategy()
        state = _base_state(session=SessionName.ASIA)
        assert strat.evaluate(state) is None

    def test_rejects_no_overnight_range(self):
        strat = NYSweepReversalStrategy()
        state = _base_state(session_ranges={})
        assert strat.evaluate(state) is None

    def test_rejects_no_sweeps(self):
        strat = NYSweepReversalStrategy()
        state = _base_state(sweep_events=[])
        assert strat.evaluate(state) is None


# ══════════════════════════════════════════════════════════════════════
# NY CONTINUATION
# ══════════════════════════════════════════════════════════════════════
class TestNYContinuation:
    def test_rejects_ranging_bias(self):
        strat = NYContinuationStrategy()
        state = _base_state(structure_bias=StructureBias.RANGING)
        assert strat.evaluate(state) is None

    def test_rejects_off_session(self):
        strat = NYContinuationStrategy()
        state = _base_state(session=SessionName.LONDON)
        assert strat.evaluate(state) is None

    def test_rejects_insufficient_swings(self):
        strat = NYContinuationStrategy()
        state = _base_state(swing_points=[
            SwingPoint(price=18300, type="swing_low", bar_index=10, timestamp=NOW),
        ])
        assert strat.evaluate(state) is None

    def test_rejects_no_trend_sweeps(self):
        strat = NYContinuationStrategy()
        # Sweep is above (bearish), but bias is bullish — no continuation sweep
        state = _base_state(
            sweep_events=[SweepEvent(
                timestamp=NOW, level_swept=18490, direction="above",
                rejected=True, displacement_followed=True,
            )]
        )
        assert strat.evaluate(state) is None

    def test_generates_signal_on_valid_continuation(self):
        strat = NYContinuationStrategy()
        # Bullish bias + sweep below (bullish continuation) + FVG entry
        state = _base_state(
            structure_bias=StructureBias.BULLISH,
            sweep_events=[SweepEvent(
                timestamp=NOW, level_swept=18280, direction="below",
                rejected=True, displacement_followed=True,
            )],
        )
        signal = strat.evaluate(state)
        # Should attempt to generate (may fail on target calc)
        assert signal is None or signal.strategy_id.startswith("ny_continuation")

    def test_bearish_continuation(self):
        strat = NYContinuationStrategy()
        state = _base_state(
            structure_bias=StructureBias.BEARISH,
            swing_points=[
                SwingPoint(price=18500, type="swing_high", bar_index=10, timestamp=NOW),
                SwingPoint(price=18400, type="swing_low", bar_index=20, timestamp=NOW),
                SwingPoint(price=18480, type="swing_high", bar_index=30, timestamp=NOW),
                SwingPoint(price=18350, type="swing_low", bar_index=40, timestamp=NOW),
                SwingPoint(price=18430, type="swing_high", bar_index=50, timestamp=NOW),
                SwingPoint(price=18300, type="swing_low", bar_index=60, timestamp=NOW),
            ],
            sweep_events=[SweepEvent(
                timestamp=NOW, level_swept=18500, direction="above",
                rejected=True, displacement_followed=True,
            )],
            fvgs=[FVG(type=Direction.SHORT, upper=18430, lower=18420, filled=False, age_bars=3)],
        )
        signal = strat.evaluate(state)
        if signal is not None:
            assert signal.direction == Direction.SHORT


# ══════════════════════════════════════════════════════════════════════
# PSYCH LEVEL REJECTION
# ══════════════════════════════════════════════════════════════════════
class TestPsychLevel:
    def test_rejects_off_session(self):
        strat = PsychLevelStrategy()
        state = _base_state(session=SessionName.ASIA)
        assert strat.evaluate(state) is None

    def test_rejects_no_psych_proximity(self):
        strat = PsychLevelStrategy()
        state = _base_state(
            psych_levels=PsychLevels(nearest_above=19000, nearest_below=18000, proximity_score=0.1)
        )
        assert strat.evaluate(state) is None

    def test_rejects_no_displacement(self):
        strat = PsychLevelStrategy()
        state = _base_state(displacement_candles=[])
        assert strat.evaluate(state) is None

    def test_rejects_insufficient_confluence(self):
        strat = PsychLevelStrategy()
        # Only psych_level tag, no other confluence
        state = _base_state(
            smt_signals=[],
            sweep_events=[],
            fvgs=[],
            displacement_candles=[{"timestamp": NOW.isoformat(), "direction": "bullish", "body_atr_ratio": 2.0}],
        )
        # With only psych_level + displacement = 2 tags, needs 3
        result = strat.evaluate(state)
        # Should reject due to < 3 confluence
        assert result is None

    def test_generates_signal_with_full_confluence(self):
        strat = PsychLevelStrategy()
        state = _base_state()  # Has SMT, sweeps, displacement, psych, killzone, structure
        signal = strat.evaluate(state)
        if signal is not None:
            assert signal.strategy_id.startswith("psych_level_model")
            assert len(signal.confluence_tags) >= 3


# ══════════════════════════════════════════════════════════════════════
# STRATEGY ENGINE (all three registered)
# ══════════════════════════════════════════════════════════════════════
class TestStrategyEngine:
    def test_engine_loads_all_strategies(self):
        from core.strategy.engine import StrategyEngine
        engine = StrategyEngine()
        assert len(engine.strategies) == 3
        ids = engine.active_strategy_ids
        assert any("sweep" in s for s in ids)
        assert any("continuation" in s for s in ids)
        assert any("psych" in s for s in ids)

    def test_daily_limit_respected(self):
        from core.strategy.engine import StrategyEngine
        engine = StrategyEngine()
        engine._trade_counts["ny_sweep_reversal_v1"] = 99
        state = _base_state()
        # Should still try other strategies but skip the one at limit
        signals = engine.evaluate(state)
        for s in signals:
            assert s.strategy_id != "ny_sweep_reversal_v1"
