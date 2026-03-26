"""Confidence Scorer — prediction-market style trade signal scoring.

Scores each trade candidate across 7 dimensions and produces a
composite confidence score used for trade gating.
"""

from __future__ import annotations

import structlog
import yaml

from core.models import ConfidenceBreakdown

logger = structlog.get_logger(__name__)


class ConfidenceScorer:
    """Scores trade signals across 7 dimensions."""

    def __init__(self, config_path: str = "config/strategy.yaml"):
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        self.weights = cfg["global"]["confidence_weights"]

    def score(
        self,
        p_setup: float,
        ev_ratio: float,
        regime_confidence: float,
        exec_confidence: float,
        structural_clarity: float,
        correlation_confirm: float,
        session_timing: float,
    ) -> tuple[float, ConfidenceBreakdown]:
        """Calculate composite confidence from 7 dimensions.

        Returns (composite_score, breakdown).
        """
        breakdown = ConfidenceBreakdown(
            p_setup=_clamp(p_setup),
            ev_ratio=_clamp(ev_ratio),
            regime_confidence=_clamp(regime_confidence),
            exec_confidence=_clamp(exec_confidence),
            structural_clarity=_clamp(structural_clarity),
            correlation_confirm=_clamp(correlation_confirm),
            session_timing=_clamp(session_timing),
        )

        composite = (
            breakdown.p_setup * self.weights["p_setup"]
            + breakdown.ev_ratio * self.weights["ev_ratio"]
            + breakdown.regime_confidence * self.weights["regime_confidence"]
            + breakdown.exec_confidence * self.weights["exec_confidence"]
            + breakdown.structural_clarity * self.weights["structural_clarity"]
            + breakdown.correlation_confirm * self.weights["correlation_confirm"]
            + breakdown.session_timing * self.weights["session_timing"]
        )

        return round(_clamp(composite), 4), breakdown

    def apply_boosters(
        self, base_confidence: float, booster_tags: list[str], booster_config: dict[str, float]
    ) -> float:
        """Apply strategy-specific confidence boosters."""
        boosted = base_confidence
        for tag in booster_tags:
            boost = booster_config.get(tag, 0.0)
            boosted += boost

        return round(min(1.0, boosted), 4)


def _clamp(value: float) -> float:
    """Clamp a value between 0.0 and 1.0."""
    return max(0.0, min(1.0, value))
