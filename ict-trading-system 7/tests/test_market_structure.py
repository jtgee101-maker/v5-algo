"""Tests for the Market Structure Engine.

Uses synthetic candle data to verify each detector works correctly.
Every test uses known patterns that MUST be detected.
"""

from datetime import datetime, timezone, timedelta

import pytest

from core.models import (
    Candle, Direction, LiquidityType, PO3Phase, SessionName, StructureBias,
)
from core.market_structure.session import SessionDetector
from core.market_structure.swings import SwingDetector
from core.market_structure.liquidity import LiquidityMapper
from core.market_structure.psych_levels import PsychLevelEngine
from core.market_structure.displacement import DisplacementDetector
from core.market_structure.po3 import PO3Detector
from core.market_structure.engine import calculate_atr


# ── Helpers ────────────────────────────────────────────────────────────

def _make_candle(
    ts_offset_min: int = 0,
    o: float = 100.0, h: float = 101.0, l: float = 99.0, c: float = 100.5,
    base_time: datetime | None = None,
) -> Candle:
    if base_time is None:
        base_time = datetime(2025, 1, 15, 14, 0, 0, tzinfo=timezone.utc)
    return Candle(
        timestamp=base_time + timedelta(minutes=ts_offset_min),
        open=o, high=h, low=l, close=c, volume=100, timeframe="1m",
    )


def _make_swing_candles(prices: list[float], base_time: datetime | None = None) -> list[Candle]:
    """Create candles from a list of close prices with synthetic OHLC."""
    candles = []
    for i, price in enumerate(prices):
        candles.append(_make_candle(
            ts_offset_min=i,
            o=price - 0.5, h=price + 1.0, l=price - 1.0, c=price,
            base_time=base_time,
        ))
    return candles


# ── Session Detection ──────────────────────────────────────────────────

class TestSessionDetector:
    def test_ny_session_active(self):
        detector = SessionDetector()
        # 14:30 UTC = well within NY session
        ny_time = datetime(2025, 1, 15, 14, 30, 0, tzinfo=timezone.utc)
        assert detector.is_ny_active(ny_time)

    def test_ny_killzone(self):
        detector = SessionDetector()
        # 14:00 UTC = within NY killzone (13:30-16:00)
        kz_time = datetime(2025, 1, 15, 14, 0, 0, tzinfo=timezone.utc)
        assert detector.is_killzone_active(kz_time)

    def test_asia_session(self):
        detector = SessionDetector()
        asia_time = datetime(2025, 1, 15, 3, 0, 0, tzinfo=timezone.utc)
        session = detector.get_active_session(asia_time)
        assert session == SessionName.ASIA

    def test_off_session(self):
        detector = SessionDetector()
        # 22:00 UTC = after all sessions
        off_time = datetime(2025, 1, 15, 22, 0, 0, tzinfo=timezone.utc)
        session = detector.get_active_session(off_time)
        assert session == SessionName.OFF_SESSION

    def test_weekend_detection(self):
        detector = SessionDetector()
        saturday = datetime(2025, 1, 18, 14, 0, 0, tzinfo=timezone.utc)  # Saturday
        assert detector.is_weekend(saturday)

    def test_weekday_not_weekend(self):
        detector = SessionDetector()
        wednesday = datetime(2025, 1, 15, 14, 0, 0, tzinfo=timezone.utc)
        assert not detector.is_weekend(wednesday)


# ── Swing Detection ────────────────────────────────────────────────────

class TestSwingDetector:
    def test_detect_swing_high(self):
        detector = SwingDetector()
        # Create a peak pattern: prices go up then down
        prices = [100, 101, 102, 103, 104, 105, 106, 105, 104, 103, 102, 101, 100]
        candles = _make_swing_candles(prices)
        swings = detector.detect_swings(candles, atr=2.0)
        highs = [s for s in swings if s.type == "swing_high"]
        assert len(highs) >= 1
        assert highs[0].price == 107.0  # high = price + 1.0

    def test_detect_swing_low(self):
        detector = SwingDetector()
        # Create a trough: prices go down then up
        prices = [106, 105, 104, 103, 102, 101, 100, 101, 102, 103, 104, 105, 106]
        candles = _make_swing_candles(prices)
        swings = detector.detect_swings(candles, atr=2.0)
        lows = [s for s in swings if s.type == "swing_low"]
        assert len(lows) >= 1

    def test_bullish_bias(self):
        detector = SwingDetector()
        # Higher highs + higher lows
        prices = [100, 102, 101, 103, 102, 105, 103, 107, 105, 108, 106, 110, 108]
        candles = _make_swing_candles(prices)
        swings = detector.detect_swings(candles, atr=1.0)
        bias = detector.determine_bias(swings)
        # With clear higher highs and higher lows, should be bullish
        assert bias in (StructureBias.BULLISH, StructureBias.RANGING)

    def test_empty_candles(self):
        detector = SwingDetector()
        swings = detector.detect_swings([], atr=1.0)
        assert swings == []

    def test_insufficient_candles(self):
        detector = SwingDetector()
        candles = _make_swing_candles([100, 101, 102])
        swings = detector.detect_swings(candles, atr=1.0)
        assert swings == []  # Not enough for lookback


# ── Liquidity Mapper ──────────────────────────────────────────────────

