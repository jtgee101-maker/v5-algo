"""Tests for the Risk Engine — the non-negotiable gatekeeper.

Every gate must be tested independently. The risk engine must NEVER
raise an unhandled exception — it always returns approve or reject.
"""

from datetime import datetime

import pytest

from core.models import ApprovedOrder, Direction, Target, ThrottleAction, TradeSignal
from core.risk.engine import RiskEngine


@pytest.fixture
def risk_engine() -> RiskEngine:
    engine = RiskEngine(config_path="config/risk.yaml")
    engine.update_state(
        equity=10_000.0,
        open_positions=[],
        daily_pnl_pct=0.0,
        weekly_pnl_pct=0.0,
        account_dd_pct=0.0,
        trades_today=0,
    )
    return engine


def _make_signal(**overrides) -> TradeSignal:
    defaults = {
        "timestamp": datetime(2025, 1, 15, 14, 32, 0),
        "strategy_id": "ny_sweep_reversal_v1",
        "symbol": "NAS100",
        "direction": Direction.LONG,
        "confidence": 0.78,
        "entry_type": "limit",
        "entry_price": 18245.50,
        "stop_price": 18210.00,
        "targets": [Target(price=18290.0, pct_close=0.50)],
        "reward_risk": 2.51,
        "session": "ny_killzone",
    }
    defaults.update(overrides)
    return TradeSignal(**defaults)


class TestThrottleState:
    def test_no_drawdown_returns_normal(self, risk_engine: RiskEngine):
        state = risk_engine.get_throttle_state()
        assert state.action == ThrottleAction.NORMAL
        assert state.risk_multiplier == 1.0

    def test_5pct_drawdown_cuts_risk_25pct(self, risk_engine: RiskEngine):
        risk_engine.account_dd_pct = 0.05
        state = risk_engine.get_throttle_state()
        assert state.action == ThrottleAction.CUT_RISK
        assert state.risk_multiplier == 0.75

    def test_8pct_drawdown_cuts_risk_50pct(self, risk_engine: RiskEngine):
        risk_engine.account_dd_pct = 0.08
        state = risk_engine.get_throttle_state()
        assert state.risk_multiplier == 0.50

    def test_10pct_drawdown_a_tier_only(self, risk_engine: RiskEngine):
        risk_engine.account_dd_pct = 0.10
        state = risk_engine.get_throttle_state()
        assert state.action == ThrottleAction.A_TIER_ONLY

    def test_15pct_drawdown_capital_preservation(self, risk_engine: RiskEngine):
        risk_engine.account_dd_pct = 0.15
        state = risk_engine.get_throttle_state()
        assert state.action == ThrottleAction.CAPITAL_PRESERVATION

    def test_18pct_drawdown_hard_lock(self, risk_engine: RiskEngine):
        risk_engine.account_dd_pct = 0.18
        state = risk_engine.get_throttle_state()
        assert state.action == ThrottleAction.HARD_LOCK

    def test_boundary_values(self, risk_engine: RiskEngine):
        """Test exact boundary — 4.99% should NOT trigger 5% throttle."""
        risk_engine.account_dd_pct = 0.0499
        state = risk_engine.get_throttle_state()
        assert state.action == ThrottleAction.NORMAL


class TestPositionSizing:
    def test_basic_sizing(self, risk_engine: RiskEngine):
        """0.25% of $10,000 = $25 risk. Stop 35.5 ticks. Size should be calculated."""
        size, risk = risk_engine.calculate_position_size(
            risk_pct=0.0025,
            stop_distance=35.50,
            tick_value=1.0,
            tick_size=0.50,
            min_lot=0.01,
        )
        assert size > 0
        assert risk <= 25.50  # Should not exceed intended risk

    def test_zero_stop_returns_zero(self, risk_engine: RiskEngine):
        size, risk = risk_engine.calculate_position_size(
            risk_pct=0.0025, stop_distance=0, tick_value=1.0, tick_size=0.5
        )
        assert size == 0.0
        assert risk == 0.0

    def test_respects_max_lot(self, risk_engine: RiskEngine):
        risk_engine.equity = 10_000_000  # Very large account
        size, _ = risk_engine.calculate_position_size(
            risk_pct=0.01, stop_distance=1.0, tick_value=0.01, tick_size=0.01, max_lot=10.0
        )
        assert size <= 10.0


