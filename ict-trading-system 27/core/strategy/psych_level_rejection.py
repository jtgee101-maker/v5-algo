"""Psychological Level Rejection / Break Strategy — V1.

High-precision strategy focused on round numbers and session key levels.
Requires 3+ confluence factors. Tighter stops, higher confidence threshold.

Rule-based. No LLM discretion at runtime.
"""

from __future__ import annotations

from typing import Optional

import structlog
import yaml

from core.models import (
    Direction, MarketState, Regime, SessionName,
    StructureBias, Target, TradeSignal,
)
from core.strategy.scorer import ConfidenceScorer

logger = structlog.get_logger(__name__)


class PsychLevelStrategy:
    """Psych Level Rejection/Break — V1.

    Entry logic:
    1. Price within proximity of a psychological level
    2. Rejection or break with displacement
    3. Minimum 3 confluence factors: SMT, liquidity, displacement, session, structure
    4. Tighter stop (half ATR)
    5. Targets: next psych level, session range, runner
    """

    def __init__(self, config_path: str = "config/strategy.yaml"):
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        self.global_cfg = cfg["global"]
        self.strat_cfg = cfg["strategies"]["psych_level_model"]
        self.scorer = ConfidenceScorer(config_path)

        self.version = self.strat_cfg["version"]
        self.strategy_id = f"psych_level_model_{self.version}"
        self.min_rr = self.strat_cfg["min_reward_risk"]
        self.min_confidence = self.strat_cfg["min_confidence"]
        self.rules = self.strat_cfg["rules"]

    def evaluate(self, state: MarketState) -> Optional[TradeSignal]:
        # Gate 1: NY session
        if state.session not in (SessionName.NY, SessionName.NY_KILLZONE):
            return None

        # Gate 2: Must be near a psychological level
        if state.psych_levels is None or state.psych_levels.proximity_score < 0.5:
            return None

        # Gate 3: Must have displacement (strong move at/near the level)
        if not state.displacement_candles:
            return None

        # Gate 4: Determine direction from displacement + level interaction
        direction = self._determine_direction(state)
        if direction is None:
            return None

        # Gate 5: Confluence count >= 3
        confluence_tags = self._build_confluence(state, direction)
        if len(confluence_tags) < self.rules["confluence"]["min_confluence_count"]:
            return None

        # Entry at the psych level retest
        entry_price = self._calculate_entry(state, direction)
        if entry_price is None:
            return None

        # Tighter stop
        stop_price = self._calculate_stop(state, direction, entry_price)
        if stop_price is None:
            return None

        # Targets
        targets = self._calculate_targets(state, direction, entry_price)
        if not targets:
            return None

        # R:R
        risk_dist = abs(entry_price - stop_price)
        if risk_dist <= 0:
            return None
        reward_dist = abs(targets[0].price - entry_price)
        rr = reward_dist / risk_dist
        if rr < self.min_rr:
            return None

        # Confidence score
        composite, breakdown = self.scorer.score(
            p_setup=self._score_setup(state, confluence_tags),
            ev_ratio=min(1.0, rr / 5.0),
            regime_confidence=0.7,
            exec_confidence=0.7,
            structural_clarity=self._score_clarity(state),
            correlation_confirm=0.8 if any("smt" in t for t in confluence_tags) else 0.3,
            session_timing=0.9 if state.session == SessionName.NY_KILLZONE else 0.5,
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
            invalidation=f"close_through_psych_level",
            reward_risk=round(rr, 2),
            confluence_tags=confluence_tags,
            regime=Regime.UNKNOWN,
            session=state.session.value,
            market_state_ref=f"market_state_{state.symbol}_{state.timestamp.strftime('%Y%m%dT%H%M%S')}.json",
        )

    def _determine_direction(self, state: MarketState) -> Optional[Direction]:
        """Determine direction from displacement near psych level."""
        if not state.displacement_candles:
            return None

        last_disp = state.displacement_candles[-1]
        disp_dir = last_disp.get("direction", "")

        # If sweep happened near the psych level → trade opposite (rejection)
        recent_sweeps_at_level = [
            s for s in state.sweep_events
            if s.rejected and state.psych_levels
            and abs(s.level_swept - state.psych_levels.nearest_above) < 20
            or (state.psych_levels and abs(s.level_swept - state.psych_levels.nearest_below) < 20)
        ]

        if recent_sweeps_at_level:
            sweep = recent_sweeps_at_level[-1]
            return Direction.SHORT if sweep.direction == "above" else Direction.LONG

        # Otherwise follow displacement direction (break model)
        if disp_dir == "bullish":
            return Direction.LONG
        elif disp_dir == "bearish":
            return Direction.SHORT

        return None

    def _build_confluence(self, state: MarketState, direction: Direction) -> list[str]:
        """Count and tag confluence factors. Need >= 3."""
        tags: list[str] = []

        # 1. Psych level proximity (always true if we got here)
        tags.append("psych_level")

        # 2. SMT divergence
        if state.smt_signals:
            matching = [s for s in state.smt_signals if s.direction == direction]
            if matching:
                tags.append("smt_aligned")

        # 3. Liquidity interaction (sweep near level)
        if any(s.rejected for s in state.sweep_events):
            tags.append("liquidity_swept")

        # 4. Displacement
        if state.displacement_candles:
            tags.append("displacement_confirmed")

        # 5. Session timing
        if state.session == SessionName.NY_KILLZONE:
            tags.append("killzone_timing")

        # 6. Structure alignment
        if (direction == Direction.LONG and state.structure_bias == StructureBias.BULLISH) or \
           (direction == Direction.SHORT and state.structure_bias == StructureBias.BEARISH):
            tags.append("structure_aligned")

        # 7. FVG present
        if state.fvgs:
            matching_fvgs = [f for f in state.fvgs if not f.filled and f.type == direction]
            if matching_fvgs:
                tags.append("fvg_present")

        return tags

    def _calculate_entry(self, state: MarketState, direction: Direction) -> Optional[float]:
        """Entry at the psych level or nearest FVG."""
        # Prefer FVG entry near psych level
        if state.fvgs:
            matching = [f for f in state.fvgs if not f.filled and f.type == direction and f.age_bars < 15]
            if matching:
                fvg = matching[-1]
                return fvg.upper if direction == Direction.LONG else fvg.lower

        # Fallback to psych level itself
        if state.psych_levels:
            if direction == Direction.LONG:
                return state.psych_levels.nearest_below
            else:
                return state.psych_levels.nearest_above

        return None

    def _calculate_stop(self, state: MarketState, direction: Direction, entry: float) -> Optional[float]:
        """Tighter stop — half ATR or nearest invalidation."""
        buffer = self.rules["stop"]["buffer_ticks"] * 0.01
        # Use psych level spacing as proxy for tight stop
        if state.psych_levels:
            level_gap = abs(state.psych_levels.nearest_above - state.psych_levels.nearest_below)
            half_gap = level_gap / 2
            if direction == Direction.LONG:
                return entry - half_gap - buffer
            else:
                return entry + half_gap + buffer

        # Fallback
        if direction == Direction.LONG:
            return entry - 0.002 - buffer  # 20 pips for FX
        else:
            return entry + 0.002 + buffer

    def _calculate_targets(self, state: MarketState, direction: Direction, entry: float) -> list[Target]:
        targets: list[Target] = []

        # Target 1: Next psych level (50% close)
        if state.psych_levels:
            if direction == Direction.LONG:
                targets.append(Target(price=state.psych_levels.nearest_above, pct_close=0.50))
            else:
                targets.append(Target(price=state.psych_levels.nearest_below, pct_close=0.50))

        # Target 2: Session range target (30%)
        ny_range = state.session_ranges.get("ny") or state.session_ranges.get("overnight")
        if ny_range:
            if direction == Direction.LONG:
                targets.append(Target(price=ny_range.high, pct_close=0.30))
            else:
                targets.append(Target(price=ny_range.low, pct_close=0.30))

        # Target 3: Runner (20%)
        if targets:
            first_dist = abs(targets[0].price - entry)
            ext = entry + first_dist * 1.5 if direction == Direction.LONG else entry - first_dist * 1.5
            targets.append(Target(price=round(ext, 5), pct_close=0.20))

        return targets

    def _score_setup(self, state: MarketState, tags: list[str]) -> float:
        score = 0.3
        score += 0.1 * min(len(tags), 5)  # More confluence = higher score
        if any("smt" in t for t in tags):
            score += 0.1
        return min(1.0, score)

    def _score_clarity(self, state: MarketState) -> float:
        score = 0.3
        if state.psych_levels and state.psych_levels.proximity_score > 0.7:
            score += 0.25
        if len(state.swing_points) >= 4:
            score += 0.15
        if state.displacement_candles:
            score += 0.15
        if state.fvgs:
            score += 0.15
        return min(1.0, score)
