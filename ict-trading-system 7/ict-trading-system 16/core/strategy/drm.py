"""Displacement Rebalance Model (DRM) — Your Edge, Encoded.

Based on actual $23K USOIL trade:
  Entry zone: 90.89 - 91.54 (mid-imbalance reclaim)
  Exit zone: 92.1 - 92.4 (sell-side liquidity)
  Method: Layered entries inside FVG after violent displacement

This module detects:
1. Violent displacement candles (ATR multiplier threshold)
2. Fair value gaps / imbalance zones left behind
3. Rebalance entry zones (mid-imbalance)
4. Liquidity targets (prior consolidation, trapped positions)
5. Barrier-touch probabilities (BlackRock-style math)

Your checklist (from your actual trades):
  ✅ Violent displacement (large candle / news move)
  ✅ Liquidity vacuum created (thin zones, inefficient prints)
  ✅ Price returns to rebalance (NOT immediately trend)
  ✅ Enter inside imbalance (not at extremes)
  ✅ Exit into opposing liquidity (not hold and hope)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


@dataclass
class Candle:
    t: str
    o: float
    h: float
    l: float
    c: float
    v: float = 0

    @property
    def body(self) -> float:
        return abs(self.c - self.o)

    @property
    def range(self) -> float:
        return self.h - self.l

    @property
    def is_bullish(self) -> bool:
        return self.c > self.o

    @property
    def mid(self) -> float:
        return (self.h + self.l) / 2


@dataclass
class FairValueGap:
    """A 3-candle imbalance zone where price moved too fast."""
    high: float          # Top of the gap
    low: float           # Bottom of the gap
    mid: float           # Midpoint — your entry zone
    direction: str       # "bullish" (gap below) or "bearish" (gap above)
    displacement_size: float  # How big the move was
    candle_index: int    # Which candle created it
    filled: bool = False
    fill_pct: float = 0.0

    @property
    def size(self) -> float:
        return self.high - self.low


@dataclass
class DisplacementEvent:
    """A violent price move that creates tradeable imbalance."""
    direction: str       # "up" or "down"
    start_price: float
    end_price: float
    displacement_atr: float  # How many ATRs the move was
    candle_count: int    # How many candles the move took
    fvgs: list[FairValueGap] = field(default_factory=list)
    timestamp: str = ""


@dataclass
class DRMSignal:
    """A complete Displacement Rebalance Model signal."""
    symbol: str
    bias: str            # "long" (buy rebalance up) or "short" (sell rebalance down)
    confidence: str      # "high", "medium", "low"
    conf_score: int

    # The displacement
    displacement: DisplacementEvent

    # Entry zone (mid-imbalance)
    entry_zone_high: float
    entry_zone_low: float
    entry_ideal: float   # Midpoint of imbalance

    # Exit targets (liquidity)
    target_1: float      # Conservative — partial fill
    target_2: float      # Full — liquidity sweep

    # Risk
    stop_loss: float
    risk_reward: float

    # Reasoning
    reasoning: list[str] = field(default_factory=list)

    # Probabilities
    touch_prob_target: float = 0.0
    touch_prob_stop: float = 0.0


class DRMEngine:
    """Detects Displacement Rebalance setups from candle data.

    This is YOUR edge — not generic TA. It finds:
    1. Where price moved too fast (displacement)
    2. What gaps were left behind (FVGs)
    3. Where to enter (mid-imbalance)
    4. Where to exit (opposing liquidity)
    """

    def __init__(
        self,
        atr_period: int = 14,
        displacement_threshold: float = 2.0,  # Candle must be 2x ATR
        fvg_min_size_atr: float = 0.3,        # FVG must be > 0.3 ATR
    ):
        self.atr_period = atr_period
        self.displacement_threshold = displacement_threshold
        self.fvg_min_size_atr = fvg_min_size_atr

    def analyze(self, symbol: str, candles_raw: list[dict]) -> dict[str, Any]:
        """Full DRM analysis on candle data.

        Returns: displacement events, FVGs, entry zones, signals, probabilities.
        """
        if len(candles_raw) < self.atr_period + 5:
            return {"symbol": symbol, "error": "insufficient candle data",
                    "min_required": self.atr_period + 5, "received": len(candles_raw)}

        candles = [Candle(**c) if isinstance(c, dict) else c for c in candles_raw]
        atr = self._calc_atr(candles)
        current_price = candles[-1].c

        # Find displacement events
        displacements = self._find_displacements(candles, atr)

        # Find fair value gaps
        fvgs = self._find_fvgs(candles, atr)

        # Check which FVGs have been filled
        for fvg in fvgs:
            self._check_fvg_fill(fvg, candles, fvg.candle_index)

        # Find unfilled FVGs (the opportunity)
        unfilled = [f for f in fvgs if not f.filled and f.fill_pct < 0.5]

        # Volatility regime
        vol_regime = "extreme" if atr > current_price * 0.05 else \
                     "high" if atr > current_price * 0.02 else \
                     "normal" if atr > current_price * 0.008 else "low"

        # Generate DRM signals
        signals = self._generate_signals(symbol, candles, atr, displacements, unfilled, current_price)

        # Barrier probabilities for each signal
        for sig in signals:
            sig.touch_prob_target = self._barrier_touch_prob(
                current_price, sig.target_1, atr, days=3)
            sig.touch_prob_stop = self._barrier_touch_prob(
                current_price, sig.stop_loss, atr, days=3)

        return {
            "symbol": symbol,
            "current_price": current_price,
            "atr": round(atr, 4),
            "volatility_regime": vol_regime,
            "displacements": [
                {
                    "direction": d.direction,
                    "start": d.start_price,
                    "end": d.end_price,
                    "atr_multiple": round(d.displacement_atr, 2),
                    "candles": d.candle_count,
                    "fvg_count": len(d.fvgs),
                }
                for d in displacements[-5:]  # Last 5
            ],
            "fair_value_gaps": [
                {
                    "high": round(f.high, 4),
                    "low": round(f.low, 4),
                    "mid": round(f.mid, 4),
                    "size": round(f.size, 4),
                    "direction": f.direction,
                    "filled": f.filled,
                    "fill_pct": round(f.fill_pct * 100, 1),
                }
                for f in fvgs[-10:]  # Last 10
            ],
            "unfilled_fvgs": len(unfilled),
            "signals": [
                {
                    "bias": s.bias,
                    "confidence": s.confidence,
                    "conf_score": s.conf_score,
                    "entry_zone": {"high": round(s.entry_zone_high, 4),
                                   "low": round(s.entry_zone_low, 4),
                                   "ideal": round(s.entry_ideal, 4)},
                    "targets": {"t1": round(s.target_1, 4), "t2": round(s.target_2, 4)},
                    "stop_loss": round(s.stop_loss, 4),
                    "risk_reward": round(s.risk_reward, 2),
                    "touch_prob_target": round(s.touch_prob_target * 100, 1),
                    "touch_prob_stop": round(s.touch_prob_stop * 100, 1),
                    "reasoning": s.reasoning,
                }
                for s in signals
            ],
        }

    def _calc_atr(self, candles: list[Candle]) -> float:
        """Average True Range."""
        trs = []
        for i in range(1, len(candles)):
            tr = max(
                candles[i].h - candles[i].l,
                abs(candles[i].h - candles[i-1].c),
                abs(candles[i].l - candles[i-1].c),
            )
            trs.append(tr)

        if len(trs) < self.atr_period:
            return sum(trs) / len(trs) if trs else 0

        # Wilder's smoothing
        atr = sum(trs[:self.atr_period]) / self.atr_period
        for tr in trs[self.atr_period:]:
            atr = (atr * (self.atr_period - 1) + tr) / self.atr_period
        return atr

    def _find_displacements(self, candles: list[Candle], atr: float) -> list[DisplacementEvent]:
        """Find candles with body > threshold * ATR (violent moves)."""
        events = []
        if atr <= 0:
            return events

        for i in range(1, len(candles)):
            c = candles[i]
            if c.body > atr * self.displacement_threshold:
                direction = "up" if c.is_bullish else "down"
                event = DisplacementEvent(
                    direction=direction,
                    start_price=c.o,
                    end_price=c.c,
                    displacement_atr=round(c.body / atr, 2),
                    candle_count=1,
                    timestamp=c.t,
                )
                events.append(event)

        return events

    def _find_fvgs(self, candles: list[Candle], atr: float) -> list[FairValueGap]:
        """Find 3-candle fair value gaps (your bread and butter)."""
        fvgs = []
        if atr <= 0:
            return fvgs

        for i in range(2, len(candles)):
            c1, c2, c3 = candles[i-2], candles[i-1], candles[i]

            # Bullish FVG: candle 3's low > candle 1's high
            # (gap up that wasn't filled)
            if c3.l > c1.h:
                gap_size = c3.l - c1.h
                if gap_size > atr * self.fvg_min_size_atr:
                    fvgs.append(FairValueGap(
                        high=c3.l,
                        low=c1.h,
                        mid=(c3.l + c1.h) / 2,
                        direction="bullish",
                        displacement_size=c2.body,
                        candle_index=i,
                    ))

            # Bearish FVG: candle 3's high < candle 1's low
            # (gap down that wasn't filled)
            if c3.h < c1.l:
                gap_size = c1.l - c3.h
                if gap_size > atr * self.fvg_min_size_atr:
                    fvgs.append(FairValueGap(
                        high=c1.l,
                        low=c3.h,
                        mid=(c1.l + c3.h) / 2,
                        direction="bearish",
                        displacement_size=c2.body,
                        candle_index=i,
                    ))

        return fvgs

    def _check_fvg_fill(self, fvg: FairValueGap, candles: list[Candle], start_idx: int) -> None:
        """Check how much of a FVG has been filled by subsequent price action."""
        for i in range(start_idx + 1, len(candles)):
            c = candles[i]
            if fvg.direction == "bullish":
                # Price needs to come DOWN into the gap
                if c.l <= fvg.low:
                    fvg.filled = True
                    fvg.fill_pct = 1.0
                    return
                elif c.l < fvg.high:
                    fill = (fvg.high - c.l) / fvg.size
                    fvg.fill_pct = max(fvg.fill_pct, fill)
            else:
                # Price needs to come UP into the gap
                if c.h >= fvg.high:
                    fvg.filled = True
                    fvg.fill_pct = 1.0
                    return
                elif c.h > fvg.low:
                    fill = (c.h - fvg.low) / fvg.size
                    fvg.fill_pct = max(fvg.fill_pct, fill)

    def _generate_signals(
        self, symbol: str, candles: list[Candle], atr: float,
        displacements: list[DisplacementEvent],
        unfilled_fvgs: list[FairValueGap],
        current_price: float,
    ) -> list[DRMSignal]:
        """Generate DRM signals from unfilled FVGs near current price."""
        signals = []

        for fvg in unfilled_fvgs:
            # Is current price near this FVG?
            distance = abs(current_price - fvg.mid)
            if distance > atr * 3:
                continue  # Too far away

            # Determine bias
            if fvg.direction == "bearish":
                # Bearish FVG = gap down. Price should come UP to fill → LONG
                bias = "long"
                entry_zone_low = fvg.low
                entry_zone_high = fvg.mid  # Enter in lower half
                entry_ideal = fvg.mid
                stop_loss = fvg.low - atr * 0.5
                target_1 = fvg.high  # Fill the gap
                target_2 = fvg.high + atr  # Liquidity above
            else:
                # Bullish FVG = gap up. Price should come DOWN to fill → SHORT
                bias = "short"
                entry_zone_low = fvg.mid
                entry_zone_high = fvg.high
                entry_ideal = fvg.mid
                stop_loss = fvg.high + atr * 0.5
                target_1 = fvg.low  # Fill the gap
                target_2 = fvg.low - atr  # Liquidity below

            # Risk/reward
            risk = abs(entry_ideal - stop_loss)
            reward = abs(target_1 - entry_ideal)
            rr = reward / risk if risk > 0 else 0

            # Build reasoning
            reasoning = []
            conf = 0

            # Check displacement size
            if fvg.displacement_size > atr * 2:
                reasoning.append(f"Violent displacement ({fvg.displacement_size/atr:.1f}x ATR)")
                conf += 2
            elif fvg.displacement_size > atr:
                reasoning.append(f"Strong displacement ({fvg.displacement_size/atr:.1f}x ATR)")
                conf += 1

            # FVG size
            if fvg.size > atr * 0.5:
                reasoning.append(f"Large imbalance zone ({fvg.size:.2f} = {fvg.size/atr:.1f}x ATR)")
                conf += 1

            # Unfilled
            reasoning.append(f"FVG {100-fvg.fill_pct*100:.0f}% unfilled — rebalance expected")
            conf += 1

            # Price proximity
            if distance < atr:
                reasoning.append(f"Price within 1 ATR of entry zone")
                conf += 1

            # R:R quality
            if rr > 2:
                reasoning.append(f"Excellent R:R ratio ({rr:.1f}:1)")
                conf += 1
            elif rr > 1.5:
                reasoning.append(f"Good R:R ratio ({rr:.1f}:1)")

            # Recent displacement nearby
            recent_disp = [d for d in displacements[-3:] if d.displacement_atr > 2]
            if recent_disp:
                reasoning.append(f"Recent violent displacement confirms imbalance")
                conf += 1

            confidence = "high" if conf >= 5 else "medium" if conf >= 3 else "low"

            signals.append(DRMSignal(
                symbol=symbol,
                bias=bias,
                confidence=confidence,
                conf_score=conf,
                displacement=displacements[-1] if displacements else DisplacementEvent("", 0, 0, 0, 0),
                entry_zone_high=entry_zone_high,
                entry_zone_low=entry_zone_low,
                entry_ideal=entry_ideal,
                target_1=target_1,
                target_2=target_2,
                stop_loss=stop_loss,
                risk_reward=rr,
                reasoning=reasoning,
                touch_prob_target=0,
                touch_prob_stop=0,
            ))

        return signals

    def _barrier_touch_prob(
        self, current: float, target: float, atr: float, days: int = 3,
    ) -> float:
        """Simplified barrier-touch probability (BlackRock-style).

        Uses ATR-derived daily sigma and zero-drift barrier model.
        P(touch) ≈ erfc(distance / (sigma * sqrt(days) * sqrt(2)))

        From the analysis: σ ≈ ATR / 1.596
        """
        if atr <= 0 or days <= 0:
            return 0

        daily_sigma = atr / 1.596
        distance = abs(target - current)
        multi_day_sigma = daily_sigma * math.sqrt(days)

        if multi_day_sigma <= 0:
            return 0

        # erfc approximation for barrier touch
        z = distance / (multi_day_sigma * math.sqrt(2))
        prob = math.erfc(z)
        return min(max(prob, 0), 1)


# Singleton
_drm = DRMEngine()

def get_drm_engine() -> DRMEngine:
    return _drm
