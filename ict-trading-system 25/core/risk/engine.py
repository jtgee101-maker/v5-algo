"""Risk Engine — deterministic order gating.

This module is NON-NEGOTIABLE. Every trade signal must pass through the order gate.
No ML, no vibes, no discretion. Pure rules from config/risk.yaml.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Optional

import structlog
import yaml

from core.models import (
    ApprovedOrder,
    Direction,
    Target,
    ThrottleAction,
    ThrottleState,
    TradeSignal,
)

logger = structlog.get_logger(__name__)


class RiskEngine:
    """Deterministic risk gate for all trade signals."""

    def __init__(self, config_path: str = "config/risk.yaml"):
        with open(config_path) as f:
            self.config = yaml.safe_load(f)

        self.base = self.config["base_risk"]
        self.limits = self.config["limits"]
        self.correlation_groups = self.config["correlation_groups"]
        self.throttle_levels = self.config["throttle_levels"]

        # State tracking (updated externally by execution engine)
        self.equity: float = 0.0
        self.open_positions: list[dict] = []
        self.daily_pnl_pct: float = 0.0
        self.weekly_pnl_pct: float = 0.0
        self.account_dd_pct: float = 0.0
        self.trades_today: int = 0

    # ── Drawdown Throttle ──────────────────────────────────────────────────

    def get_throttle_state(self) -> ThrottleState:
        """Determine current throttle level based on account drawdown."""
        active_level = None
        for level in self.throttle_levels:
            if self.account_dd_pct >= level["dd_pct"]:
                active_level = level

        if active_level is None:
            return ThrottleState(
                risk_multiplier=1.0,
                action=ThrottleAction.NORMAL,
                current_dd_pct=self.account_dd_pct,
            )

        action_str = active_level.get("action", "cut_risk")
        try:
            action = ThrottleAction(action_str)
        except ValueError:
            action = ThrottleAction.CUT_RISK

        reduction = active_level.get("risk_reduction", 0.0)

        return ThrottleState(
            risk_multiplier=max(0.0, 1.0 - reduction),
            action=action,
            current_dd_pct=self.account_dd_pct,
        )

    # ── Position Sizing ────────────────────────────────────────────────────

    def calculate_position_size(
        self,
        risk_pct: float,
        stop_distance: float,
        tick_value: float,
        tick_size: float,
        min_lot: float = 0.01,
        max_lot: float = 100.0,
    ) -> tuple[float, float]:
        """Calculate position size from risk parameters.

        Returns (lots, actual_risk_amount).
        """
        if stop_distance <= 0 or tick_size <= 0 or tick_value <= 0:
            return 0.0, 0.0

        risk_amount = self.equity * risk_pct
        ticks_at_risk = stop_distance / tick_size
        raw_size = risk_amount / (ticks_at_risk * tick_value)

        # Round DOWN to min_lot increment
        if min_lot > 0:
            size = math.floor(raw_size / min_lot) * min_lot
        else:
            size = raw_size

        size = min(size, max_lot)
        size = max(size, 0.0)

        actual_risk = size * ticks_at_risk * tick_value if size > 0 else 0.0
        return round(size, 8), round(actual_risk, 2)

    # ── Exposure Checks ────────────────────────────────────────────────────

    def _get_total_open_risk_pct(self) -> float:
        """Sum risk % of all currently open positions."""
        return sum(p.get("risk_pct", 0.0) for p in self.open_positions)

    def _get_correlated_risk_pct(self, symbol: str) -> float:
        """Sum risk % of open positions in the same correlation group."""
        group_symbols = set()
        for group_name, symbols in self.correlation_groups.items():
            if symbol in symbols:
                group_symbols.update(symbols)

        if not group_symbols:
            return 0.0

        return sum(
            p.get("risk_pct", 0.0)
            for p in self.open_positions
            if p.get("symbol") in group_symbols
        )

    def _get_symbol_risk_pct(self, symbol: str) -> float:
        """Sum risk % for a specific symbol."""
        return sum(
            p.get("risk_pct", 0.0)
            for p in self.open_positions
            if p.get("symbol") == symbol
        )

    # ── Order Gate ─────────────────────────────────────────────────────────

    def evaluate(
        self,
        signal: TradeSignal,
        tick_value: float = 1.0,
        tick_size: float = 0.01,
        min_lot: float = 0.01,
        max_lot: float = 100.0,
        current_spread_atr_pct: float = 0.0,
        session_active: bool = True,
    ) -> ApprovedOrder:
        """Run the full risk gate on a trade signal.

        Returns ApprovedOrder with approved=True or approved=False + reason.
        """
        checks_passed: list[str] = []
        signal_ref = f"signal_{signal.symbol}_{signal.timestamp.isoformat()}"

        def reject(reason: str, detail: str) -> ApprovedOrder:
            logger.warning("risk.rejected", reason=reason, detail=detail, symbol=signal.symbol)
            throttle = self.get_throttle_state()
            return ApprovedOrder(
                approved=False,
                signal_ref=signal_ref,
                symbol=signal.symbol,
                direction=signal.direction,
                rejection_reason=reason,
                rejection_detail=detail,
                throttle_state=throttle.action,
                timestamp=datetime.utcnow(),
            )

        # 1. Hard lock check
        throttle = self.get_throttle_state()
        if throttle.action == ThrottleAction.HARD_LOCK:
            return reject("hard_lock", f"Account DD at {self.account_dd_pct:.1%} — hard lock active")

        # 2. Capital preservation
        if throttle.action == ThrottleAction.CAPITAL_PRESERVATION:
            return reject("capital_preservation", f"DD at {self.account_dd_pct:.1%} — no new trades")

        # 3. Session check
        if not session_active:
            return reject("session_inactive", "NY session is not active")
        checks_passed.append("session")

        # 4. Spread check
        if current_spread_atr_pct > self.limits["max_spread_atr_pct"]:
            return reject(
                "spread_too_wide",
                f"Spread {current_spread_atr_pct:.2%} > limit {self.limits['max_spread_atr_pct']:.2%}",
            )
        checks_passed.append("spread")

        # 5. Daily trade count
        if self.trades_today >= self.limits["max_trades_per_day"]:
            return reject("max_trades_reached", f"Already {self.trades_today} trades today")
        checks_passed.append("trade_count")

        # 6. Daily loss
        if self.daily_pnl_pct <= -self.limits["max_daily_loss"]:
            return reject(
                "daily_loss_limit",
                f"Daily P&L {self.daily_pnl_pct:.2%} exceeds limit {-self.limits['max_daily_loss']:.2%}",
            )
        checks_passed.append("daily_loss")

        # 7. Weekly loss
        if self.weekly_pnl_pct <= -self.limits["max_weekly_loss"]:
            return reject(
                "weekly_loss_limit",
                f"Weekly P&L {self.weekly_pnl_pct:.2%} exceeds limit {-self.limits['max_weekly_loss']:.2%}",
            )
        checks_passed.append("weekly_loss")

        # 8. Calculate position size with throttle-adjusted risk
        adjusted_risk = self.base["risk_per_trade"] * throttle.risk_multiplier
        stop_distance = abs(signal.entry_price - signal.stop_price)

        size, risk_amount = self.calculate_position_size(
            risk_pct=adjusted_risk,
            stop_distance=stop_distance,
            tick_value=tick_value,
            tick_size=tick_size,
            min_lot=min_lot,
            max_lot=max_lot,
        )

        if size <= 0:
            return reject("zero_size", "Calculated position size is zero after throttle adjustment")
        checks_passed.append("size")

        actual_risk_pct = risk_amount / self.equity if self.equity > 0 else 0.0

        # 9. Total exposure check
        if self._get_total_open_risk_pct() + actual_risk_pct > self.base["max_simultaneous_risk"]:
            return reject(
                "max_exposure",
                f"Total risk would be {self._get_total_open_risk_pct() + actual_risk_pct:.2%} > {self.base['max_simultaneous_risk']:.2%}",
            )
        checks_passed.append("exposure")

        # 10. Correlation check
        if self._get_correlated_risk_pct(signal.symbol) + actual_risk_pct > self.base["max_correlated_risk"]:
            return reject(
                "correlation_limit",
                f"Correlated risk would exceed {self.base['max_correlated_risk']:.2%}",
            )
        checks_passed.append("correlation")

        # 11. Per-symbol check
        if self._get_symbol_risk_pct(signal.symbol) + actual_risk_pct > self.base["max_per_symbol"]:
            return reject(
                "symbol_limit",
                f"Symbol risk would exceed {self.base['max_per_symbol']:.2%}",
            )
        checks_passed.append("symbol_limit")

        # 12. A-tier only check
        if throttle.action == ThrottleAction.A_TIER_ONLY and signal.confidence < 0.80:
            return reject(
                "a_tier_only",
                f"Throttle requires A-tier setups (>0.80), signal confidence is {signal.confidence:.2f}",
            )
        checks_passed.append("drawdown")

        # ALL PASSED
        logger.info(
            "risk.approved",
            symbol=signal.symbol,
            direction=signal.direction,
            size=size,
            risk_pct=actual_risk_pct,
            throttle=throttle.action,
        )

        return ApprovedOrder(
            approved=True,
            signal_ref=signal_ref,
            symbol=signal.symbol,
            direction=signal.direction,
            entry_type=signal.entry_type,
            entry_price=signal.entry_price,
            stop_price=signal.stop_price,
            targets=signal.targets,
            position_size=size,
            risk_amount=risk_amount,
            risk_pct_actual=actual_risk_pct,
            throttle_state=throttle.action,
            checks_passed=checks_passed,
            timestamp=datetime.utcnow(),
        )

    def update_state(
        self,
        equity: float,
        open_positions: list[dict],
        daily_pnl_pct: float,
        weekly_pnl_pct: float,
        account_dd_pct: float,
        trades_today: int,
    ) -> None:
        """Update the risk engine's view of account state.

        Called by the execution engine before each evaluation.
        """
        self.equity = equity
        self.open_positions = open_positions
        self.daily_pnl_pct = daily_pnl_pct
        self.weekly_pnl_pct = weekly_pnl_pct
        self.account_dd_pct = account_dd_pct
        self.trades_today = trades_today
        logger.debug(
            "risk.state_updated",
            equity=equity,
            dd=account_dd_pct,
            daily_pnl=daily_pnl_pct,
            open_positions=len(open_positions),
        )
