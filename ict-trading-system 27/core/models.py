"""Shared data models for the ICT Trading System.

All inter-engine communication uses these Pydantic models,
which correspond to the JSON schemas in schemas/.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ── Enums ──────────────────────────────────────────────────────────────────

class Direction(str, Enum):
    LONG = "long"
    SHORT = "short"


class SessionName(str, Enum):
    ASIA = "asia"
    LONDON = "london"
    NY = "ny"
    NY_KILLZONE = "ny_killzone"
    OFF_SESSION = "off_session"


class StructureBias(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    RANGING = "ranging"


class PO3Phase(str, Enum):
    IDLE = "idle"
    ACCUMULATING = "accumulating"
    MANIPULATED = "manipulated"
    DISTRIBUTING = "distributing"
    COMPLETE = "complete"


class Regime(str, Enum):
    REVERSAL_DAY = "reversal_day"
    TREND_DAY = "trend_day"
    CHOP = "chop"
    NEWS_DRIVEN = "news_driven"
    UNKNOWN = "unknown"


class ThrottleAction(str, Enum):
    NORMAL = "normal"
    CUT_RISK = "cut_risk"
    CUT_RISK_AND_POSITIONS = "cut_risk_and_positions"
    A_TIER_ONLY = "a_tier_only"
    SHADOW_WEAK = "shadow_weak_strategies"
    CAPITAL_PRESERVATION = "capital_preservation"
    HARD_LOCK = "hard_lock"


class ExitReason(str, Enum):
    TARGET_HIT = "target_hit"
    STOP_HIT = "stop_hit"
    INVALIDATION = "invalidation"
    MANUAL_CLOSE = "manual_close"
    KILL_SWITCH = "kill_switch"
    SESSION_END = "session_end"
    TIMEOUT = "timeout"


class TradeStatus(str, Enum):
    OPEN = "open"
    CLOSED_WIN = "closed_win"
    CLOSED_LOSS = "closed_loss"
    CLOSED_BREAKEVEN = "closed_breakeven"
    CANCELLED = "cancelled"


class LiquidityType(str, Enum):
    PDH = "pdh"
    PDL = "pdl"
    ASIA_HIGH = "asia_high"
    ASIA_LOW = "asia_low"
    WEEKLY_HIGH = "weekly_high"
    WEEKLY_LOW = "weekly_low"
    EQUAL_HIGHS = "equal_highs"
    EQUAL_LOWS = "equal_lows"
    OR_HIGH = "opening_range_high"
    OR_LOW = "opening_range_low"
    SWING_CLUSTER = "swing_cluster"


# ── Shared Sub-Models ──────────────────────────────────────────────────────

class PriceRange(BaseModel):
    high: float
    low: float
    mid: Optional[float] = None
    range_atr_ratio: Optional[float] = None


class Target(BaseModel):
    price: float
    pct_close: float = Field(ge=0, le=1)


class Candle(BaseModel):
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    timeframe: str = "1m"


# ── Market Structure Engine Output ─────────────────────────────────────────

class LiquidityPool(BaseModel):
    price: float
    type: LiquidityType
    strength_score: float = Field(ge=0, le=1)
    age_bars: int = 0
    swept: bool = False
    swept_timestamp: Optional[datetime] = None


class SwingPoint(BaseModel):
    price: float
    type: str  # "swing_high" or "swing_low"
    bar_index: int
    timestamp: datetime
    broken: bool = False


class SMTSignal(BaseModel):
    pair: tuple[str, str]
    direction: Direction
    strength: float = Field(ge=0, le=1)
    timestamp: datetime
    session_valid: bool = True


class PO3State(BaseModel):
    phase: PO3Phase = PO3Phase.IDLE
    accumulation_range: Optional[PriceRange] = None
    manipulation_extreme: Optional[float] = None
    distribution_bias: Optional[Direction] = None
    confidence: float = Field(default=0.0, ge=0, le=1)


class FVG(BaseModel):
    type: Direction
    upper: float
    lower: float
    filled: bool = False
    age_bars: int = 0


class SweepEvent(BaseModel):
    timestamp: datetime
    level_swept: float
    level_type: Optional[str] = None
    direction: str  # "above" or "below"
    rejected: bool = False
    displacement_followed: bool = False


class PsychLevels(BaseModel):
    nearest_above: float
    nearest_below: float
    proximity_score: float = Field(ge=0, le=1)


class MarketState(BaseModel):
    """Complete output of the Market Structure Engine for one symbol."""
    timestamp: datetime
    symbol: str
    session: SessionName
    session_ranges: dict[str, PriceRange] = {}
    liquidity_pools: list[LiquidityPool] = []
    structure_bias: StructureBias = StructureBias.RANGING
    swing_points: list[SwingPoint] = []
    smt_signals: list[SMTSignal] = []
    po3_state: PO3State = Field(default_factory=PO3State)
    psych_levels: Optional[PsychLevels] = None
    fvgs: list[FVG] = []
    displacement_candles: list[dict] = []
    sweep_events: list[SweepEvent] = []


# ── Strategy Decision Engine Output ────────────────────────────────────────

class ConfidenceBreakdown(BaseModel):
    p_setup: float = Field(ge=0, le=1)
    ev_ratio: float = Field(ge=0, le=1)
    regime_confidence: float = Field(ge=0, le=1)
    exec_confidence: float = Field(ge=0, le=1)
    structural_clarity: float = Field(ge=0, le=1)
    correlation_confirm: float = Field(ge=0, le=1)
    session_timing: float = Field(ge=0, le=1)


class TradeSignal(BaseModel):
    timestamp: datetime
    strategy_id: str
    symbol: str
    direction: Direction
    confidence: float = Field(ge=0, le=1)
    confidence_breakdown: Optional[ConfidenceBreakdown] = None
    entry_type: str  # "market", "limit", "stop"
    entry_price: float
    stop_price: float
    targets: list[Target]
    invalidation: Optional[str] = None
    reward_risk: float = Field(ge=0)
    confluence_tags: list[str] = []
    regime: Regime = Regime.UNKNOWN
    session: str = ""
    market_state_ref: Optional[str] = None


# ── Risk Engine Output ─────────────────────────────────────────────────────

class ThrottleState(BaseModel):
    risk_multiplier: float = Field(ge=0, le=1, default=1.0)
    action: ThrottleAction = ThrottleAction.NORMAL
    current_dd_pct: float = 0.0


class ApprovedOrder(BaseModel):
    approved: bool
    signal_ref: str
    symbol: Optional[str] = None
    direction: Optional[Direction] = None
    entry_type: Optional[str] = None
    entry_price: Optional[float] = None
    stop_price: Optional[float] = None
    targets: list[Target] = []
    position_size: float = 0.0
    risk_amount: float = 0.0
    risk_pct_actual: float = 0.0
    throttle_state: ThrottleAction = ThrottleAction.NORMAL
    checks_passed: list[str] = []
    rejection_reason: Optional[str] = None
    rejection_detail: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ── Execution / Trade Result ───────────────────────────────────────────────

class ExecutionQuality(BaseModel):
    fill_latency_ms: int = 0
    slippage_ticks: float = 0.0
    spread_at_entry: float = 0.0


class TradeResult(BaseModel):
    trade_id: str
    order_ref: Optional[str] = None
    signal_ref: Optional[str] = None
    symbol: str
    direction: Direction
    strategy_id: str
    entry_time: datetime
    entry_price_requested: float
    entry_price_filled: float
    entry_slippage_ticks: float = 0.0
    stop_price: float
    targets: list[Target] = []
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[ExitReason] = None
    pnl_dollars: float = 0.0
    pnl_pct: float = 0.0
    r_multiple: float = 0.0
    position_size: float = 0.0
    confidence_at_entry: float = 0.0
    confluence_tags: list[str] = []
    regime_at_entry: Regime = Regime.UNKNOWN
    session: str = ""
    status: TradeStatus = TradeStatus.OPEN
    execution_quality: ExecutionQuality = Field(default_factory=ExecutionQuality)
