"""Swing Point Detection — identifies swing highs, swing lows, BOS, and CHoCH.

This is the foundation for all structure-based logic. Every other detector
depends on having clean swing points.
"""

from __future__ import annotations

from typing import Optional

import structlog
import yaml

from core.models import Candle, StructureBias, SwingPoint

logger = structlog.get_logger(__name__)


class SwingDetector:
    """Detects swing highs and lows from candle data."""

    def __init__(self, config_path: str = "config/structure.yaml"):
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        swing_cfg = cfg["swing_detection"]
        self.lookback = swing_cfg["lookback_bars"]
        self.min_distance_atr = swing_cfg["min_swing_distance_atr"]
        self.bos_mode = swing_cfg.get("bos_confirmation", "close")

    def detect_swings(self, candles: list[Candle], atr: float) -> list[SwingPoint]:
        """Find all swing highs and swing lows in the candle series.

        A swing high at index i requires:
          candles[i].high > all highs in [i-lookback, i+lookback] (excluding i)
        A swing low at index i requires:
          candles[i].low < all lows in [i-lookback, i+lookback] (excluding i)

        Minimum distance filter: swing must differ from prior swing by min_distance_atr * ATR.
        """
        if len(candles) < (2 * self.lookback + 1):
            return []

        swings: list[SwingPoint] = []
        min_distance = self.min_distance_atr * atr if atr > 0 else 0

        for i in range(self.lookback, len(candles) - self.lookback):
            window_highs = [
                candles[j].high
                for j in range(i - self.lookback, i + self.lookback + 1)
                if j != i
            ]
            window_lows = [
                candles[j].low
                for j in range(i - self.lookback, i + self.lookback + 1)
                if j != i
            ]

            is_swing_high = candles[i].high > max(window_highs)
            is_swing_low = candles[i].low < min(window_lows)

            if is_swing_high:
                price = candles[i].high
                if self._passes_distance_filter(swings, price, min_distance):
                    swings.append(SwingPoint(
                        price=price,
                        type="swing_high",
                        bar_index=i,
                        timestamp=candles[i].timestamp,
                        broken=False,
                    ))

            if is_swing_low:
                price = candles[i].low
                if self._passes_distance_filter(swings, price, min_distance):
                    swings.append(SwingPoint(
                        price=price,
                        type="swing_low",
                        bar_index=i,
                        timestamp=candles[i].timestamp,
                        broken=False,
                    ))

        return swings

    def _passes_distance_filter(
        self, existing: list[SwingPoint], new_price: float, min_distance: float
    ) -> bool:
        """Ensure new swing is far enough from the most recent swing of same type."""
        if not existing or min_distance <= 0:
            return True
        last = existing[-1]
        return abs(new_price - last.price) >= min_distance

    def mark_broken_swings(
        self, swings: list[SwingPoint], candles: list[Candle]
    ) -> list[SwingPoint]:
        """Mark swings as broken if price has traded through them.

        Uses close-based confirmation by default (configurable).
        """
        for swing in swings:
            for candle in candles[swing.bar_index + 1:]:
                if swing.type == "swing_high":
                    check = candle.close if self.bos_mode == "close" else candle.high
                    if check > swing.price:
                        swing.broken = True
                        break
                elif swing.type == "swing_low":
                    check = candle.close if self.bos_mode == "close" else candle.low
                    if check < swing.price:
                        swing.broken = True
                        break
        return swings

    def determine_bias(self, swings: list[SwingPoint]) -> StructureBias:
        """Determine market structure bias from swing sequence.

        Bullish: higher highs + higher lows
        Bearish: lower highs + lower lows
        Ranging: mixed
        """
        if len(swings) < 4:
            return StructureBias.RANGING

        recent = swings[-4:]
        highs = [s for s in recent if s.type == "swing_high"]
        lows = [s for s in recent if s.type == "swing_low"]

        if len(highs) < 2 or len(lows) < 2:
            return StructureBias.RANGING

        hh = highs[-1].price > highs[-2].price  # Higher high
        hl = lows[-1].price > lows[-2].price     # Higher low
        lh = highs[-1].price < highs[-2].price   # Lower high
        ll = lows[-1].price < lows[-2].price     # Lower low

        if hh and hl:
            return StructureBias.BULLISH
        elif lh and ll:
            return StructureBias.BEARISH
        else:
            return StructureBias.RANGING

    def detect_bos_choch(
        self, swings: list[SwingPoint], bias: StructureBias
    ) -> Optional[str]:
        """Detect Break of Structure or Change of Character.

        BOS: broken swing in the direction of current bias
        CHoCH: broken swing AGAINST the direction of current bias
        """
        if len(swings) < 2:
            return None

        last_broken = None
        for s in reversed(swings):
            if s.broken:
                last_broken = s
                break

        if last_broken is None:
            return None

        if bias == StructureBias.BULLISH:
            if last_broken.type == "swing_high":
                return "bos_bullish"  # Break above high = continuation
            elif last_broken.type == "swing_low":
                return "choch_bearish"  # Break below low = character change
        elif bias == StructureBias.BEARISH:
            if last_broken.type == "swing_low":
                return "bos_bearish"
            elif last_broken.type == "swing_high":
                return "choch_bullish"

        return None
