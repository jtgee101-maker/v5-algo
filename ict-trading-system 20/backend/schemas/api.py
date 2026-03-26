"""Pydantic schemas for all API request/response models."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, List, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


# ── Generic Wrappers ──────────────────────────────────────────────────

class ItemsResponse(BaseModel, Generic[T]):
    items: List[T]


class SuccessResponse(BaseModel):
    success: bool
    message: Optional[str] = None


# ── Health ─────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    mode: str
    broker_connected: bool
    db_connected: bool
    last_pipeline_heartbeat: Optional[str] = None
    last_market_sync: Optional[str] = None
    version: str


# ── Account ────────────────────────────────────────────────────────────

class AccountOut(BaseModel):
    id: str
    broker_name: str
    account_name: str
    account_type: str
    mode: str
    balance: float
    equity: float
    margin_used: float
    free_margin: float
    drawdown_pct: float
    status: str
    currency: Optional[str] = None
    updated_at: str


class AccountStateResponse(BaseModel):
    account: AccountOut


# ── Market State ───────────────────────────────────────────────────────

class MarketStateOut(BaseModel):
    id: str
    symbol: str
    timestamp: str
    session_name: Optional[str] = None
    session_active: bool = False
    overnight_range_high: Optional[float] = None
    overnight_range_low: Optional[float] = None
    prior_day_high: Optional[float] = None
    prior_day_low: Optional[float] = None
    asia_high: Optional[float] = None
    asia_low: Optional[float] = None
    weekly_high: Optional[float] = None
    weekly_low: Optional[float] = None
    psych_level_nearest: Optional[float] = None
    smt_flag: bool = False
    po3_phase: Optional[str] = None
    sweep_detected: bool = False
    displacement_detected: bool = False
    bias: Optional[str] = None
    structure_score: Optional[float] = None


# ── Trade Signal ───────────────────────────────────────────────────────

class SignalOut(BaseModel):
    id: str
    symbol: str
    strategy_name: str
    strategy_version: Optional[str] = None
    timestamp: str
    side: str
    confidence: float
    expected_value: Optional[float] = None
    entry_price: float
    stop_price: float
    take_profit_1: Optional[float] = None
    take_profit_2: Optional[float] = None
    take_profit_3: Optional[float] = None
    invalidation_reason: Optional[str] = None
    risk_score: Optional[float] = None
    structure_score: Optional[float] = None
    confluence_tags: Optional[List[str]] = None
    status: str
    expires_at: Optional[str] = None
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    rejected_by: Optional[str] = None
    rejected_at: Optional[str] = None
    rejection_reason: Optional[str] = None


class ApproveSignalRequest(BaseModel):
    signal_id: str
    approved_by: str
    note: Optional[str] = None


class RejectSignalRequest(BaseModel):
    signal_id: str
    rejected_by: str
    reason: str


class ApprovalResponse(BaseModel):
    success: bool
    signal_id: str
    status: str
    approved_at: Optional[str] = None
    rejected_at: Optional[str] = None


# ── Trade Result ───────────────────────────────────────────────────────

class TradeOut(BaseModel):
    id: str
    external_trade_id: Optional[str] = None
    account_id: str
    symbol: str
    strategy_name: Optional[str] = None
    status: str
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    stop_price: Optional[float] = None
    take_profit: Optional[float] = None
    quantity: Optional[float] = None
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    fees: Optional[float] = None
    slippage: Optional[float] = None
    opened_at: Optional[str] = None
    closed_at: Optional[str] = None


# ── Risk Events ────────────────────────────────────────────────────────

class RiskEventOut(BaseModel):
    id: str
    account_id: str
    event_type: str
    severity: str
    message: str
    triggered_at: str
    resolved_at: Optional[str] = None
    auto_action_taken: Optional[str] = None


# ── Incidents ──────────────────────────────────────────────────────────

class IncidentOut(BaseModel):
    id: str
    title: str
    category: str
    severity: str
    source: str
    status: str
    summary: str
    details: Optional[str] = None
    created_at: str
    resolved_at: Optional[str] = None


# ── Config ─────────────────────────────────────────────────────────────

class ConfigResponse(BaseModel):
    mode: str
    manual_approval_required: bool
    allowed_symbols: List[str]
    risk: dict


class UpdateConfigRequest(BaseModel):
    changed_by: str
    reason: Optional[str] = None
    updates: dict


class UpdateConfigResponse(BaseModel):
    success: bool
    applied: dict


# ── Control ────────────────────────────────────────────────────────────

class KillSwitchRequest(BaseModel):
    triggered_by: str
    reason: str


class KillSwitchResponse(BaseModel):
    success: bool
    mode: str
    orders_cancelled: int
    positions_closed: int
    timestamp: str


class SetModeRequest(BaseModel):
    changed_by: str
    mode: str


class SetModeResponse(BaseModel):
    success: bool
    mode: str
    live_locked: bool


# ── Journal ────────────────────────────────────────────────────────────

class JournalOut(BaseModel):
    id: str
    trade_result_id: Optional[str] = None
    strategy_name: Optional[str] = None
    symbol: str
    session_name: Optional[str] = None
    summary: str
    lesson: Optional[str] = None
    tags: Optional[List[str]] = None
    created_by: str
    created_at: str


# ── Agent Runs ─────────────────────────────────────────────────────────

class AgentRunOut(BaseModel):
    id: str
    agent_name: str
    run_type: str
    status: str
    input_summary: Optional[str] = None
    output_summary: Optional[str] = None
    error_message: Optional[str] = None
    started_at: str
    completed_at: Optional[str] = None
