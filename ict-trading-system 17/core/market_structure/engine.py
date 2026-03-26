"""Market Structure Engine — assembles all detectors into a unified MarketState.

This is Engine A. It consumes candle data and outputs a complete MarketState
with all labeled features: session ranges, liquidity pools, swing points,
SMT signals, PO3 state, psych levels, FVGs, displacement, and sweep events.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import structlog
import yaml

from core.models import (
    Candle,
    MarketState,
    PriceRange,
    SessionName,
)
from core.market_structure.session import SessionDetector
from core.market_structure.swings import SwingDetector
from core.market_structure.liquidity import LiquidityMapper
from core.market_structure.psych_levels import PsychLevelEngine
from core.market_structure.displacement import DisplacementDetector
from core.market_structure.smt import SMTDetector
from core.market_structure.po3 import PO3Detector

logger = structlog.get_logger(__name__)


def calculate_atr(candles: list[Candle], period: int = 14) -> float:
    """Calculate Average True Range from candle data."""
    if len(candles) < 2:
        return 0.0

    trs: list[float] = []
    for i in range(1, len(candles)):
        high_low = candles[i].high - candles[i].low
        high_prev_close = abs(candles[i].high - candles[i - 1].close)
        low_prev_close = abs(candles[i].low - candles[i - 1].close)
        trs.append(max(high_low, high_prev_close, low_prev_close))

    if not trs:
        return 0.0

    window = trs[-period:] if len(trs) >= period else trs
    return sum(window) / len(window)


class MarketStructureEngine:
    """Assembles all market structure detectors into a unified output.

    Usage:
        engine = MarketStructureEngine()
        state = engine.build_state(
            symbol="NAS100",
            candles_1m=candles,
            prior_day_candles=prior,
            asia_candles=asia,
            weekly_candles=weekly,
        )
    """

    def __init__(self, config_path: str = "config/structure.yaml"):
        self.session_detector = SessionDetector(config_path)
        self.swing_detector = SwingDetector(config_path)
        self.liquidity_mapper = LiquidityMapper(config_path)
        self.psych_engine = PsychLevelEngine(config_path)
        self.displacement_detector = DisplacementDetector(config_path)
        self.smt_detector = SMTDetector(config_path)
        self.po3_detector = PO3Detector(config_path)

        with open(config_path) as f:
            self.config = yaml.safe_load(f)

    def build_state(
        self,
        symbol: str,
        candles_1m: list[Candle],
        prior_day_candles: Optional[list[Candle]] = None,
        asia_candles: Optional[list[Candle]] = None,
        weekly_candles: Optional[list[Candle]] = None,
        pre_ny_candles: Optional[list[Candle]] = None,
        paired_symbol_swings: Optional[list] = None,
        paired_symbol: Optional[str] = None,
        paired_atr: float = 0.0,
        tick_size: float = 0.01,
        utc_now: Optional[datetime] = None,
    ) -> MarketState:
        """Build complete MarketState from candle data and detectors."""
        if utc_now is None:
            utc_now = datetime.now(timezone.utc)

        # Session
        session = self.session_detector.get_active_session(utc_now)

        # ATR
        atr = calculate_atr(candles_1m, period=14)

        # Current price
        current_price = candles_1m[-1].close if candles_1m else 0.0

        # Swing points
        swings = self.swing_detector.detect_swings(candles_1m, atr)
        swings = self.swing_detector.mark_broken_swings(swings, candles_1m)
        bias = self.swing_detector.determine_bias(swings)

        # Session ranges
        session_ranges: dict[str, PriceRange] = {}
        if asia_candles:
            asia_range = self.liquidity_mapper.get_session_range(asia_candles)
            if asia_range:
                session_ranges["asia"] = asia_range

        if pre_ny_candles:
            overnight_range = self.liquidity_mapper.get_session_range(pre_ny_candles)
            if overnight_range:
                session_ranges["overnight"] = overnight_range

        ny_candles = [
            c for c in candles_1m
            if self.session_detector.is_ny_active(c.timestamp)
        ]
        if ny_candles:
            ny_range = self.liquidity_mapper.get_session_range(ny_candles)
            if ny_range:
                session_ranges["ny"] = ny_range

        # Liquidity pools
        ny_open_time = None
        if session in (SessionName.NY, SessionName.NY_KILLZONE):
            try:
                ny_start, _ = self.session_detector.get_session_range_times(SessionName.NY, utc_now)
                ny_open_time = ny_start
            except ValueError:
                pass

        liquidity_pools = self.liquidity_mapper.build_liquidity_map(
            current_candles=candles_1m,
            prior_day_candles=prior_day_candles or [],
            weekly_candles=weekly_candles or [],
            asia_candles=asia_candles or [],
            swings=swings,
            tick_size=tick_size,
            ny_open_time=ny_open_time,
        )

        # Check for sweep events on liquidity levels
        liquidity_pools = self.liquidity_mapper.check_sweep(
            liquidity_pools, candles_1m[-20:] if len(candles_1m) > 20 else candles_1m, tick_size
        )

        # Psychological levels
        psych_levels = None
        if current_price > 0:
            psych_levels = self.psych_engine.get_levels(symbol, current_price, tick_size)

        # Displacement candles and FVGs
        displacements = self.displacement_detector.find_displacement_candles(candles_1m, atr)
        fvgs = self.displacement_detector.find_fvgs(candles_1m, tick_size)
        fvgs = self.displacement_detector.update_fvg_status(fvgs, candles_1m, len(candles_1m))

        # Sweep events from liquidity levels
        level_prices = [p.price for p in liquidity_pools]
        level_types = [p.type.value for p in liquidity_pools]
        sweep_events = self.displacement_detector.detect_sweeps(
            candles_1m[-30:] if len(candles_1m) > 30 else candles_1m,
            level_prices,
            level_types,
        )

        # SMT divergence (if paired data provided)
        smt_signals = []
        if paired_symbol and paired_symbol_swings is not None:
            session_valid = self.session_detector.is_ny_active(utc_now)
            smt_signals = self.smt_detector.detect_divergence(
                symbol_a=symbol,
                swings_a=swings,
                symbol_b=paired_symbol,
                swings_b=paired_symbol_swings,
                atr_a=atr,
                atr_b=paired_atr,
                session_valid=session_valid,
            )

        # Power of 3
        po3_state = self.po3_detector.evaluate(
            candles=candles_1m,
            atr=atr,
            pre_ny_candles=pre_ny_candles,
        )

        state = MarketState(
            timestamp=utc_now,
            symbol=symbol,
            session=session,
            session_ranges=session_ranges,
            liquidity_pools=liquidity_pools,
            structure_bias=bias,
            swing_points=swings,
            smt_signals=smt_signals,
            po3_state=po3_state,
            psych_levels=psych_levels,
            fvgs=fvgs,
            displacement_candles=displacements,
            sweep_events=sweep_events,
        )

        logger.info(
            "market_structure.state_built",
            symbol=symbol,
            session=session,
            bias=bias,
            pools=len(liquidity_pools),
            swings=len(swings),
            fvgs=len(fvgs),
            sweeps=len(sweep_events),
            po3_phase=po3_state.phase,
        )

        return state

    def reset_session_state(self) -> None:
        """Reset stateful detectors for a new session."""
        self.po3_detector.reset()
