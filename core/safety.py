"""Safety modules — integrated from Byte-Ventures/claude-trader patterns.

Three layered safety systems that run BEFORE the risk engine:
1. CircuitBreaker — pauses trading after consecutive losses
2. TradeCooldown — enforces minimum time between trades
3. HotConfig — reload config without restart

These supplement (not replace) the existing risk engine.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)


class CircuitBreaker:
    """Halts trading after N consecutive losses.

    Pattern from claude-trader/src/safety/circuit_breaker.py.
    Trips when consecutive_losses >= threshold.
    Auto-resets after cooldown_minutes.
    """

    def __init__(
        self,
        max_consecutive_losses: int = 3,
        cooldown_minutes: int = 30,
    ):
        self.max_consecutive_losses = max_consecutive_losses
        self.cooldown_minutes = cooldown_minutes
        self.consecutive_losses = 0
        self.tripped = False
        self.tripped_at: Optional[float] = None
        self.total_trips = 0

    def record_trade(self, pnl: float) -> None:
        """Record a trade result. Trips breaker on consecutive losses."""
        if pnl < 0:
            self.consecutive_losses += 1
            if self.consecutive_losses >= self.max_consecutive_losses and not self.tripped:
                self.tripped = True
                self.tripped_at = time.time()
                self.total_trips += 1
                logger.warning(
                    "circuit_breaker.tripped",
                    consecutive_losses=self.consecutive_losses,
                    cooldown_minutes=self.cooldown_minutes,
                )
        else:
            self.consecutive_losses = 0
            # Don't auto-reset on win if still in cooldown

    def is_blocked(self) -> tuple[bool, str]:
        """Check if trading is blocked."""
        if not self.tripped:
            return False, ""

        # Check if cooldown expired
        elapsed = time.time() - (self.tripped_at or 0)
        remaining = (self.cooldown_minutes * 60) - elapsed

        if remaining <= 0:
            self.tripped = False
            self.tripped_at = None
            self.consecutive_losses = 0
            logger.info("circuit_breaker.reset", reason="cooldown_expired")
            return False, ""

        return True, f"Circuit breaker: {self.consecutive_losses} consecutive losses. Resumes in {int(remaining/60)}m"

    def force_reset(self) -> None:
        """Manual reset by operator."""
        self.tripped = False
        self.tripped_at = None
        self.consecutive_losses = 0
        logger.info("circuit_breaker.force_reset")

    def status(self) -> dict[str, Any]:
        return {
            "tripped": self.tripped,
            "consecutive_losses": self.consecutive_losses,
            "max_consecutive_losses": self.max_consecutive_losses,
            "cooldown_minutes": self.cooldown_minutes,
            "total_trips": self.total_trips,
            "tripped_at": datetime.fromtimestamp(self.tripped_at, tz=timezone.utc).isoformat() if self.tripped_at else None,
        }


class TradeCooldown:
    """Enforces minimum time between trades per symbol.

    Pattern from claude-trader/src/safety/trade_cooldown.py.
    Prevents overtrading and revenge trading.
    """

    def __init__(self, cooldown_seconds: int = 300):  # 5 min default
        self.cooldown_seconds = cooldown_seconds
        self._last_trade: dict[str, float] = {}  # symbol → timestamp

    def record_trade(self, symbol: str) -> None:
        self._last_trade[symbol] = time.time()

    def is_blocked(self, symbol: str) -> tuple[bool, str]:
        last = self._last_trade.get(symbol)
        if last is None:
            return False, ""

        elapsed = time.time() - last
        remaining = self.cooldown_seconds - elapsed

        if remaining <= 0:
            return False, ""

        return True, f"Cooldown: {symbol} traded {int(elapsed)}s ago. Wait {int(remaining)}s"

    def status(self) -> dict[str, Any]:
        now = time.time()
        return {
            "cooldown_seconds": self.cooldown_seconds,
            "active_cooldowns": {
                sym: {
                    "last_trade_seconds_ago": int(now - ts),
                    "remaining_seconds": max(0, self.cooldown_seconds - int(now - ts)),
                }
                for sym, ts in self._last_trade.items()
                if now - ts < self.cooldown_seconds
            },
        }


class ATRPositionSizer:
    """ATR-based position sizing — from claude-trader/src/strategy/position_sizer.py.

    Instead of flat risk %, uses ATR to calculate dynamic stop distance
    and position size. More conservative in volatile markets, more
    aggressive in quiet ones.
    """

    def __init__(
        self,
        risk_pct: float = 0.0025,  # 0.25% of account
        atr_multiplier: float = 1.5,
        max_position_pct: float = 0.05,  # Max 5% of account in one position
    ):
        self.risk_pct = risk_pct
        self.atr_multiplier = atr_multiplier
        self.max_position_pct = max_position_pct

    def calculate(
        self,
        account_equity: float,
        atr: float,
        entry_price: float,
    ) -> dict[str, float]:
        """Calculate position size and stop based on ATR."""
        risk_amount = account_equity * self.risk_pct
        stop_distance = atr * self.atr_multiplier

        if stop_distance <= 0 or entry_price <= 0:
            return {"quantity": 0, "stop_distance": 0, "risk_amount": 0}

        # Position size = risk_amount / stop_distance
        quantity = risk_amount / stop_distance

        # Cap at max position percentage
        max_quantity = (account_equity * self.max_position_pct) / entry_price
        quantity = min(quantity, max_quantity)

        return {
            "quantity": round(quantity, 4),
            "stop_distance": round(stop_distance, 5),
            "risk_amount": round(risk_amount, 2),
            "risk_pct": self.risk_pct,
            "atr_used": atr,
            "atr_multiplier": self.atr_multiplier,
        }


# ── Singleton instances for use across the app ──────────────────────

_circuit_breaker = CircuitBreaker()
_trade_cooldown = TradeCooldown()
_position_sizer = ATRPositionSizer()


def get_circuit_breaker() -> CircuitBreaker:
    return _circuit_breaker


def get_trade_cooldown() -> TradeCooldown:
    return _trade_cooldown


def get_position_sizer() -> ATRPositionSizer:
    return _position_sizer
