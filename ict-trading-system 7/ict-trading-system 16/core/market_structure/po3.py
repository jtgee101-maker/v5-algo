"""Power of 3 (PO3) Sequence Detector.

Identifies the accumulation → manipulation → distribution pattern
within a trading session using a state machine.
"""

from __future__ import annotations

from typing import Optional

import structlog
import yaml

from core.models import Candle, Direction, PO3Phase, PO3State, PriceRange

logger = structlog.get_logger(__name__)


class PO3Detector:
    """State machine for detecting Power of 3 sequences."""

    def __init__(self, config_path: str = "config/structure.yaml"):
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        po3_cfg = cfg["po3"]
        self.accum_max_range_atr_pct = po3_cfg["accumulation_max_range_atr_pct"]
        self.manip_min_sweep_atr = po3_cfg["manipulation_min_sweep_atr"]
        self.dist_min_expansion_atr = po3_cfg["distribution_min_expansion_atr"]
        self.max_accumulation_bars = po3_cfg.get("max_accumulation_bars", 60)
        self.max_manipulation_bars = po3_cfg.get("max_manipulation_bars", 15)

        # State
        self._phase = PO3Phase.IDLE
        self._accum_range: Optional[PriceRange] = None
        self._manip_extreme: Optional[float] = None
        self._manip_direction: Optional[str] = None
        self._accum_start_bar: int = 0
        self._manip_start_bar: int = 0

    def reset(self) -> None:
        """Reset state machine for a new session."""
        self._phase = PO3Phase.IDLE
        self._accum_range = None
        self._manip_extreme = None
        self._manip_direction = None
        self._accum_start_bar = 0
        self._manip_start_bar = 0

    def evaluate(
        self,
        candles: list[Candle],
        atr: float,
        pre_ny_candles: Optional[list[Candle]] = None,
    ) -> PO3State:
        """Run PO3 detection on candle data.

        Flow:
        1. IDLE → detect tight accumulation range in pre-NY data
        2. ACCUMULATING → wait for sweep beyond range
        3. MANIPULATED → wait for expansion in opposite direction
        4. DISTRIBUTING → expansion confirmed
        5. COMPLETE → full sequence identified
        """
        if atr <= 0:
            return PO3State(phase=PO3Phase.IDLE)

        # Phase 1: Look for accumulation in pre-NY candles
        if self._phase == PO3Phase.IDLE:
            source = pre_ny_candles if pre_ny_candles else candles
            if source:
                self._try_find_accumulation(source, atr)

        # Phase 2: Look for manipulation sweep
        if self._phase == PO3Phase.ACCUMULATING and self._accum_range:
            self._try_find_manipulation(candles, atr)

        # Phase 3: Look for distribution expansion
        if self._phase == PO3Phase.MANIPULATED:
            self._try_find_distribution(candles, atr)

        return self._build_state()

    def _try_find_accumulation(self, candles: list[Candle], atr: float) -> None:
        """Identify a tight consolidation range."""
        if len(candles) < 5:
            return

        # Use most recent chunk as potential accumulation
        window_size = min(len(candles), self.max_accumulation_bars)
        window = candles[-window_size:]

        high = max(c.high for c in window)
        low = min(c.low for c in window)
        range_size = high - low
        range_atr_pct = range_size / atr if atr > 0 else 999

        if range_atr_pct <= self.accum_max_range_atr_pct:
            self._phase = PO3Phase.ACCUMULATING
            self._accum_range = PriceRange(
                high=high, low=low,
                mid=(high + low) / 2,
                range_atr_ratio=round(range_atr_pct, 4),
            )
            self._accum_start_bar = len(candles) - window_size
            logger.debug("po3.accumulation_found", high=high, low=low, range_atr=range_atr_pct)

    def _try_find_manipulation(self, candles: list[Candle], atr: float) -> None:
        """Detect price sweeping beyond the accumulation range."""
        assert self._accum_range is not None

        sweep_threshold = self.manip_min_sweep_atr * atr

        for i, candle in enumerate(candles):
            # Sweep above accumulation high
            if candle.high > self._accum_range.high + sweep_threshold:
                self._phase = PO3Phase.MANIPULATED
                self._manip_extreme = candle.high
                self._manip_direction = "above"
                self._manip_start_bar = i
                logger.debug("po3.manipulation_above", extreme=candle.high)
                return

            # Sweep below accumulation low
            if candle.low < self._accum_range.low - sweep_threshold:
                self._phase = PO3Phase.MANIPULATED
                self._manip_extreme = candle.low
                self._manip_direction = "below"
                self._manip_start_bar = i
                logger.debug("po3.manipulation_below", extreme=candle.low)
                return

        # Check if too many bars have passed without manipulation
        if len(candles) - self._accum_start_bar > self.max_accumulation_bars * 2:
            self.reset()

    def _try_find_distribution(self, candles: list[Candle], atr: float) -> None:
        """Detect expansion in the opposite direction of manipulation."""
        assert self._accum_range is not None
        expansion_threshold = self.dist_min_expansion_atr * atr

        recent = candles[self._manip_start_bar:]
        if not recent:
            return

        # Check timeout
        if len(recent) > self.max_manipulation_bars * 3:
            self.reset()
            return

        if self._manip_direction == "above":
            # Manipulation was above → expect distribution downward
            min_close = min(c.close for c in recent[-10:]) if len(recent) >= 10 else min(c.close for c in recent)
            if self._accum_range.mid - min_close >= expansion_threshold:
                self._phase = PO3Phase.DISTRIBUTING
                logger.debug("po3.distributing_bearish")
        elif self._manip_direction == "below":
            # Manipulation was below → expect distribution upward
            max_close = max(c.close for c in recent[-10:]) if len(recent) >= 10 else max(c.close for c in recent)
            if max_close - self._accum_range.mid >= expansion_threshold:
                self._phase = PO3Phase.DISTRIBUTING
                logger.debug("po3.distributing_bullish")

    def _build_state(self) -> PO3State:
        """Build the output state object."""
        confidence_map = {
            PO3Phase.IDLE: 0.0,
            PO3Phase.ACCUMULATING: 0.2,
            PO3Phase.MANIPULATED: 0.5,
            PO3Phase.DISTRIBUTING: 0.8,
            PO3Phase.COMPLETE: 1.0,
        }

        dist_bias = None
        if self._manip_direction == "above":
            dist_bias = Direction.SHORT
        elif self._manip_direction == "below":
            dist_bias = Direction.LONG

        return PO3State(
            phase=self._phase,
            accumulation_range=self._accum_range,
            manipulation_extreme=self._manip_extreme,
            distribution_bias=dist_bias,
            confidence=confidence_map.get(self._phase, 0.0),
        )
