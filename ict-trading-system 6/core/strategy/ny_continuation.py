"""NY Continuation After Sweep Strategy — V1.

Detects liquidity runs in the trend direction, confirms continuation (not reversal),
then enters on pullback into imbalance/structure shift proxy. Best on trend days.

Rule-based. No LLM discretion at runtime.
"""

from __future__ import annotations

from typing import Optional

import structlog
import yaml

from core.models import (
    Direction, FVG, MarketState, Regime, SessionName,
    StructureBias, SweepEvent, Target, TradeSignal,
)
from core.strategy.scorer import ConfidenceScorer

logger = structlog.get_logger(__name__)


class NYContinuationStrategy:
    """NY Continuation After Sweep — V1.

    Entry logic:
    1. Structure bias must be clear (bullish or bearish, not ranging)
    2. Break of structure in trend direction (no CHoCH against)
    3. Liquidity sweep in trend direction confirms continuation
    4. Pullback into FVG or structure level
    5. Stop below/above pullback structure
    6. Targets: next external liquidity, daily range extension, runner
    """

    def __init__(self, config_path: str = "config/strategy.yaml"):
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        self.global_cfg = cfg["global"]
        self.strat_cfg = cfg["strategies"]["ny_continuation"]
        self.scorer = ConfidenceScorer(config_path)

        self.version = self.strat_cfg["version"]
        self.strategy_id = f"ny_continuation_{self.version}"
        self.min_rr = self.strat_cfg["min_reward_risk"]
        self.min_confidence = self.strat_cfg["min_confidence"]
        self.rules = self.strat_cfg["rules"]

    def evaluate(self, state: MarketState) -> Optional[TradeSignal]:
        # Gate 1: NY session
        if state.session not in (SessionName.NY, SessionName.NY_KILLZONE):
            return None

        # Gate 2: Clear directional bias (not ranging)
        if state.structure_bias == StructureBias.RANGING:
            return None

        direction = Direction.LONG if state.structure_bias == StructureBias.BULLISH else Direction.SHORT

        # Gate 3: Need swings confirming trend
        min_swings = self.rules["trend_confirmation"]["min_trend_swings"]
        if direction == Direction.LONG:
            confirming = [s for s in state.swing_points if s.type == "swing_low" and not s.broken]
        else:
            confirming = [s for s in state.swing_points if s.type == "swing_high" and not s.broken]
        if len(confirming) < min_swings:
            return None

        # Gate 4: Sweep in trend direction (continuation, not reversal)
        trend_sweeps = self._find_trend_sweeps(state, direction)
        if not trend_sweeps:
            return None

        # Gate 5: Pullback into FVG or structure
        entry_price, fvg = self._find_pullback_entry(state, direction)
        if entry_price is None:
            return None

        # Stop at pullback structure
        stop_price = self._calculate_stop(state, direction, entry_price)
        if stop_price is None:
            return None

        # Targets
        targets = self._calculate_targets(state, direction, entry_price)
        if not targets:
            return None

        # R:R check
        risk_dist = abs(entry_price - stop_price)
        if risk_dist <= 0:
            return None
        reward_dist = abs(targets[0].price - entry_price)
        rr = reward_dist / risk_dist
        if rr < self.min_rr:
            return None

        # Confidence
        confluence_tags = self._build_tags(state, trend_sweeps, fvg)
        composite, breakdown = self.scorer.score(
            p_setup=self._score_setup(state, trend_sweeps),
            ev_ratio=min(1.0, rr / 3.0),
            regime_confidence=0.8 if state.structure_bias != StructureBias.RANGING else 0.3,
            exec_confidence=0.7,
            structural_clarity=self._score_clarity(state),
            correlation_confirm=0.7 if state.smt_signals else 0.3,
            session_timing=0.9 if state.session == SessionName.NY_KILLZONE else 0.6,
        )

        if composite < self.min_confidence:
            return None

        return TradeSignal(
            timestamp=state.timestamp,
            strategy_id=self.strategy_id,
            symbol=state.symbol,
            direction=direction,
            confidence=composite,
            confidence_breakdown=breakdown,
            entry_type="limit",
            entry_price=entry_price,
            stop_price=stop_price,
            targets=targets,
            invalidation=f"choch_against_{direction.value}",
            reward_risk=round(rr, 2),
            confluence_tags=confluence_tags,
            regime=Regime.TREND_DAY,
            session=state.session.value,
            market_state_ref=f"market_state_{state.symbol}_{state.timestamp.strftime('%Y%m%dT%H%M%S')}.json",
        )

    def _find_trend_sweeps(self, state: MarketState, direction: Direction) -> list[SweepEvent]:
        """Find sweeps that confirm trend continuation."""
        if direction == Direction.LONG:
            # Bullish continuation: sweep below a low, then price recovers
            return [s for s in state.sweep_events
                    if s.direction == "below" and s.rejected and s.displacement_followed]
        else:
            return [s for s in state.sweep_events
                    if s.direction == "above" and s.rejected and s.displacement_followed]

    def _find_pullback_entry(self, state: MarketState, direction: Direction) -> tuple[Optional[float], Optional[FVG]]:
        """Find entry at pullback into FVG or structure."""
        matching_fvgs = [f for f in state.fvgs if not f.filled and f.type == direction and f.age_bars < 30]
        if matching_fvgs:
            fvg = matching_fvgs[-1]
            entry = fvg.upper if direction == Direction.LONG else fvg.lower
            return entry, fvg

        # Fallback: use nearest swing level as structure retest
        if direction == Direction.LONG:
            recent_lows = [s for s in state.swing_points if s.type == "swing_low" and not s.broken]
            if recent_lows:
                return recent_lows[-1].price, None
        else:
            recent_highs = [s for s in state.swing_points if s.type == "swing_high" and not s.broken]
            if recent_highs:
                return recent_highs[-1].price, None

        return None, None

    def _calculate_stop(self, state: MarketState, direction: Direction, entry: float) -> Optional[float]:
        """Stop below/above the pullback structure."""
        buffer = self.rules["stop"]["buffer_ticks"] * 0.01
        if direction == Direction.LONG:
            lows = [s.price for s in state.swing_points if s.type == "swing_low" and s.price < entry]
            if lows:
                return min(lows[-2:]) - buffer
        else:
            highs = [s.price for s in state.swing_points if s.type == "swing_high" and s.price > entry]
            if highs:
                return max(highs[-2:]) + buffer
        return None

    def _calculate_targets(self, state: MarketState, direction: Direction, entry: float) -> list[Target]:
        targets: list[Target] = []

        # Target 1: Next external liquidity (40% close)
        ext_pools = []
        for pool in state.liquidity_pools:
            if direction == Direction.LONG and pool.price > entry and not pool.swept:
                ext_pools.append(pool)
            elif direction == Direction.SHORT and pool.price < entry and not pool.swept:
                ext_pools.append(pool)

        if ext_pools:
            nearest = min(ext_pools, key=lambda p: abs(p.price - entry))
            targets.append(Target(price=nearest.price, pct_close=0.40))

        # Target 2: Range extension (35%)
        overnight = state.session_ranges.get("overnight")
        if overnight:
            rng = overnight.high - overnight.low
            if direction == Direction.LONG:
                targets.append(Target(price=round(entry + rng * 0.618, 5), pct_close=0.35))
            else:
                targets.append(Target(price=round(entry - rng * 0.618, 5), pct_close=0.35))

        # Target 3: Runner (25%)
        if targets:
            dist = abs(targets[0].price - entry)
            ext = entry + dist * 2.0 if direction == Direction.LONG else entry - dist * 2.0
            targets.append(Target(price=round(ext, 5), pct_close=0.25))

        return targets

    def _build_tags(self, state: MarketState, sweeps: list, fvg: Optional[FVG]) -> list[str]:
        tags = ["trend_continuation"]
        if sweeps:
            tags.append("sweep_continuation")
        if fvg:
            tags.append("fvg_entry")
        if state.smt_signals:
            tags.append("smt_aligned")
        if state.psych_levels and state.psych_levels.proximity_score > 0.5:
            tags.append("psych_level_nearby")
        if state.structure_bias == StructureBias.BULLISH:
            tags.append("bullish_bias")
        elif state.structure_bias == StructureBias.BEARISH:
            tags.append("bearish_bias")
        return tags

    def _score_setup(self, state: MarketState, sweeps: list) -> float:
        score = 0.35
        if sweeps:
            score += 0.15
        if state.structure_bias != StructureBias.RANGING:
            score += 0.15
        if len(state.swing_points) >= 6:
            score += 0.1
        if state.fvgs:
            score += 0.1
        if state.smt_signals:
            score += 0.1
        return min(1.0, score)

    def _score_clarity(self, state: MarketState) -> float:
        score = 0.3
        if len(state.swing_points) >= 4:
            score += 0.2
        if len(state.liquidity_pools) >= 3:
            score += 0.15
        if state.fvgs:
            score += 0.15
        if state.structure_bias != StructureBias.RANGING:
            score += 0.2
        return min(1.0, score)
