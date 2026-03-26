"""Psychological Price Levels — dynamic level grid per symbol.

Builds a grid of round numbers and key levels that attract price action,
then scores proximity of current price to nearest levels.
"""

from __future__ import annotations

import math

import structlog
import yaml

from core.models import PsychLevels

logger = structlog.get_logger(__name__)


class PsychLevelEngine:
    """Generates psychological price level grids per symbol."""

    def __init__(self, config_path: str = "config/structure.yaml"):
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        self.psych_cfg = cfg["psych_levels"]
        self.proximity_ticks = self.psych_cfg.get("proximity_ticks", 10)

    def get_levels(
        self, symbol: str, current_price: float, tick_size: float = 0.01
    ) -> PsychLevels:
        """Find nearest psychological levels above and below current price."""
        granularity = self._get_granularity(symbol)
        big_figure = self._get_big_figure(symbol)

        all_levels = self._generate_levels(current_price, granularity, big_figure)

        below = [l for l in all_levels if l < current_price]
        above = [l for l in all_levels if l > current_price]

        nearest_below = max(below) if below else current_price
        nearest_above = min(above) if above else current_price

        # Proximity score: 1.0 when exactly at a level, 0.0 when far away
        min_distance = min(
            abs(current_price - nearest_below),
            abs(current_price - nearest_above),
        )
        proximity_threshold = self.proximity_ticks * tick_size
        if proximity_threshold > 0:
            proximity_score = max(0.0, 1.0 - (min_distance / proximity_threshold))
        else:
            proximity_score = 0.0

        return PsychLevels(
            nearest_above=nearest_above,
            nearest_below=nearest_below,
            proximity_score=round(proximity_score, 4),
        )

    def _get_granularity(self, symbol: str) -> list[int]:
        """Get the sub-level granularity for a symbol."""
        sym_cfg = self.psych_cfg.get(symbol, {})
        if isinstance(sym_cfg, dict):
            return sym_cfg.get("granularity", [0, 25, 50, 75])
        return [0, 25, 50, 75]

    def _get_big_figure(self, symbol: str) -> int:
        """Get the big figure increment for a symbol."""
        sym_cfg = self.psych_cfg.get(symbol, {})
        if isinstance(sym_cfg, dict):
            return sym_cfg.get("big_figure", 100)
        return 100

    def _generate_levels(
        self, price: float, granularity: list[int], big_figure: int
    ) -> list[float]:
        """Generate a grid of psychological levels around the current price.

        For indices (NAS100=18245): levels at 18000, 18025, 18050, 18075, 18100, ...
        For FX (EURUSD=1.0825): levels at 1.0800, 1.0820, 1.0850, 1.0880, ...
        For crypto (BTC=67500): levels at 67000, 67500, 68000, ...
        """
        levels: list[float] = []

        # Determine the base unit
        if price > 1000:
            # Indices, crypto with high prices
            base = math.floor(price / big_figure) * big_figure
            for offset in range(-2 * big_figure, 3 * big_figure, big_figure):
                base_level = base + offset
                for sub in granularity:
                    level = base_level + sub
                    levels.append(float(level))
        elif price > 10:
            # Mid-range
            base = math.floor(price / big_figure) * big_figure
            for offset in range(-2 * big_figure, 3 * big_figure, big_figure):
                base_level = base + offset
                for sub in granularity:
                    levels.append(float(base_level + sub))
        else:
            # FX pairs (price ~1.08)
            # Granularity is in pips (e.g., [0, 20, 50, 80] means 1.0800, 1.0820, etc.)
            pip_base = math.floor(price * 100) / 100  # e.g., 1.08
            for cent_offset in range(-2, 3):
                cent_level = pip_base + cent_offset * 0.01
                for sub in granularity:
                    level = cent_level + sub * 0.0001  # sub is in pips
                    levels.append(round(level, 5))

        return sorted(set(levels))

    def is_near_psych_level(
        self, price: float, symbol: str, tick_size: float = 0.01
    ) -> bool:
        """Quick check if price is within proximity_ticks of a psych level."""
        levels = self.get_levels(symbol, price, tick_size)
        return levels.proximity_score > 0.5
