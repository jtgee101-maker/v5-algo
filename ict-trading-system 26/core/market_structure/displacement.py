"""Displacement & Fair Value Gap Detection.

Identifies strong momentum candles (displacement) and the gaps they leave (FVGs).
"""

from __future__ import annotations

import structlog
import yaml

from core.models import Candle, Direction, FVG, SweepEvent

logger = structlog.get_logger(__name__)


class DisplacementDetector:
    """Detects displacement candles and Fair Value Gaps."""

    def __init__(self, config_path: str = "config/structure.yaml"):
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        fvg_cfg = cfg["fvg"]
        self.displacement_min_body_atr = fvg_cfg["displacement_min_body_atr"]
        self.max_age_bars = fvg_cfg["max_age_bars"]
        self.min_gap_size_ticks = fvg_cfg.get("min_gap_size_ticks", 2)

    def find_displacement_candles(
        self, candles: list[Candle], atr: float
    ) -> list[dict]:
        """Find candles with bodies larger than threshold * ATR."""
        displacements = []
        if atr <= 0:
            return displacements

        for candle in candles:
            body = abs(candle.close - candle.open)
            body_atr_ratio = body / atr

            if body_atr_ratio >= self.displacement_min_body_atr:
                direction = "bullish" if candle.close > candle.open else "bearish"
                displacements.append({
                    "timestamp": candle.timestamp,
                    "direction": direction,
                    "body_atr_ratio": round(body_atr_ratio, 3),
                })

        return displacements

    def find_fvgs(
        self, candles: list[Candle], tick_size: float = 0.01
    ) -> list[FVG]:
        """Find Fair Value Gaps — 3-candle patterns with price gaps.

        Bullish FVG: candle[i].high < candle[i+2].low (gap up)
        Bearish FVG: candle[i].low > candle[i+2].high (gap down)
        """
        fvgs: list[FVG] = []
        min_gap = self.min_gap_size_ticks * tick_size

        for i in range(len(candles) - 2):
            c1 = candles[i]
            c3 = candles[i + 2]

            # Bullish FVG: gap between c1 high and c3 low
            if c3.low > c1.high and (c3.low - c1.high) >= min_gap:
                fvgs.append(FVG(
                    type=Direction.LONG,
                    upper=c3.low,
                    lower=c1.high,
                    filled=False,
                    age_bars=0,
                ))

            # Bearish FVG: gap between c1 low and c3 high
            if c1.low > c3.high and (c1.low - c3.high) >= min_gap:
                fvgs.append(FVG(
                    type=Direction.SHORT,
                    upper=c1.low,
                    lower=c3.high,
                    filled=False,
                    age_bars=0,
                ))

        return fvgs

    def update_fvg_status(
        self, fvgs: list[FVG], candles: list[Candle], current_bar_index: int
    ) -> list[FVG]:
        """Update FVGs: mark as filled if price has traded through them, update age."""
        active_fvgs = []
        for fvg in fvgs:
            fvg.age_bars = current_bar_index  # Simplified age tracking

            if fvg.age_bars > self.max_age_bars:
                continue  # Too old, drop

            if not fvg.filled:
                for candle in candles:
                    if fvg.type == Direction.LONG:
                        if candle.low <= fvg.lower:
                            fvg.filled = True
                            break
                    elif fvg.type == Direction.SHORT:
                        if candle.high >= fvg.upper:
                            fvg.filled = True
                            break

            active_fvgs.append(fvg)

        return active_fvgs

    def detect_sweeps(
        self,
        candles: list[Candle],
        levels: list[float],
        level_types: list[str],
    ) -> list[SweepEvent]:
        """Detect sweep events — price pierces a level then reverses.

        A sweep occurs when a candle's wick extends beyond a level
        but the close comes back inside.
        """
        events: list[SweepEvent] = []

        for i, candle in enumerate(candles):
            for level, ltype in zip(levels, level_types):
                # Sweep above: wick above level, close below
                if candle.high > level and candle.close < level:
                    # Check if there's displacement following
                    displacement = False
                    if i + 1 < len(candles):
                        next_body = abs(candles[i + 1].close - candles[i + 1].open)
                        if candles[i + 1].close < candle.close:
                            displacement = True

                    events.append(SweepEvent(
                        timestamp=candle.timestamp,
                        level_swept=level,
                        level_type=ltype,
                        direction="above",
                        rejected=True,
                        displacement_followed=displacement,
                    ))

                # Sweep below: wick below level, close above
                elif candle.low < level and candle.close > level:
                    displacement = False
                    if i + 1 < len(candles):
                        if candles[i + 1].close > candle.close:
                            displacement = True

                    events.append(SweepEvent(
                        timestamp=candle.timestamp,
                        level_swept=level,
                        level_type=ltype,
                        direction="below",
                        rejected=True,
                        displacement_followed=displacement,
                    ))

        return events
