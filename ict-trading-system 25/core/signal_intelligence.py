"""Signal Intelligence Engine — validation, scoring, dedup, classification.

This is the missing layer between raw scanner/DRM output and persisted signals.
No garbage reaches the operator console.

Pipeline: raw input → validate → score → dedup → classify → persist

Classes:
  SignalValidationEngine — structural + price sanity checks
  SignalScoringEngine — quality + confluence + trust scoring
  SignalDeduplicator — fingerprint-based dedup + versioning
  SignalClassifier — bucket into actionable/candidate/rejected/invalid
  DRMDecisionEngine — converts DRM zones into trade decisions
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)


# ══════════════════════════════════════════════════════════════════════
# VALIDATION ENGINE — structural + price sanity
# ══════════════════════════════════════════════════════════════════════

class SignalValidationEngine:
    """Validates every signal before it can enter the pipeline.

    Checks: symbol validity, price sanity, ATR bounds, directional coherence,
    field completeness, market data freshness.
    """

    # Max % deviation from current price for entry/SL/TP
    MAX_ENTRY_DEVIATION_PCT = 5.0     # Entry within 5% of market
    MAX_SL_DEVIATION_PCT = 15.0       # Stop within 15%
    MAX_TP_DEVIATION_PCT = 30.0       # Target within 30%
    MIN_SL_ATR_MULTIPLE = 0.2         # Stop must be at least 0.2 ATR away
    MAX_SL_ATR_MULTIPLE = 5.0         # Stop no more than 5 ATR away
    MIN_TP_ATR_MULTIPLE = 0.3         # Target at least 0.3 ATR
    MAX_TP_ATR_MULTIPLE = 10.0        # Target no more than 10 ATR
    STALE_DATA_SECONDS = 300          # 5 min = stale

    def validate(
        self,
        *,
        symbol: str,
        direction: str,
        entry: float,
        stop_loss: float,
        take_profit: float,
        current_price: float = 0,
        atr: float = 0,
        source: str = "",
        strategy: str = "",
        allowed_symbols: list[str] = None,
        data_timestamp: str = "",
        confidence: float = 0,
    ) -> dict:
        """Validate a proposed signal. Returns validation result."""

        hard_failures = []
        soft_warnings = []
        normalized = {}

        # ── 1. Symbol validity ────────────────────────────────
        if not symbol or not symbol.strip():
            hard_failures.append("Missing symbol")
        elif allowed_symbols and symbol.upper() not in [s.upper() for s in allowed_symbols]:
            hard_failures.append(f"Symbol {symbol} not in allowed list")
        normalized["symbol"] = symbol.upper() if symbol else ""

        # ── 2. Direction validity ─────────────────────────────
        dir_lower = (direction or "").lower()
        if dir_lower not in ("long", "short", "buy", "sell"):
            hard_failures.append(f"Invalid direction: {direction}")
        normalized["direction"] = "long" if dir_lower in ("long", "buy") else "short"

        # ── 3. Required fields ────────────────────────────────
        if entry <= 0:
            hard_failures.append(f"Invalid entry price: {entry}")
        if stop_loss <= 0:
            hard_failures.append(f"Invalid stop loss: {stop_loss}")
        if take_profit <= 0:
            hard_failures.append(f"Invalid take profit: {take_profit}")
        if not source:
            soft_warnings.append("No source specified")
        if not strategy:
            soft_warnings.append("No strategy specified")

        # If basic fields are missing, can't do further checks
        if hard_failures:
            return self._result(False, hard_failures, soft_warnings, normalized, 0)

        # ── 4. Directional coherence ──────────────────────────
        is_long = normalized["direction"] == "long"

        if is_long:
            if stop_loss >= entry:
                hard_failures.append(f"Long signal: stop ({stop_loss}) must be below entry ({entry})")
            if take_profit <= entry:
                hard_failures.append(f"Long signal: TP ({take_profit}) must be above entry ({entry})")
        else:
            if stop_loss <= entry:
                hard_failures.append(f"Short signal: stop ({stop_loss}) must be above entry ({entry})")
            if take_profit >= entry:
                hard_failures.append(f"Short signal: TP ({take_profit}) must be below entry ({entry})")

        # ── 5. Price sanity vs current market ─────────────────
        if current_price > 0:
            entry_dev = abs(entry - current_price) / current_price * 100
            sl_dev = abs(stop_loss - current_price) / current_price * 100
            tp_dev = abs(take_profit - current_price) / current_price * 100

            if entry_dev > self.MAX_ENTRY_DEVIATION_PCT:
                hard_failures.append(
                    f"Entry {entry} is {entry_dev:.1f}% from market ({current_price}) — max {self.MAX_ENTRY_DEVIATION_PCT}%"
                )
            if sl_dev > self.MAX_SL_DEVIATION_PCT:
                soft_warnings.append(f"Stop {stop_loss} is {sl_dev:.1f}% from market")
            if tp_dev > self.MAX_TP_DEVIATION_PCT:
                soft_warnings.append(f"TP {take_profit} is {tp_dev:.1f}% from market")

            normalized["entry_deviation_pct"] = round(entry_dev, 2)
            normalized["sl_deviation_pct"] = round(sl_dev, 2)
            normalized["tp_deviation_pct"] = round(tp_dev, 2)

        # ── 6. ATR-based bounds ───────────────────────────────
        if atr > 0:
            sl_distance = abs(entry - stop_loss)
            tp_distance = abs(take_profit - entry)
            sl_atr = sl_distance / atr
            tp_atr = tp_distance / atr

            if sl_atr < self.MIN_SL_ATR_MULTIPLE:
                soft_warnings.append(f"Stop too tight: {sl_atr:.2f}x ATR (min {self.MIN_SL_ATR_MULTIPLE}x)")
            if sl_atr > self.MAX_SL_ATR_MULTIPLE:
                hard_failures.append(f"Stop too wide: {sl_atr:.2f}x ATR (max {self.MAX_SL_ATR_MULTIPLE}x)")
            if tp_atr < self.MIN_TP_ATR_MULTIPLE:
                soft_warnings.append(f"TP too tight: {tp_atr:.2f}x ATR (min {self.MIN_TP_ATR_MULTIPLE}x)")
            if tp_atr > self.MAX_TP_ATR_MULTIPLE:
                soft_warnings.append(f"TP too far: {tp_atr:.2f}x ATR (max {self.MAX_TP_ATR_MULTIPLE}x)")

            normalized["sl_atr_multiple"] = round(sl_atr, 2)
            normalized["tp_atr_multiple"] = round(tp_atr, 2)

        # ── 7. R:R check ─────────────────────────────────────
        risk = abs(entry - stop_loss)
        reward = abs(take_profit - entry)
        rr = reward / risk if risk > 0 else 0
        normalized["risk_reward"] = round(rr, 2)

        if rr < 0.5:
            hard_failures.append(f"Risk:Reward {rr:.2f} is below 0.5 — not worth the risk")
        elif rr < 1.0:
            soft_warnings.append(f"Risk:Reward {rr:.2f} is below 1.0")

        # ── 8. Data freshness ─────────────────────────────────
        if data_timestamp:
            try:
                dt = datetime.fromisoformat(data_timestamp.replace("Z", "+00:00"))
                age = (datetime.now(timezone.utc) - dt).total_seconds()
                if age > self.STALE_DATA_SECONDS:
                    soft_warnings.append(f"Market data is {int(age)}s old (stale)")
                normalized["data_age_seconds"] = round(age, 1)
            except Exception:
                soft_warnings.append("Cannot parse data timestamp")

        # ── Compute validation score ──────────────────────────
        # Start at 100, deduct for issues
        score = 100
        score -= len(hard_failures) * 30
        score -= len(soft_warnings) * 5
        score = max(0, min(100, score))

        valid = len(hard_failures) == 0
        return self._result(valid, hard_failures, soft_warnings, normalized, score)

    def _result(self, valid, hard_failures, soft_warnings, normalized, score) -> dict:
        return {
            "valid": valid,
            "hard_failures": hard_failures,
            "soft_warnings": soft_warnings,
            "normalized_fields": normalized,
            "validation_score": score,
            "rejection_reason": hard_failures[0] if hard_failures else None,
        }


# ══════════════════════════════════════════════════════════════════════
# SCORING ENGINE — quality + confluence + trust
# ══════════════════════════════════════════════════════════════════════

class SignalScoringEngine:
    """Scores how strong and trustworthy a validated signal is.

    Separate from validation. Validation = is it structurally valid?
    Scoring = how good is it?
    """

    # Weights (sum to 1.0)
    WEIGHTS = {
        "structure": 0.25,     # DRM/FVG alignment
        "regime": 0.15,        # Volatility regime fit
        "momentum": 0.15,      # Directional momentum
        "risk_reward": 0.15,   # R:R quality
        "freshness": 0.10,     # Data recency
        "source_trust": 0.10,  # Source credibility
        "duplicate_penalty": 0.05,  # Repetition penalty
        "history": 0.05,       # Strategy track record
    }

    # Source trust rankings (0-100)
    SOURCE_TRUST = {
        "manual": 90,
        "drm_validated": 85,
        "drm": 75,
        "scanner": 60,
        "ai_scan": 50,
        "news_derived": 30,
        "synthetic": 10,
        "unknown": 20,
    }

    # Classification thresholds
    ACTIONABLE_THRESHOLD = 70
    CANDIDATE_THRESHOLD = 45
    LOW_CONFIDENCE_THRESHOLD = 25

    def score(
        self,
        *,
        # From validation
        validation_result: dict,
        # DRM context
        displacement_detected: bool = False,
        displacement_atr_multiple: float = 0,
        fvg_present: bool = False,
        fvg_fill_pct: float = 0,
        fvg_count: int = 0,
        unfilled_fvg_count: int = 0,
        # Market context
        volatility_regime: str = "unknown",
        momentum: str = "neutral",
        momentum_aligned: bool = False,
        # Signal quality
        risk_reward: float = 0,
        # Source
        source: str = "unknown",
        # Freshness
        data_age_seconds: float = 0,
        # Dedup
        is_duplicate: bool = False,
        duplicate_count: int = 0,
        # History
        strategy_win_rate: float = 0,
        strategy_sample_size: int = 0,
        # Sentiment
        sentiment_aligned: bool = False,
        sentiment_available: bool = False,
    ) -> dict:
        """Score a validated signal. Returns score + classification."""

        if not validation_result.get("valid"):
            return {
                "score_total": 0,
                "score_components": {},
                "classification": "invalid",
                "reasons": validation_result.get("hard_failures", []),
            }

        components = {}
        reasons_tradable = []
        reasons_not_tradable = []

        # ── 1. Structure quality (DRM alignment) ─────────────
        struct_score = 20  # base
        if displacement_detected:
            boost = min(displacement_atr_multiple * 15, 40)
            struct_score += boost
            reasons_tradable.append(f"Displacement detected ({displacement_atr_multiple:.1f}x ATR)")
        else:
            reasons_not_tradable.append("No displacement detected")

        if fvg_present and unfilled_fvg_count > 0:
            struct_score += 20
            if fvg_fill_pct < 50:
                struct_score += 10
                reasons_tradable.append(f"FVG {fvg_fill_pct:.0f}% unfilled — rebalance expected")
            else:
                reasons_not_tradable.append(f"FVG {fvg_fill_pct:.0f}% filled — diminishing edge")
        elif not fvg_present:
            reasons_not_tradable.append("No fair value gap detected")

        struct_score = min(100, max(0, struct_score))
        components["structure"] = struct_score

        # ── 2. Regime quality ─────────────────────────────────
        regime_scores = {"extreme": 90, "high": 75, "normal": 40, "low": 15, "unknown": 30}
        regime_score = regime_scores.get(volatility_regime.lower(), 30)
        if volatility_regime.lower() in ("extreme", "high"):
            reasons_tradable.append(f"Volatility regime: {volatility_regime} — DRM edge strong")
        elif volatility_regime.lower() in ("low", "normal"):
            reasons_not_tradable.append(f"Volatility regime: {volatility_regime} — DRM edge weak")
        components["regime"] = regime_score

        # ── 3. Momentum ──────────────────────────────────────
        momentum_score = 50  # neutral base
        if momentum_aligned:
            momentum_score = 85
            reasons_tradable.append("Momentum aligned with direction")
        elif momentum.lower() in ("strong_bullish", "strong_bearish"):
            if momentum_aligned:
                momentum_score = 95
            else:
                momentum_score = 20
                reasons_not_tradable.append("Strong momentum against direction")
        components["momentum"] = momentum_score

        # ── 4. Risk:Reward ───────────────────────────────────
        if risk_reward <= 0:
            rr_score = 0
        elif risk_reward >= 3.0:
            rr_score = 100
            reasons_tradable.append(f"Excellent R:R {risk_reward:.1f}:1")
        elif risk_reward >= 2.0:
            rr_score = 80
            reasons_tradable.append(f"Good R:R {risk_reward:.1f}:1")
        elif risk_reward >= 1.5:
            rr_score = 60
        elif risk_reward >= 1.0:
            rr_score = 40
        else:
            rr_score = 15
            reasons_not_tradable.append(f"Poor R:R {risk_reward:.1f}:1")
        components["risk_reward"] = rr_score

        # ── 5. Freshness ─────────────────────────────────────
        if data_age_seconds <= 60:
            fresh_score = 100
        elif data_age_seconds <= 300:
            fresh_score = 70
        elif data_age_seconds <= 600:
            fresh_score = 40
            reasons_not_tradable.append("Data is >5 min old")
        else:
            fresh_score = 10
            reasons_not_tradable.append("Data is stale (>10 min)")
        components["freshness"] = fresh_score

        # ── 6. Source trust ──────────────────────────────────
        trust_score = self.SOURCE_TRUST.get(source.lower(), 20)
        components["source_trust"] = trust_score

        # ── 7. Duplicate penalty ─────────────────────────────
        if is_duplicate:
            dup_score = max(0, 100 - duplicate_count * 30)
            reasons_not_tradable.append(f"Duplicate signal (seen {duplicate_count}x)")
        else:
            dup_score = 100
        components["duplicate_penalty"] = dup_score

        # ── 8. Historical performance ────────────────────────
        if strategy_sample_size >= 10:
            hist_score = min(100, strategy_win_rate * 100 * 1.2)
        elif strategy_sample_size >= 5:
            hist_score = min(100, strategy_win_rate * 100)
        else:
            hist_score = 50  # no data = neutral
        components["history"] = hist_score

        # ── Sentiment boost/penalty (not a scored component, but modifier)
        sentiment_modifier = 0
        if sentiment_available:
            if sentiment_aligned:
                sentiment_modifier = 5
                reasons_tradable.append("Sentiment aligned")
            else:
                sentiment_modifier = -3

        # ── Compute total ────────────────────────────────────
        total = sum(
            components[k] * self.WEIGHTS[k]
            for k in self.WEIGHTS
        ) + sentiment_modifier
        total = max(0, min(100, round(total, 1)))

        # ── Classify ─────────────────────────────────────────
        if total >= self.ACTIONABLE_THRESHOLD:
            classification = "actionable"
        elif total >= self.CANDIDATE_THRESHOLD:
            classification = "candidate"
        elif total >= self.LOW_CONFIDENCE_THRESHOLD:
            classification = "low_confidence"
        else:
            classification = "rejected"

        return {
            "score_total": total,
            "score_components": components,
            "classification": classification,
            "why_tradable": reasons_tradable,
            "why_not_tradable": reasons_not_tradable,
            "sentiment_modifier": sentiment_modifier,
        }


# ══════════════════════════════════════════════════════════════════════
# DEDUPLICATOR — fingerprint-based dedup + versioning
# ══════════════════════════════════════════════════════════════════════

class SignalDeduplicator:
    """Detects and handles duplicate signals before persistence.

    Fingerprint: symbol + direction + strategy + rounded(entry) + rounded(stop) + time_bucket
    """

    # Time bucket: signals within this window are considered same setup
    TIME_BUCKET_MINUTES = 60
    # Price rounding for fingerprint (0.1% of price)
    PRICE_ROUND_PCT = 0.001

    def __init__(self):
        self._fingerprints: dict[str, dict] = {}  # fp → {count, first_seen, last_seen, signal_id}

    def check(
        self, *, symbol: str, direction: str, strategy: str,
        entry: float, stop_loss: float, take_profit: float,
        timestamp: str = "",
    ) -> dict:
        """Check if this signal is a duplicate.

        Returns: {is_duplicate, duplicate_type, fingerprint, existing_signal_id,
                  duplicate_count, action}
        """
        fp = self._compute_fingerprint(symbol, direction, strategy, entry, stop_loss, take_profit)
        now = datetime.now(timezone.utc)

        existing = self._fingerprints.get(fp)
        if existing:
            age_seconds = (now - datetime.fromisoformat(existing["last_seen"])).total_seconds()

            if age_seconds < self.TIME_BUCKET_MINUTES * 60:
                # Same setup within time window
                existing["count"] += 1
                existing["last_seen"] = now.isoformat()

                if existing["count"] <= 1:
                    dup_type = "exact"
                elif existing["count"] <= 3:
                    dup_type = "near"
                else:
                    dup_type = "spam"

                return {
                    "is_duplicate": True,
                    "duplicate_type": dup_type,
                    "fingerprint": fp,
                    "existing_signal_id": existing.get("signal_id"),
                    "duplicate_count": existing["count"],
                    "action": "suppress" if dup_type == "spam" else "version",
                    "parent_signal_id": existing.get("signal_id"),
                }
            else:
                # Same fingerprint but outside time window — new setup
                existing["count"] = 1
                existing["last_seen"] = now.isoformat()

        # New signal
        self._fingerprints[fp] = {
            "count": 1,
            "first_seen": now.isoformat(),
            "last_seen": now.isoformat(),
            "signal_id": None,
        }

        return {
            "is_duplicate": False,
            "duplicate_type": None,
            "fingerprint": fp,
            "existing_signal_id": None,
            "duplicate_count": 0,
            "action": "create",
            "parent_signal_id": None,
        }

    def register_signal(self, fingerprint: str, signal_id: str) -> None:
        """Register a created signal's ID for future dedup lookups."""
        if fingerprint in self._fingerprints:
            self._fingerprints[fingerprint]["signal_id"] = signal_id

    def _compute_fingerprint(
        self, symbol: str, direction: str, strategy: str,
        entry: float, stop_loss: float, take_profit: float,
    ) -> str:
        """Compute a deterministic fingerprint for dedup."""
        # Round prices to reduce noise
        def _round(price):
            if price <= 0:
                return "0"
            bucket = price * self.PRICE_ROUND_PCT
            return str(round(price / max(bucket, 0.01)) * max(bucket, 0.01))

        raw = f"{symbol.upper()}|{direction.lower()}|{strategy.lower()}|{_round(entry)}|{_round(stop_loss)}|{_round(take_profit)}"
        return hashlib.md5(raw.encode()).hexdigest()[:12]

    def get_stats(self) -> dict:
        """Get dedup stats."""
        return {
            "tracked_fingerprints": len(self._fingerprints),
            "total_duplicates": sum(v["count"] - 1 for v in self._fingerprints.values() if v["count"] > 1),
        }


