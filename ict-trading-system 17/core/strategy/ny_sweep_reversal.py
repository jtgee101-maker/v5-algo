"""NY Open Sweep Reversal Strategy — V1.

Identifies manipulation sweeps beyond the overnight/pre-NY accumulation range,
confirmed by SMT divergence or failed continuation, then enters on lower
timeframe displacement/retest targeting opposite internal liquidity.

This is a RULE-BASED strategy with no LLM discretion at runtime.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import structlog
import yaml

from core.models import (
    Direction,
    FVG,
    MarketState,
    PO3Phase,
    Regime,
    SessionName,
    SweepEvent,
    Target,
    TradeSignal,
)
from core.strategy.scorer import ConfidenceScorer

logger = structlog.get_logger(__name__)


class NYSweepReversalStrategy:
    """NY Open Sweep Reversal — V1.

    Entry logic:
    1. Pre-NY accumulation range must exist
    2. Sweep beyond that range (manipulation)
    3. Confirmation: SMT divergence OR failed continuation (rejected sweep)
    4. Entry on LTF displacement + FVG retest
    5. Stop at manipulation extreme
    6. Targets: opposite liquidity / OR midpoint / OR extension
    """

    def __init__(self, config_path: str = "config/strategy.yaml"):
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        self.global_cfg = cfg["global"]
        self.strat_cfg = cfg["strategies"]["ny_sweep_reversal"]
        self.scorer = ConfidenceScorer(config_path)

        self.version = self.strat_cfg["version"]
        self.strategy_id = f"ny_sweep_reversal_{self.version}"
        self.min_rr = self.strat_cfg["min_reward_risk"]
        self.min_confidence = self.strat_cfg["min_confidence"]

    def evaluate(self, state: MarketState) -> Optional[TradeSignal]:
        """Evaluate market state for a sweep reversal setup.

        Returns a TradeSignal if conditions are met, None otherwise.
        """
        # Gate 1: Must be in NY session
        if state.session not in (SessionName.NY, SessionName.NY_KILLZONE):
            return None

        # Gate 2: Need an overnight/accumulation range
        overnight = state.session_ranges.get("overnight") or state.session_ranges.get("asia")
        if overnight is None:
            return None

        # Gate 3: Need sweep events
        recent_sweeps = [
            s for s in state.sweep_events
            if s.rejected and s.displacement_followed
        ]
        if not recent_sweeps:
            return None

        # Pick the most recent valid sweep
        sweep = recent_sweeps[-1]

        # Gate 4: Sweep must be beyond the accumulation range
        if sweep.direction == "above" and sweep.level_swept <= overnight.high:
            return None
        if sweep.direction == "below" and sweep.level_swept >= overnight.low:
            return None

        # Determine trade direction (opposite of sweep direction)
        if sweep.direction == "above":
            direction = Direction.SHORT
        elif sweep.direction == "below":
            direction = Direction.LONG
        else:
            return None

        # Gate 5: Check for confirmation
        has_smt = len(state.smt_signals) > 0
        has_po3_manip = state.po3_state.phase in (PO3Phase.MANIPULATED, PO3Phase.DISTRIBUTING)
        has_rejection = sweep.rejected

        if not (has_smt or has_po3_manip or has_rejection):
            return None

        # Gate 6: Find entry from FVG (fair value gap) for retest entry
        entry_price, fvg_used = self._find_entry(state, direction)
        if entry_price is None:
            return None

        # Stop at manipulation extreme
        stop_price = self._calculate_stop(sweep, direction)

        # Targets from liquidity pools
        targets = self._calculate_targets(state, direction, entry_price)
        if not targets:
            return None

        # Reward/risk check
        risk_distance = abs(entry_price - stop_price)
        reward_distance = abs(targets[0].price - entry_price)
        if risk_distance <= 0:
            return None
        reward_risk = reward_distance / risk_distance
        if reward_risk < self.min_rr:
            return None

        # Score the setup
        confluence_tags = self._get_confluence_tags(state, sweep, has_smt, has_po3_manip)

        composite, breakdown = self.scorer.score(
            p_setup=self._score_setup_probability(state, sweep),
            ev_ratio=min(1.0, reward_risk / 4.0),  # Normalize RR to 0-1 (4R = perfect)
            regime_confidence=self._score_regime(state),
            exec_confidence=0.7,  # Default; session monitor overrides later
            structural_clarity=self._score_structure_clarity(state, sweep),
            correlation_confirm=0.8 if has_smt else 0.3,
            session_timing=self._score_session_timing(state),
        )

        # Apply boosters
        boosters = self.strat_cfg.get("confidence_boosters", {})
        final_confidence = self.scorer.apply_boosters(composite, confluence_tags, boosters)

        if final_confidence < self.min_confidence:
            logger.debug(
                "strategy.sweep_reversal.below_threshold",
                confidence=final_confidence,
                threshold=self.min_confidence,
            )
            return None

        signal = TradeSignal(
            timestamp=state.timestamp,
            strategy_id=self.strategy_id,
            symbol=state.symbol,
            direction=direction,
            confidence=final_confidence,
            confidence_breakdown=breakdown,
            entry_type="limit",
            entry_price=entry_price,
            stop_price=stop_price,
            targets=targets,
            invalidation=f"close_{'below' if direction == Direction.LONG else 'above'}_{stop_price}",
            reward_risk=round(reward_risk, 2),
            confluence_tags=confluence_tags,
            regime=Regime.REVERSAL_DAY,
            session=state.session.value,
            market_state_ref=f"market_state_{state.symbol}_{state.timestamp.strftime('%Y%m%dT%H%M%S')}.json",
        )

        logger.info(
            "strategy.sweep_reversal.signal",
            symbol=state.symbol,
            direction=direction,
            confidence=final_confidence,
            rr=reward_risk,
            tags=confluence_tags,
        )

        return signal

    # ── Helper Methods ─────────────────────────────────────────────────

    def _find_entry(
        self, state: MarketState, direction: Direction
    ) -> tuple[Optional[float], Optional[FVG]]:
        """Find entry price from FVG or displacement level."""
        # Look for unfilled FVG in the right direction
        matching_fvgs = [
            f for f in state.fvgs
            if not f.filled and f.type == direction and f.age_bars < 20
        ]

        if matching_fvgs:
            fvg = matching_fvgs[-1]  # Most recent
            if direction == Direction.LONG:
                entry = fvg.upper  # Enter at top of bullish FVG (retest from above)
            else:
                entry = fvg.lower  # Enter at bottom of bearish FVG
            return entry, fvg

        # Fallback: use the most recent displacement candle level
        if state.displacement_candles:
            last_disp = state.displacement_candles[-1]
            # Use the displacement timestamp to find approximate level
            # This is a simplified fallback
            return None, None

        return None, None

    def _calculate_stop(self, sweep: SweepEvent, direction: Direction) -> float:
        """Place stop at the manipulation extreme with buffer."""
        buffer = 5  # ticks — TODO: make configurable from tick_size
        if direction == Direction.LONG:
            return sweep.level_swept - buffer * 0.01
        else:
            return sweep.level_swept + buffer * 0.01

    def _calculate_targets(
        self, state: MarketState, direction: Direction, entry: float
    ) -> list[Target]:
        """Calculate target ladder from liquidity pools and session ranges."""
        targets: list[Target] = []

        # Target 1: Opposite internal liquidity (50% close)
        opposite_pools = []
        for pool in state.liquidity_pools:
            if direction == Direction.LONG and pool.price > entry:
                opposite_pools.append(pool)
            elif direction == Direction.SHORT and pool.price < entry:
                opposite_pools.append(pool)

        if opposite_pools:
            if direction == Direction.LONG:
                nearest = min(opposite_pools, key=lambda p: p.price)
            else:
                nearest = max(opposite_pools, key=lambda p: p.price)
            targets.append(Target(price=nearest.price, pct_close=0.50))

        # Target 2: Session range midpoint (30% close)
        overnight = state.session_ranges.get("overnight")
        if overnight and overnight.mid:
            targets.append(Target(price=overnight.mid, pct_close=0.30))

        # Target 3: Extended target (20% close — runner)
        if targets:
            first_target_dist = abs(targets[0].price - entry)
            if direction == Direction.LONG:
                extension = entry + first_target_dist * 1.618
            else:
                extension = entry - first_target_dist * 1.618
            targets.append(Target(price=round(extension, 5), pct_close=0.20))

        return targets

    def _get_confluence_tags(
        self, state: MarketState, sweep: SweepEvent, has_smt: bool, has_po3: bool
    ) -> list[str]:
        """Build list of confluence tags present in this setup."""
        tags: list[str] = []
        if has_smt:
            tags.append("smt_divergence")
        if has_po3:
            tags.append("po3_in_manipulation")
        if state.psych_levels and state.psych_levels.proximity_score > 0.5:
            tags.append("psych_level_confluence")
        if sweep.displacement_followed:
            tags.append("displacement_confirmed")
        if sweep.rejected:
            tags.append("sweep_rejected")
        return tags

    def _score_setup_probability(self, state: MarketState, sweep: SweepEvent) -> float:
        """Score the probability this setup works based on structure quality."""
        score = 0.4  # Base
        if sweep.rejected:
            score += 0.15
        if sweep.displacement_followed:
            score += 0.15
        if state.po3_state.phase in (PO3Phase.MANIPULATED, PO3Phase.DISTRIBUTING):
            score += 0.1
        if len(state.smt_signals) > 0:
            score += 0.1
        if state.psych_levels and state.psych_levels.proximity_score > 0.5:
            score += 0.1
        return min(1.0, score)

    def _score_regime(self, state: MarketState) -> float:
        """Score how well current conditions match reversal day regime."""
        # Reversal days tend to have: tight overnight range, strong sweep, clear rejection
        score = 0.5
        overnight = state.session_ranges.get("overnight")
        if overnight and overnight.range_atr_ratio:
            if overnight.range_atr_ratio < 0.5:
                score += 0.2  # Tight range = better for reversal
        if len(state.sweep_events) >= 1:
            score += 0.15
        if state.structure_bias.value in ("bullish", "bearish"):
            score += 0.1  # Clear bias better than ranging for reversals
        return min(1.0, score)

    def _score_structure_clarity(self, state: MarketState, sweep: SweepEvent) -> float:
        """Score how unambiguous the structure labels are."""
        score = 0.3
        if len(state.swing_points) >= 4:
            score += 0.2
        if len(state.liquidity_pools) >= 3:
            score += 0.15
        if state.fvgs:
            score += 0.15
        if sweep.displacement_followed:
            score += 0.2
        return min(1.0, score)

    def _score_session_timing(self, state: MarketState) -> float:
        """Score timing within the session."""
        if state.session == SessionName.NY_KILLZONE:
            return 0.9  # Optimal
        elif state.session == SessionName.NY:
            return 0.6  # Acceptable
        return 0.2  # Poor timing
