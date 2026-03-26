"""SQLAlchemy ORM models for all persistence tables."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    Column, Float, ForeignKey, Index, Integer, String, Text,
)
from sqlalchemy.orm import relationship

from backend.db.base import Base


def _uuid() -> str:
    return str(uuid4())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Account(Base):
    __tablename__ = "accounts"

    id = Column(String, primary_key=True, default=_uuid)
    broker_name = Column(String, nullable=False)
    account_name = Column(String, nullable=False)
    account_type = Column(String, nullable=False)  # demo, live
    mode = Column(String, nullable=False, default="shadow")  # shadow, demo, live
    balance = Column(Float, nullable=False, default=0)
    equity = Column(Float, nullable=False, default=0)
    margin_used = Column(Float, nullable=False, default=0)
    free_margin = Column(Float, nullable=False, default=0)
    drawdown_pct = Column(Float, nullable=False, default=0)
    status = Column(String, nullable=False, default="disconnected")
    currency = Column(String, default="USD")
    updated_at = Column(String, nullable=False, default=_now_iso)


class MarketStateRecord(Base):
    __tablename__ = "market_states"
    __table_args__ = (
        Index("idx_market_states_symbol_ts", "symbol", "timestamp"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    symbol = Column(String, nullable=False)
    timestamp = Column(String, nullable=False)
    session_name = Column(String)
    session_active = Column(Integer, nullable=False, default=0)
    overnight_range_high = Column(Float)
    overnight_range_low = Column(Float)
    prior_day_high = Column(Float)
    prior_day_low = Column(Float)
    asia_high = Column(Float)
    asia_low = Column(Float)
    weekly_high = Column(Float)
    weekly_low = Column(Float)
    psych_level_nearest = Column(Float)
    smt_flag = Column(Integer, nullable=False, default=0)
    po3_phase = Column(String)
    sweep_detected = Column(Integer, nullable=False, default=0)
    displacement_detected = Column(Integer, nullable=False, default=0)
    bias = Column(String)
    structure_score = Column(Float)
    json_payload = Column(Text, nullable=False, default="{}")


class TradeSignalRecord(Base):
    __tablename__ = "trade_signals"
    __table_args__ = (
        Index("idx_trade_signals_status_ts", "status", "timestamp"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    symbol = Column(String, nullable=False)
    strategy_name = Column(String, nullable=False)
    strategy_version = Column(String)
    timestamp = Column(String, nullable=False)
    side = Column(String, nullable=False)  # buy, sell
    confidence = Column(Float, nullable=False)
    expected_value = Column(Float)
    entry_price = Column(Float, nullable=False)
    stop_price = Column(Float, nullable=False)
    take_profit_1 = Column(Float)
    take_profit_2 = Column(Float)
    take_profit_3 = Column(Float)
    invalidation_reason = Column(String)
    risk_score = Column(Float)
    structure_score = Column(Float)
    confluence_tags = Column(Text)  # JSON array as string
    status = Column(String, nullable=False, default="pending")
    expires_at = Column(String)
    approved_by = Column(String)
    approved_at = Column(String)
    rejected_by = Column(String)
    rejected_at = Column(String)
    rejection_reason = Column(String)
    json_payload = Column(Text, nullable=False, default="{}")

    approved_orders = relationship("ApprovedOrderRecord", back_populates="signal")


class ApprovedOrderRecord(Base):
    __tablename__ = "approved_orders"

    id = Column(String, primary_key=True, default=_uuid)
    signal_id = Column(String, ForeignKey("trade_signals.id"), nullable=False)
    account_id = Column(String, ForeignKey("accounts.id"), nullable=False)
    symbol = Column(String, nullable=False)
    side = Column(String, nullable=False)
    order_type = Column(String, nullable=False)
    entry_price = Column(Float, nullable=False)
    stop_price = Column(Float, nullable=False)
    take_profit = Column(Float)
    quantity = Column(Float, nullable=False)
    risk_pct = Column(Float, nullable=False)
    instrument_id = Column(String)
    broker_payload = Column(Text)
    status = Column(String, nullable=False, default="pending")
    created_at = Column(String, nullable=False, default=_now_iso)

    signal = relationship("TradeSignalRecord", back_populates="approved_orders")
    trade_results = relationship("TradeResultRecord", back_populates="approved_order")


class TradeResultRecord(Base):
    __tablename__ = "trade_results"
    __table_args__ = (
        Index("idx_trade_results_closed_at", "closed_at"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    approved_order_id = Column(String, ForeignKey("approved_orders.id"), nullable=False)
    external_trade_id = Column(String)
    account_id = Column(String, ForeignKey("accounts.id"), nullable=False)
    symbol = Column(String, nullable=False)
    strategy_name = Column(String)
    status = Column(String, nullable=False)  # open, closed, cancelled
    entry_price = Column(Float)
    exit_price = Column(Float)
    stop_price = Column(Float)
    take_profit = Column(Float)
    quantity = Column(Float)
    pnl = Column(Float)
    pnl_pct = Column(Float)
    fees = Column(Float)
    slippage = Column(Float)
    opened_at = Column(String)
    closed_at = Column(String)
    execution_notes = Column(Text)
    json_payload = Column(Text)

    approved_order = relationship("ApprovedOrderRecord", back_populates="trade_results")


class RiskEventRecord(Base):
    __tablename__ = "risk_events"

    id = Column(String, primary_key=True, default=_uuid)
    account_id = Column(String, ForeignKey("accounts.id"), nullable=False)
    event_type = Column(String, nullable=False)
    severity = Column(String, nullable=False)  # info, warning, critical
    message = Column(String, nullable=False)
    triggered_at = Column(String, nullable=False, default=_now_iso)
    resolved_at = Column(String)
    auto_action_taken = Column(String)
    json_payload = Column(Text)


class IncidentRecord(Base):
    __tablename__ = "incidents"
    __table_args__ = (
        Index("idx_incidents_status_created", "status", "created_at"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    title = Column(String, nullable=False)
    category = Column(String, nullable=False)
    severity = Column(String, nullable=False)  # low, medium, high, critical
    source = Column(String, nullable=False)
    status = Column(String, nullable=False, default="open")
    summary = Column(String, nullable=False)
    details = Column(Text)
    created_at = Column(String, nullable=False, default=_now_iso)
    resolved_at = Column(String)
    json_payload = Column(Text)


class ConfigChangeRecord(Base):
    __tablename__ = "config_changes"

    id = Column(String, primary_key=True, default=_uuid)
    config_type = Column(String, nullable=False)
    config_key = Column(String, nullable=False)
    old_value = Column(String)
    new_value = Column(String, nullable=False)
    changed_by = Column(String, nullable=False)
    reason = Column(String)
    created_at = Column(String, nullable=False, default=_now_iso)


class JournalEntryRecord(Base):
    __tablename__ = "journal_entries"

    id = Column(String, primary_key=True, default=_uuid)
    trade_result_id = Column(String, ForeignKey("trade_results.id"), nullable=True)
    strategy_name = Column(String)
    symbol = Column(String, nullable=False)
    session_name = Column(String)
    summary = Column(String, nullable=False)
    lesson = Column(String)
    tags = Column(Text)  # JSON array as string
    created_by = Column(String, nullable=False)
    created_at = Column(String, nullable=False, default=_now_iso)


class AgentRunRecord(Base):
    __tablename__ = "agent_runs"

    id = Column(String, primary_key=True, default=_uuid)
    agent_name = Column(String, nullable=False)
    run_type = Column(String, nullable=False)  # scheduled, manual, triggered
    status = Column(String, nullable=False, default="started")
    input_summary = Column(Text)
    output_summary = Column(Text)
    error_message = Column(Text)
    started_at = Column(String, nullable=False, default=_now_iso)
    completed_at = Column(String)


class ExecutionLifecycleRecord(Base):
    """Canonical execution lifecycle — tracks from policy through broker to reconciliation.

    Every execution attempt lives here from birth to reconciliation.
    Lifecycle states (in order):
      policy_blocked, policy_simulated, policy_ready_for_broker,
      broker_submitted, broker_acknowledged, partially_filled, filled,
      broker_rejected, canceled, reconciling, reconciled, unknown
    """
    __tablename__ = "execution_lifecycle"
    __table_args__ = (
        Index("idx_exec_symbol_ts", "symbol", "created_at"),
        Index("idx_exec_status", "lifecycle_status"),
        Index("idx_exec_broker_order", "broker_order_id"),
    )

    id = Column(String, primary_key=True, default=_uuid)  # execution_id
    signal_id = Column(String)

    # Trade request
    symbol = Column(String, nullable=False)
    direction = Column(String, nullable=False)
    source = Column(String)         # operator, scanner, system
    strategy = Column(String)

    # Policy decision
    policy_result = Column(String)  # approved, blocked
    policy_message = Column(String)
    policy_blockers = Column(Text)  # JSON array
    policy_warnings = Column(Text)  # JSON array
    config_hash = Column(String)
    account_state_stale = Column(Integer, default=0)  # 0=fresh, 1=stale
    mode = Column(String)

    # Lifecycle status (the canonical state)
    lifecycle_status = Column(String, nullable=False, default="unknown")

    # Broker state
    broker_status = Column(String)        # submitted, acknowledged, rejected, etc.
    broker_message = Column(String)
    broker_order_id = Column(String)
    broker_rejection_code = Column(String)
    broker_raw_response = Column(Text)    # Full JSON for debugging

    # Quantities
    quantity_requested = Column(Float, default=0)
    quantity_filled = Column(Float, default=0)
    avg_fill_price = Column(Float, default=0)

    # Reconciliation
    reconciliation_status = Column(String)   # reconciling, reconciled, failed
    reconciliation_message = Column(String)

    # Timestamps (all TZ-aware ISO)
    requested_at = Column(String, nullable=False, default=_now_iso)
    policy_decided_at = Column(String)
    submitted_at = Column(String)
    acknowledged_at = Column(String)
    partially_filled_at = Column(String)
    filled_at = Column(String)
    canceled_at = Column(String)
    reconciled_at = Column(String)
    created_at = Column(String, nullable=False, default=_now_iso)
    updated_at = Column(String, nullable=False, default=_now_iso)


class AuditLogRecord(Base):
    """Durable audit log for all risk, execution, config, and safety events.

    Every critical decision is persisted here — survives restarts.
    """
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("idx_audit_category_ts", "category", "timestamp"),
        Index("idx_audit_symbol_ts", "symbol", "timestamp"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    category = Column(String, nullable=False)  # risk_decision, execution, config_change, kill_switch, breaker, scanner_promotion
    event_type = Column(String, nullable=False)  # approved, blocked, tripped, reset, activated, deactivated, promoted
    symbol = Column(String)
    direction = Column(String)
    strategy = Column(String)
    source = Column(String)  # operator, scanner, system, scheduler
    mode = Column(String)
    result = Column(String)  # approved, blocked, simulated, ready_for_broker, failed
    blockers = Column(Text)  # JSON array of blocker strings
    warnings = Column(Text)  # JSON array of warning strings
    config_hash = Column(String)
    execution_id = Column(String)
    actor = Column(String)
    old_value = Column(String)
    new_value = Column(String)
    reason = Column(String)
    equity = Column(Float)
    daily_pnl = Column(Float)
    json_payload = Column(Text)  # Full decision/event as JSON
    timestamp = Column(String, nullable=False, default=_now_iso)