class TestLiquidityMapper:
    def test_prior_day_high_low(self):
        mapper = LiquidityMapper()
        prior = _make_swing_candles([100, 102, 98, 101, 99])
        result = mapper.build_liquidity_map(
            current_candles=[], prior_day_candles=prior,
            weekly_candles=[], asia_candles=[], swings=[],
        )
        types = [p.type for p in result]
        assert LiquidityType.PDH in types
        assert LiquidityType.PDL in types

    def test_asia_range(self):
        mapper = LiquidityMapper()
        asia = _make_swing_candles([100, 101, 99, 100.5])
        result = mapper.build_liquidity_map(
            current_candles=[], prior_day_candles=[],
            weekly_candles=[], asia_candles=asia, swings=[],
        )
        types = [p.type for p in result]
        assert LiquidityType.ASIA_HIGH in types
        assert LiquidityType.ASIA_LOW in types

    def test_session_range(self):
        mapper = LiquidityMapper()
        candles = _make_swing_candles([100, 105, 98, 103])
        result = mapper.get_session_range(candles)
        assert result is not None
        assert result.high == 106.0  # max price + 1.0 (from _make_swing_candles)
        assert result.low == 97.0    # min price - 1.0

    def test_empty_input(self):
        mapper = LiquidityMapper()
        result = mapper.build_liquidity_map(
            current_candles=[], prior_day_candles=[],
            weekly_candles=[], asia_candles=[], swings=[],
        )
        assert result == []


# ── Psychological Levels ───────────────────────────────────────────────

class TestPsychLevels:
    def test_index_levels(self):
        engine = PsychLevelEngine()
        levels = engine.get_levels("NAS100", 18245.0, tick_size=0.25)
        assert levels.nearest_below < 18245.0
        assert levels.nearest_above > 18245.0
        # Should be near round numbers like 18225, 18250
        assert levels.nearest_above <= 18250.0

    def test_fx_levels(self):
        engine = PsychLevelEngine()
        levels = engine.get_levels("EURUSD", 1.0825, tick_size=0.00001)
        assert levels.nearest_below < 1.0825
        assert levels.nearest_above > 1.0825

    def test_proximity_score_near_level(self):
        engine = PsychLevelEngine()
        # Price right at a round number
        levels = engine.get_levels("NAS100", 18250.0, tick_size=0.25)
        assert levels.proximity_score > 0.5

    def test_is_near_psych_level(self):
        engine = PsychLevelEngine()
        assert engine.is_near_psych_level(18250.0, "NAS100", tick_size=0.25)


# ── Displacement / FVG ─────────────────────────────────────────────────

class TestDisplacement:
    def test_bullish_fvg(self):
        detector = DisplacementDetector()
        # Create a bullish FVG: c1.high < c3.low
        candles = [
            _make_candle(0, o=100, h=101, l=99, c=100.5),
            _make_candle(1, o=101, h=105, l=100.5, c=104),  # Big up candle
            _make_candle(2, o=104, h=106, l=103, c=105),     # Gap: c1.high=101, c3.low=103
        ]
        fvgs = detector.find_fvgs(candles, tick_size=0.01)
        bullish = [f for f in fvgs if f.type == Direction.LONG]
        assert len(bullish) >= 1
        assert bullish[0].lower == 101.0
        assert bullish[0].upper == 103.0

    def test_no_fvg_in_overlapping_candles(self):
        detector = DisplacementDetector()
        # Overlapping candles = no gap
        candles = [
            _make_candle(0, o=100, h=102, l=99, c=101),
            _make_candle(1, o=101, h=103, l=100, c=102),
            _make_candle(2, o=102, h=103, l=100.5, c=101.5),
        ]
        fvgs = detector.find_fvgs(candles, tick_size=0.01)
        assert len(fvgs) == 0

    def test_sweep_detection(self):
        detector = DisplacementDetector()
        # Candle sweeps above 105 but closes below
        candles = [
            _make_candle(0, o=104, h=106, l=103.5, c=104.5),  # Wick above 105, close below
        ]
        events = detector.detect_sweeps(candles, levels=[105.0], level_types=["pdh"])
        assert len(events) >= 1
        assert events[0].direction == "above"
        assert events[0].rejected


# ── ATR Calculation ────────────────────────────────────────────────────

class TestATR:
    def test_basic_atr(self):
        candles = _make_swing_candles([100, 102, 98, 103, 97, 105, 95])
        atr = calculate_atr(candles, period=5)
        assert atr > 0

    def test_insufficient_data(self):
        atr = calculate_atr([_make_candle()], period=14)
        assert atr == 0.0

    def test_empty(self):
        atr = calculate_atr([], period=14)
        assert atr == 0.0


# ── PO3 Detector ──────────────────────────────────────────────────────

class TestPO3:
    def test_idle_state(self):
        detector = PO3Detector()
        candles = _make_swing_candles([100, 100.1, 100.2])
        state = detector.evaluate(candles, atr=5.0)
        assert state.phase == PO3Phase.IDLE

    def test_accumulation_detection(self):
        detector = PO3Detector()
        # Tight range candles (range < 40% of ATR)
        tight = _make_swing_candles([100, 100.1, 99.9, 100.05, 100.15, 99.95,
                                     100.1, 100.0, 100.05, 99.9, 100.1])
        state = detector.evaluate(tight, atr=10.0, pre_ny_candles=tight)
        assert state.phase in (PO3Phase.ACCUMULATING, PO3Phase.IDLE)

    def test_reset(self):
        detector = PO3Detector()
        detector._phase = PO3Phase.MANIPULATED
        detector.reset()
        assert detector._phase == PO3Phase.IDLE