# ══════════════════════════════════════════════════════════════════════
# DRM DECISION ENGINE — converts DRM data into trade decisions
# ══════════════════════════════════════════════════════════════════════

class DRMDecisionEngine:
    """Converts raw DRM analysis into structured trade decisions.

    Stops being a data dump. For each symbol, returns:
    - setup_detected (true/false)
    - setup_type classification
    - confluence_score
    - trade_eligibility
    - why_tradable / why_not_tradable
    """

    # Minimum scores for trade eligibility
    MIN_CONFLUENCE_FOR_TRADE = 3   # out of 7
    MIN_DISPLACEMENT_ATR = 1.5     # minimum displacement size
    MIN_UNFILLED_FVG_PCT = 20      # FVG must be at least 20% unfilled

    def evaluate(self, drm_result: dict) -> dict:
        """Evaluate a DRM analysis result and produce a trade decision."""

        symbol = drm_result.get("symbol", "UNKNOWN")
        current_price = drm_result.get("current_price", 0)
        atr = drm_result.get("atr", 0)
        regime = drm_result.get("volatility_regime", "unknown")
        displacements = drm_result.get("displacements", [])
        fvgs = drm_result.get("fair_value_gaps", [])
        signals = drm_result.get("signals", [])
        unfilled = drm_result.get("unfilled_fvgs", 0)

        why_tradable = []
        why_not_tradable = []
        confluence = 0

        # ── Check displacement ────────────────────────────────
        has_displacement = False
        max_disp_atr = 0
        for d in displacements:
            atr_mult = d.get("atr_multiple", d.get("displacement_atr", 0))
            if atr_mult >= self.MIN_DISPLACEMENT_ATR:
                has_displacement = True
                max_disp_atr = max(max_disp_atr, atr_mult)

        if has_displacement:
            confluence += 2 if max_disp_atr >= 2.5 else 1
            why_tradable.append(f"Displacement detected: {max_disp_atr:.1f}x ATR")
        else:
            why_not_tradable.append(f"No displacement ≥{self.MIN_DISPLACEMENT_ATR}x ATR")

        # ── Check FVGs ────────────────────────────────────────
        live_fvgs = [f for f in fvgs if not f.get("filled", True) and f.get("fill_pct", 100) < (100 - self.MIN_UNFILLED_FVG_PCT)]
        if live_fvgs:
            confluence += 1
            best_fill = min(f.get("fill_pct", 100) for f in live_fvgs)
            why_tradable.append(f"{len(live_fvgs)} unfilled FVGs (best: {best_fill:.0f}% filled)")
        else:
            why_not_tradable.append("No significantly unfilled FVGs")

        # ── Check regime ──────────────────────────────────────
        if regime.lower() in ("extreme", "high"):
            confluence += 1
            why_tradable.append(f"Regime: {regime} — DRM edge is strong")
        elif regime.lower() == "normal":
            why_not_tradable.append("Regime: normal — DRM edge is marginal")
        elif regime.lower() == "low":
            why_not_tradable.append("Regime: low — DRM not suitable")
            confluence -= 1

        # ── Check price proximity to entry zone ───────────────
        if signals:
            best_signal = max(signals, key=lambda s: s.get("conf_score", 0))
            ez = best_signal.get("entry_zone", {})
            ez_low = ez.get("low", 0)
            ez_high = ez.get("high", 0)

            if ez_low > 0 and ez_high > 0 and atr > 0:
                dist_to_zone = min(abs(current_price - ez_low), abs(current_price - ez_high))
                if dist_to_zone <= atr:
                    confluence += 1
                    why_tradable.append(f"Price within 1 ATR of entry zone ({ez_low:.2f}–{ez_high:.2f})")
                elif dist_to_zone <= atr * 2:
                    why_tradable.append(f"Price within 2 ATR of entry zone")
                else:
                    why_not_tradable.append(f"Price {dist_to_zone / atr:.1f} ATR from entry zone — too far")

            # Check R:R from signal
            rr = best_signal.get("risk_reward", 0)
            if rr >= 2.0:
                confluence += 1
                why_tradable.append(f"R:R {rr:.1f}:1 — excellent")
            elif rr >= 1.5:
                why_tradable.append(f"R:R {rr:.1f}:1 — acceptable")
            elif rr > 0:
                why_not_tradable.append(f"R:R {rr:.1f}:1 — weak")

            # Touch probability
            tp = best_signal.get("touch_prob_target", 0)
            if tp >= 60:
                confluence += 1
                why_tradable.append(f"Target touch probability: {tp:.0f}%")
            elif tp >= 40:
                why_tradable.append(f"Target touch probability: {tp:.0f}% — moderate")
            elif tp > 0:
                why_not_tradable.append(f"Target touch probability only {tp:.0f}%")

        # ── Determine setup type ──────────────────────────────
        if not signals:
            setup_type = "no_valid_setup"
            setup_detected = False
        elif has_displacement and live_fvgs:
            bias = signals[0].get("bias", "unknown")
            setup_type = f"displacement_rebalance_{bias}"
            setup_detected = True
        elif live_fvgs:
            setup_type = "imbalance_continuation"
            setup_detected = True
        else:
            setup_type = "weak_structure"
            setup_detected = False

        # ── Trade eligibility ─────────────────────────────────
        trade_eligible = confluence >= self.MIN_CONFLUENCE_FOR_TRADE and setup_detected

        return {
            "symbol": symbol,
            "setup_detected": setup_detected,
            "setup_type": setup_type,
            "confluence_score": max(0, min(7, confluence)),
            "displacement_score": round(max_disp_atr, 2),
            "fvg_quality_score": len(live_fvgs),
            "regime_fit": regime.lower() in ("extreme", "high"),
            "trade_eligible": trade_eligible,
            "why_tradable": why_tradable,
            "why_not_tradable": why_not_tradable,
            "current_price": current_price,
            "atr": atr,
            "regime": regime,
            "unfilled_fvgs": unfilled,
            "signals_count": len(signals),
        }


