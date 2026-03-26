"""SMT (Smart Money Technique) Divergence Detection.

Compares swing points across correlated instruments to detect divergences
that signal potential reversals.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import structlog
import yaml

from core.models import Candle, Direction, SMTSignal, SwingPoint

logger = structlog.get_logger(__name__)


class SMTDetector:
    """Detects divergence between correlated instruments."""

    def __init__(self, config_path: str = "config/structure.yaml"):
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        smt_cfg = cfg["smt"]
        self.pairs: list[list[str]] = smt_cfg["pairs"]
        self.max_divergence_bars = smt_cfg["max_divergence_bars"]
        self.min_atr_filter = smt_cfg["min_atr_filter"]
        self.require_session_valid = smt_cfg.get("require_session_valid", True)

    def get_pair_for(self, symbol: str) -> Optional[str]:
        """Find the correlated pair symbol for a given symbol."""
        for pair in self.pairs:
            if symbol in pair:
                return pair[1] if pair[0] == symbol else pair[0]
        return None

    def detect_divergence(
        self,
        symbol_a: str,
        swings_a: list[SwingPoint],
        symbol_b: str,
        swings_b: list[SwingPoint],
        atr_a: float,
        atr_b: float,
        session_valid: bool = True,
    ) -> list[SMTSignal]:
        """Detect SMT divergence between two instruments.

        Divergence: instrument A makes a new swing high/low but instrument B
        fails to do the same within max_divergence_bars.

        Bullish divergence: A makes lower low, B fails to → reversal up
        Bearish divergence: A makes higher high, B fails to → reversal down
        """
        signals: list[SMTSignal] = []

        # ATR filter — skip if volatility too low on either instrument
        if atr_a < self.min_atr_filter or atr_b < self.min_atr_filter:
            return signals

        if self.require_session_valid and not session_valid:
            return signals

        # Check for bearish divergence (higher high on A, B fails)
        signals.extend(self._check_high_divergence(
            symbol_a, swings_a, symbol_b, swings_b, session_valid
        ))

        # Check for bullish divergence (lower low on A, B fails)
        signals.extend(self._check_low_divergence(
            symbol_a, swings_a, symbol_b, swings_b, session_valid
        ))

        return signals

    def _check_high_divergence(
        self,
        sym_a: str,
        swings_a: list[SwingPoint],
        sym_b: str,
        swings_b: list[SwingPoint],
        session_valid: bool,
    ) -> list[SMTSignal]:
        """Check if A makes a higher high but B doesn't."""
        signals: list[SMTSignal] = []
        highs_a = [s for s in swings_a if s.type == "swing_high"]
        highs_b = [s for s in swings_b if s.type == "swing_high"]

        if len(highs_a) < 2 or len(highs_b) < 2:
            return signals

        # Most recent two swing highs on each
        last_a = highs_a[-1]
        prev_a = highs_a[-2]
        last_b = highs_b[-1]
        prev_b = highs_b[-2]

        # A made higher high
        if last_a.price > prev_a.price:
            # B failed to make higher high (within bar window)
            bar_diff = abs(last_a.bar_index - last_b.bar_index)
            if bar_diff <= self.max_divergence_bars and last_b.price <= prev_b.price:
                strength = self._calc_strength(last_a, prev_a, last_b, prev_b)
                signals.append(SMTSignal(
                    pair=(sym_a, sym_b),
                    direction=Direction.SHORT,  # Bearish divergence
                    strength=strength,
                    timestamp=last_a.timestamp,
                    session_valid=session_valid,
                ))

        return signals

    def _check_low_divergence(
        self,
        sym_a: str,
        swings_a: list[SwingPoint],
        sym_b: str,
        swings_b: list[SwingPoint],
        session_valid: bool,
    ) -> list[SMTSignal]:
        """Check if A makes a lower low but B doesn't."""
        signals: list[SMTSignal] = []
        lows_a = [s for s in swings_a if s.type == "swing_low"]
        lows_b = [s for s in swings_b if s.type == "swing_low"]

        if len(lows_a) < 2 or len(lows_b) < 2:
            return signals

        last_a = lows_a[-1]
        prev_a = lows_a[-2]
        last_b = lows_b[-1]
        prev_b = lows_b[-2]

        # A made lower low
        if last_a.price < prev_a.price:
            bar_diff = abs(last_a.bar_index - last_b.bar_index)
            if bar_diff <= self.max_divergence_bars and last_b.price >= prev_b.price:
                strength = self._calc_strength(last_a, prev_a, last_b, prev_b)
                signals.append(SMTSignal(
                    pair=(sym_a, sym_b),
                    direction=Direction.LONG,  # Bullish divergence
                    strength=strength,
                    timestamp=last_a.timestamp,
                    session_valid=session_valid,
                ))

        return signals

    def _calc_strength(
        self,
        last_a: SwingPoint,
        prev_a: SwingPoint,
        last_b: SwingPoint,
        prev_b: SwingPoint,
    ) -> float:
        """Calculate divergence strength (0-1).

        Stronger when: A's move is large, B's failure is clear, bars are close together.
        """
        # How far A extended beyond its prior swing
        a_extension = abs(last_a.price - prev_a.price)
        # How much B failed
        b_failure = abs(last_b.price - prev_b.price)

        if a_extension == 0:
            return 0.3

        # Ratio of B's failure to A's extension (higher = stronger divergence)
        failure_ratio = b_failure / a_extension if a_extension > 0 else 0

        # Bar proximity bonus
        bar_diff = abs(last_a.bar_index - last_b.bar_index)
        proximity_bonus = max(0, 1.0 - bar_diff / self.max_divergence_bars) * 0.3

        strength = min(1.0, 0.3 + failure_ratio * 0.4 + proximity_bonus)
        return round(strength, 3)