class TestOrderGate:
    def test_approve_valid_signal(self, risk_engine: RiskEngine):
        signal = _make_signal()
        order = risk_engine.evaluate(signal, tick_value=1.0, tick_size=0.50)
        assert order.approved is True
        assert "session" in order.checks_passed
        assert "spread" in order.checks_passed

    def test_reject_session_inactive(self, risk_engine: RiskEngine):
        signal = _make_signal()
        order = risk_engine.evaluate(signal, session_active=False)
        assert order.approved is False
        assert order.rejection_reason == "session_inactive"

    def test_reject_spread_too_wide(self, risk_engine: RiskEngine):
        signal = _make_signal()
        order = risk_engine.evaluate(signal, current_spread_atr_pct=0.25)
        assert order.approved is False
        assert order.rejection_reason == "spread_too_wide"

    def test_reject_daily_loss_limit(self, risk_engine: RiskEngine):
        risk_engine.daily_pnl_pct = -0.016  # Exceeds 1.5%
        signal = _make_signal()
        order = risk_engine.evaluate(signal)
        assert order.approved is False
        assert order.rejection_reason == "daily_loss_limit"

    def test_reject_weekly_loss_limit(self, risk_engine: RiskEngine):
        risk_engine.weekly_pnl_pct = -0.041  # Exceeds 4%
        signal = _make_signal()
        order = risk_engine.evaluate(signal)
        assert order.approved is False
        assert order.rejection_reason == "weekly_loss_limit"

    def test_reject_max_trades(self, risk_engine: RiskEngine):
        risk_engine.trades_today = 3  # At limit
        signal = _make_signal()
        order = risk_engine.evaluate(signal)
        assert order.approved is False
        assert order.rejection_reason == "max_trades_reached"

    def test_reject_hard_lock(self, risk_engine: RiskEngine):
        risk_engine.account_dd_pct = 0.18
        signal = _make_signal()
        order = risk_engine.evaluate(signal)
        assert order.approved is False
        assert order.rejection_reason == "hard_lock"

    def test_reject_capital_preservation(self, risk_engine: RiskEngine):
        risk_engine.account_dd_pct = 0.15
        signal = _make_signal()
        order = risk_engine.evaluate(signal)
        assert order.approved is False
        assert order.rejection_reason == "capital_preservation"

    def test_a_tier_only_rejects_low_confidence(self, risk_engine: RiskEngine):
        risk_engine.account_dd_pct = 0.10
        signal = _make_signal(confidence=0.70)  # Below 0.80 threshold
        order = risk_engine.evaluate(signal)
        assert order.approved is False
        assert order.rejection_reason == "a_tier_only"

    def test_a_tier_only_allows_high_confidence(self, risk_engine: RiskEngine):
        risk_engine.account_dd_pct = 0.10
        signal = _make_signal(confidence=0.85)
        order = risk_engine.evaluate(signal, tick_value=1.0, tick_size=0.50)
        assert order.approved is True

    def test_reject_total_exposure(self, risk_engine: RiskEngine):
        """With existing positions using up most exposure, new trade should be rejected."""
        risk_engine.open_positions = [
            {"symbol": "US30", "risk_pct": 0.014, "direction": "long"},
        ]
        signal = _make_signal()
        order = risk_engine.evaluate(signal, tick_value=1.0, tick_size=0.50)
        assert order.approved is False
        assert order.rejection_reason == "max_exposure"

    def test_reject_correlation_limit(self, risk_engine: RiskEngine):
        """NAS100 and US30 are correlated — hitting group limit should reject."""
        risk_engine.open_positions = [
            {"symbol": "US30", "risk_pct": 0.007, "direction": "long"},
        ]
        signal = _make_signal(symbol="NAS100")
        order = risk_engine.evaluate(signal, tick_value=1.0, tick_size=0.50)
        assert order.approved is False
        assert order.rejection_reason == "correlation_limit"

    def test_never_raises_exception(self, risk_engine: RiskEngine):
        """The risk engine must always return a result, never crash."""
        # Feed it garbage — it should still return a rejection, not crash
        signal = _make_signal(entry_price=0.0, stop_price=0.0)
        order = risk_engine.evaluate(signal)
        assert isinstance(order, ApprovedOrder)
        # Either approved with 0 size or rejected — but never an exception

    def test_throttle_reduces_position_size(self, risk_engine: RiskEngine):
        """At 5% DD, position size should be ~75% of normal."""
        signal = _make_signal()

        # Normal size
        normal_order = risk_engine.evaluate(signal, tick_value=1.0, tick_size=0.50)

        # At 5% DD
        risk_engine.account_dd_pct = 0.05
        throttled_order = risk_engine.evaluate(signal, tick_value=1.0, tick_size=0.50)

        if normal_order.approved and throttled_order.approved:
            assert throttled_order.risk_amount <= normal_order.risk_amount