# ══════════════════════════════════════════════════════════════════════
# MASTER PIPELINE — runs all engines in sequence
# ══════════════════════════════════════════════════════════════════════

class SignalIntelligencePipeline:
    """Orchestrates: validate → score → dedup → classify → output.

    This is the single entry point for all signal creation.
    """

    def __init__(self):
        self.validator = SignalValidationEngine()
        self.scorer = SignalScoringEngine()
        self.deduplicator = SignalDeduplicator()
        self.drm_decision = DRMDecisionEngine()

    def process(
        self,
        *,
        # Signal data
        symbol: str,
        direction: str,
        entry: float,
        stop_loss: float,
        take_profit: float,
        source: str = "unknown",
        strategy: str = "",
        confidence: float = 0,
        # Market context
        current_price: float = 0,
        atr: float = 0,
        volatility_regime: str = "unknown",
        momentum: str = "neutral",
        # DRM context
        displacement_detected: bool = False,
        displacement_atr_multiple: float = 0,
        fvg_present: bool = False,
        fvg_fill_pct: float = 0,
        unfilled_fvg_count: int = 0,
        # Config
        allowed_symbols: list[str] = None,
        data_timestamp: str = "",
        # Sentiment
        sentiment_aligned: bool = False,
        sentiment_available: bool = False,
    ) -> dict:
        """Run full signal intelligence pipeline. Returns processed result."""

        # ── Step 1: Validate ──────────────────────────────────
        validation = self.validator.validate(
            symbol=symbol, direction=direction, entry=entry,
            stop_loss=stop_loss, take_profit=take_profit,
            current_price=current_price, atr=atr,
            source=source, strategy=strategy,
            allowed_symbols=allowed_symbols,
            data_timestamp=data_timestamp, confidence=confidence,
        )

        if not validation["valid"]:
            return {
                "valid": False,
                "classification": "invalid",
                "score_total": 0,
                "validation": validation,
                "scoring": None,
                "dedup": None,
                "action": "reject",
                "rejection_reason": validation["rejection_reason"],
                "why_tradable": [],
                "why_not_tradable": validation["hard_failures"],
            }

        # ── Step 2: Dedup ─────────────────────────────────────
        dedup = self.deduplicator.check(
            symbol=symbol, direction=direction, strategy=strategy,
            entry=entry, stop_loss=stop_loss, take_profit=take_profit,
        )

        if dedup["action"] == "suppress":
            return {
                "valid": True,
                "classification": "rejected",
                "score_total": 0,
                "validation": validation,
                "scoring": None,
                "dedup": dedup,
                "action": "suppress",
                "rejection_reason": f"Duplicate signal suppressed (seen {dedup['duplicate_count']}x)",
                "why_tradable": [],
                "why_not_tradable": [f"Duplicate spam — seen {dedup['duplicate_count']} times in window"],
            }

        # ── Step 3: Score ─────────────────────────────────────
        normalized = validation.get("normalized_fields", {})
        rr = normalized.get("risk_reward", 0)

        scoring = self.scorer.score(
            validation_result=validation,
            displacement_detected=displacement_detected,
            displacement_atr_multiple=displacement_atr_multiple,
            fvg_present=fvg_present,
            fvg_fill_pct=fvg_fill_pct,
            unfilled_fvg_count=unfilled_fvg_count,
            volatility_regime=volatility_regime,
            momentum=momentum,
            momentum_aligned=(momentum.lower().startswith("bull") and direction.lower() in ("long", "buy"))
                          or (momentum.lower().startswith("bear") and direction.lower() in ("short", "sell")),
            risk_reward=rr,
            source=source,
            data_age_seconds=normalized.get("data_age_seconds", 0),
            is_duplicate=dedup["is_duplicate"],
            duplicate_count=dedup.get("duplicate_count", 0),
            sentiment_aligned=sentiment_aligned,
            sentiment_available=sentiment_available,
        )

        # ── Step 4: Classification ────────────────────────────
        classification = scoring["classification"]
        if dedup["is_duplicate"] and classification == "actionable":
            classification = "candidate"  # downgrade duplicates

        review_required = classification in ("candidate", "low_confidence") or dedup["is_duplicate"]

        return {
            "valid": True,
            "classification": classification,
            "score_total": scoring["score_total"],
            "score_components": scoring["score_components"],
            "validation": validation,
            "scoring": scoring,
            "dedup": dedup,
            "action": "create" if classification in ("actionable", "candidate") else "reject",
            "rejection_reason": None if classification in ("actionable", "candidate") else f"Score too low: {scoring['score_total']}",
            "why_tradable": scoring.get("why_tradable", []),
            "why_not_tradable": scoring.get("why_not_tradable", []),
            "review_required": review_required,
            "fingerprint": dedup["fingerprint"],
            "freshness": "fresh" if normalized.get("data_age_seconds", 999) < 300 else "stale",
        }


# ── Singletons ────────────────────────────────────────────────────

_pipeline = SignalIntelligencePipeline()


def get_signal_pipeline() -> SignalIntelligencePipeline:
    return _pipeline
