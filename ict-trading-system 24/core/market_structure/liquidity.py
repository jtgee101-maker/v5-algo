"""Liquidity Pool Mapper — identifies where resting liquidity sits.

Maps prior day high/low, Asia range, weekly H/L, equal highs/lows,
opening range, and swing clusters into a scored liquidity map.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import structlog
import yaml

from core.models import Candle, LiquidityPool, LiquidityType, PriceRange, SwingPoint

logger = structlog.get_logger(__name__)


class LiquidityMapper:
    """Builds a map of liquidity pools from candle and swing data."""

    def __init__(self, config_path: str = "config/structure.yaml"):
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        liq_cfg = cfg["liquidity"]
        self.equal_tolerance_ticks = liq_cfg["equal_level_tolerance_ticks"]
        self.min_cluster_size = liq_cfg["min_cluster_size"]
        self.opening_range_minutes = liq_cfg["opening_range_minutes"]

    def build_liquidity_map(
        self,
        current_candles: list[Candle],
        prior_day_candles: list[Candle],
        weekly_candles: list[Candle],
        asia_candles: list[Candle],
        swings: list[SwingPoint],
        tick_size: float = 0.01,
        ny_open_time: Optional[datetime] = None,
    ) -> list[LiquidityPool]:
        """Build complete liquidity pool map from all available data."""
        pools: list[LiquidityPool] = []

        # Prior Day High/Low
        if prior_day_candles:
            pdh = max(c.high for c in prior_day_candles)
            pdl = min(c.low for c in prior_day_candles)
            pools.append(LiquidityPool(
                price=pdh, type=LiquidityType.PDH,
                strength_score=0.8, age_bars=len(current_candles),
            ))
            pools.append(LiquidityPool(
                price=pdl, type=LiquidityType.PDL,
                strength_score=0.8, age_bars=len(current_candles),
            ))

        # Asia Range High/Low
        if asia_candles:
            ah = max(c.high for c in asia_candles)
            al = min(c.low for c in asia_candles)
            pools.append(LiquidityPool(
                price=ah, type=LiquidityType.ASIA_HIGH,
                strength_score=0.7, age_bars=len(current_candles),
            ))
            pools.append(LiquidityPool(
                price=al, type=LiquidityType.ASIA_LOW,
                strength_score=0.7, age_bars=len(current_candles),
            ))

        # Weekly High/Low
        if weekly_candles:
            wh = max(c.high for c in weekly_candles)
            wl = min(c.low for c in weekly_candles)
            pools.append(LiquidityPool(
                price=wh, type=LiquidityType.WEEKLY_HIGH,
                strength_score=0.9, age_bars=len(current_candles),
            ))
            pools.append(LiquidityPool(
                price=wl, type=LiquidityType.WEEKLY_LOW,
                strength_score=0.9, age_bars=len(current_candles),
            ))

        # Opening Range (first N minutes of NY)
        if ny_open_time and current_candles:
            or_candles = [
                c for c in current_candles
                if ny_open_time <= c.timestamp
                and (c.timestamp - ny_open_time).total_seconds() <= self.opening_range_minutes * 60
            ]
            if or_candles:
                or_high = max(c.high for c in or_candles)
                or_low = min(c.low for c in or_candles)
                pools.append(LiquidityPool(
                    price=or_high, type=LiquidityType.OR_HIGH,
                    strength_score=0.75,
                ))
                pools.append(LiquidityPool(
                    price=or_low, type=LiquidityType.OR_LOW,
                    strength_score=0.75,
                ))

        # Equal Highs / Equal Lows from swings
        pools.extend(self._find_equal_levels(swings, tick_size))

        # Sort by price
        pools.sort(key=lambda p: p.price)

        logger.debug("liquidity.map_built", pool_count=len(pools))
        return pools

    def _find_equal_levels(
        self, swings: list[SwingPoint], tick_size: float
    ) -> list[LiquidityPool]:
        """Detect clusters of swing highs or lows at similar prices (equal levels)."""
        pools: list[LiquidityPool] = []
        tolerance = self.equal_tolerance_ticks * tick_size

        swing_highs = [s for s in swings if s.type == "swing_high"]
        swing_lows = [s for s in swings if s.type == "swing_low"]

        # Find equal highs
        for cluster in self._cluster_prices([s.price for s in swing_highs], tolerance):
            if len(cluster) >= self.min_cluster_size:
                avg_price = sum(cluster) / len(cluster)
                strength = min(1.0, 0.5 + 0.1 * len(cluster))
                pools.append(LiquidityPool(
                    price=round(avg_price, 6),
                    type=LiquidityType.EQUAL_HIGHS,
                    strength_score=strength,
                ))

        # Find equal lows
        for cluster in self._cluster_prices([s.price for s in swing_lows], tolerance):
            if len(cluster) >= self.min_cluster_size:
                avg_price = sum(cluster) / len(cluster)
                strength = min(1.0, 0.5 + 0.1 * len(cluster))
                pools.append(LiquidityPool(
                    price=round(avg_price, 6),
                    type=LiquidityType.EQUAL_LOWS,
                    strength_score=strength,
                ))

        return pools

    def _cluster_prices(
        self, prices: list[float], tolerance: float
    ) -> list[list[float]]:
        """Group prices that are within tolerance of each other."""
        if not prices:
            return []

        sorted_prices = sorted(prices)
        clusters: list[list[float]] = [[sorted_prices[0]]]

        for price in sorted_prices[1:]:
            if price - clusters[-1][-1] <= tolerance:
                clusters[-1].append(price)
            else:
                clusters.append([price])

        return clusters

    def check_sweep(
        self,
        pools: list[LiquidityPool],
        candles: list[Candle],
        tick_size: float = 0.01,
    ) -> list[LiquidityPool]:
        """Check if any liquidity levels have been swept by recent candles."""
        if not candles:
            return pools

        for pool in pools:
            if pool.swept:
                continue
            for candle in candles:
                # Swept above (for highs)
                if pool.type in (
                    LiquidityType.PDH, LiquidityType.ASIA_HIGH,
                    LiquidityType.WEEKLY_HIGH, LiquidityType.OR_HIGH,
                    LiquidityType.EQUAL_HIGHS,
                ):
                    if candle.high > pool.price and candle.close < pool.price:
                        pool.swept = True
                        pool.swept_timestamp = candle.timestamp
                        break
                # Swept below (for lows)
                elif pool.type in (
                    LiquidityType.PDL, LiquidityType.ASIA_LOW,
                    LiquidityType.WEEKLY_LOW, LiquidityType.OR_LOW,
                    LiquidityType.EQUAL_LOWS,
                ):
                    if candle.low < pool.price and candle.close > pool.price:
                        pool.swept = True
                        pool.swept_timestamp = candle.timestamp
                        break

        return pools

    def get_session_range(self, candles: list[Candle]) -> Optional[PriceRange]:
        """Calculate price range from a set of candles."""
        if not candles:
            return None
        high = max(c.high for c in candles)
        low = min(c.low for c in candles)
        mid = (high + low) / 2
        return PriceRange(high=high, low=low, mid=mid)
