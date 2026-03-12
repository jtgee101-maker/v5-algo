"""API routers — all endpoints with clean dependency injection.

No global singletons. Services are instantiated per-request with the DB session.
ConfigService is the only singleton (holds runtime mode state) but gets fresh
DB sessions via the dependency module.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import AuthContext, get_auth, require_admin, require_operator
from backend.db.session import get_db
from backend.db.models import ConfigChangeRecord
from backend.db.repositories.base import GenericRepository
from backend.dependencies import get_config_service
from backend.schemas.api import (
    AccountOut, AccountStateResponse, AgentRunOut, ApprovalResponse,
    ApproveSignalRequest, ConfigResponse, HealthResponse, IncidentOut,
    ItemsResponse, JournalOut, KillSwitchRequest, KillSwitchResponse,
    MarketStateOut, RejectSignalRequest, RiskEventOut, SetModeRequest,
    SetModeResponse, SignalOut, SuccessResponse, TradeOut,
    UpdateConfigRequest, UpdateConfigResponse,
)
from backend.services.core_services import (
    AccountService, AgentService, IncidentService,
    JournalService, MarketService, RiskService, TradeService,
)
from backend.services.signal_service import SignalService
from backend.settings import VERSION


# ══════════════════════════════════════════════════════════════════════
# HEALTH — real checks against DB
# ══════════════════════════════════════════════════════════════════════
health_router = APIRouter(tags=["health"])


@health_router.get("/health", response_model=HealthResponse)
async def health_check(db: AsyncSession = Depends(get_db)):
    cfg = get_config_service(db)
    acct_svc = AccountService(db)
    mkt_svc = MarketService(db)

    acct = await acct_svc.get_primary()
    broker_ok = acct is not None and acct.status == "connected"

    last_sync = None
    recent_ms = await mkt_svc.list_states(limit=1)
    if recent_ms:
        last_sync = recent_ms[0].timestamp

    return HealthResponse(
        status="ok",
        mode=cfg.mode,
        broker_connected=broker_ok,
        db_connected=True,
        last_pipeline_heartbeat=acct.updated_at if acct else None,
        last_market_sync=last_sync,
        version=VERSION,
    )


# ══════════════════════════════════════════════════════════════════════
# ACCOUNT
# ══════════════════════════════════════════════════════════════════════
account_router = APIRouter(tags=["account"])


@account_router.get("/account-state", response_model=AccountStateResponse)
async def get_account_state(db: AsyncSession = Depends(get_db)):
    acct = await AccountService(db).get_primary()
    if acct is None:
        raise HTTPException(404, "No account configured")
    return AccountStateResponse(account=AccountOut(
        id=acct.id, broker_name=acct.broker_name, account_name=acct.account_name,
        account_type=acct.account_type, mode=acct.mode, balance=acct.balance,
        equity=acct.equity, margin_used=acct.margin_used, free_margin=acct.free_margin,
        drawdown_pct=acct.drawdown_pct, status=acct.status,
        currency=acct.currency, updated_at=acct.updated_at,
    ))


# ══════════════════════════════════════════════════════════════════════
# MARKET STATE
# ══════════════════════════════════════════════════════════════════════
market_router = APIRouter(tags=["market"])


@market_router.get("/market-state", response_model=ItemsResponse[MarketStateOut])
async def get_market_states(
    symbol: Optional[str] = Query(None), limit: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    records = await MarketService(db).list_states(symbol=symbol, limit=limit)
    return ItemsResponse(items=[
        MarketStateOut(
            id=r.id, symbol=r.symbol, timestamp=r.timestamp,
            session_name=r.session_name, session_active=bool(r.session_active),
            overnight_range_high=r.overnight_range_high, overnight_range_low=r.overnight_range_low,
            prior_day_high=r.prior_day_high, prior_day_low=r.prior_day_low,
            asia_high=r.asia_high, asia_low=r.asia_low,
            weekly_high=r.weekly_high, weekly_low=r.weekly_low,
            psych_level_nearest=r.psych_level_nearest, smt_flag=bool(r.smt_flag),
            po3_phase=r.po3_phase, sweep_detected=bool(r.sweep_detected),
            displacement_detected=bool(r.displacement_detected),
            bias=r.bias, structure_score=r.structure_score,
        ) for r in records
    ])


# ══════════════════════════════════════════════════════════════════════
# SIGNALS + APPROVAL WORKFLOW
# ══════════════════════════════════════════════════════════════════════
signals_router = APIRouter(tags=["signals"])


def _signal_out(r) -> SignalOut:
    tags = None
    if r.confluence_tags:
        try:
            tags = json.loads(r.confluence_tags)
        except (json.JSONDecodeError, TypeError):
            tags = r.confluence_tags.split(",") if r.confluence_tags else None
    return SignalOut(
        id=r.id, symbol=r.symbol, strategy_name=r.strategy_name,
        strategy_version=r.strategy_version, timestamp=r.timestamp,
        side=r.side, confidence=r.confidence, expected_value=r.expected_value,
        entry_price=r.entry_price, stop_price=r.stop_price,
        take_profit_1=r.take_profit_1, take_profit_2=r.take_profit_2,
        take_profit_3=r.take_profit_3, invalidation_reason=r.invalidation_reason,
        risk_score=r.risk_score, structure_score=r.structure_score,
        confluence_tags=tags, status=r.status, expires_at=r.expires_at,
        approved_by=r.approved_by, approved_at=r.approved_at,
        rejected_by=r.rejected_by, rejected_at=r.rejected_at,
        rejection_reason=r.rejection_reason,
    )


@signals_router.get("/signals", response_model=ItemsResponse[SignalOut])
async def list_signals(
    status: Optional[str] = Query(None), symbol: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200), db: AsyncSession = Depends(get_db),
):
    records = await SignalService(db).list_signals(status=status, symbol=symbol, limit=limit)
    return ItemsResponse(items=[_signal_out(r) for r in records])


@signals_router.post("/approve-signal", response_model=ApprovalResponse)
async def approve_signal(
    req: ApproveSignalRequest,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_auth),
):
    require_operator(auth)
    result = await SignalService(db).approve_signal(req.signal_id, req.approved_by, req.note)
    if result is None:
        raise HTTPException(404, "Signal not found or not in pending status")
    return ApprovalResponse(success=True, signal_id=result.id, status=result.status, approved_at=result.approved_at)


@signals_router.post("/reject-signal", response_model=ApprovalResponse)
async def reject_signal(
    req: RejectSignalRequest,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_auth),
):
    require_operator(auth)
    result = await SignalService(db).reject_signal(req.signal_id, req.rejected_by, req.reason)
    if result is None:
        raise HTTPException(404, "Signal not found or not in pending status")
    return ApprovalResponse(success=True, signal_id=result.id, status=result.status, rejected_at=result.rejected_at)


# ══════════════════════════════════════════════════════════════════════
# TRADES
# ══════════════════════════════════════════════════════════════════════
trades_router = APIRouter(tags=["trades"])


@trades_router.get("/trades", response_model=ItemsResponse[TradeOut])
async def list_trades(
    symbol: Optional[str] = Query(None), status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200), db: AsyncSession = Depends(get_db),
):
    records = await TradeService(db).list_trades(symbol=symbol, status=status, limit=limit)
    return ItemsResponse(items=[
        TradeOut(
            id=r.id, external_trade_id=r.external_trade_id, account_id=r.account_id,
            symbol=r.symbol, strategy_name=r.strategy_name, status=r.status,
            entry_price=r.entry_price, exit_price=r.exit_price,
            stop_price=r.stop_price, take_profit=r.take_profit,
            quantity=r.quantity, pnl=r.pnl, pnl_pct=r.pnl_pct,
            fees=r.fees, slippage=r.slippage, opened_at=r.opened_at, closed_at=r.closed_at,
        ) for r in records
    ])


# ══════════════════════════════════════════════════════════════════════
# RISK / INCIDENTS / JOURNALS / AGENTS — simple list endpoints
# ══════════════════════════════════════════════════════════════════════
risk_router = APIRouter(tags=["risk"])


@risk_router.get("/risk-events", response_model=ItemsResponse[RiskEventOut])
async def list_risk_events(limit: int = Query(50, ge=1, le=200), db: AsyncSession = Depends(get_db)):
    records = await RiskService(db).list_events(limit=limit)
    return ItemsResponse(items=[
        RiskEventOut(id=r.id, account_id=r.account_id, event_type=r.event_type,
                     severity=r.severity, message=r.message, triggered_at=r.triggered_at,
                     resolved_at=r.resolved_at, auto_action_taken=r.auto_action_taken)
        for r in records
    ])


incidents_router = APIRouter(tags=["incidents"])


@incidents_router.get("/incidents", response_model=ItemsResponse[IncidentOut])
async def list_incidents(
    status: Optional[str] = Query(None), limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    records = await IncidentService(db).list_incidents(status=status, limit=limit)
    return ItemsResponse(items=[
        IncidentOut(id=r.id, title=r.title, category=r.category, severity=r.severity,
                    source=r.source, status=r.status, summary=r.summary,
                    details=r.details, created_at=r.created_at, resolved_at=r.resolved_at)
        for r in records
    ])


journals_router = APIRouter(tags=["journals"])


@journals_router.get("/journals", response_model=ItemsResponse[JournalOut])
async def list_journals(limit: int = Query(50, ge=1, le=200), db: AsyncSession = Depends(get_db)):
    records = await JournalService(db).list_entries(limit=limit)
    items = []
    for r in records:
        tags = None
        if r.tags:
            try:
                tags = json.loads(r.tags)
            except (json.JSONDecodeError, TypeError):
                pass
        items.append(JournalOut(
            id=r.id, trade_result_id=r.trade_result_id, strategy_name=r.strategy_name,
            symbol=r.symbol, session_name=r.session_name, summary=r.summary,
            lesson=r.lesson, tags=tags, created_by=r.created_by, created_at=r.created_at,
        ))
    return ItemsResponse(items=items)


agents_router = APIRouter(tags=["agents"])


@agents_router.get("/agents/runs", response_model=ItemsResponse[AgentRunOut])
async def list_agent_runs(limit: int = Query(50, ge=1, le=200), db: AsyncSession = Depends(get_db)):
    records = await AgentService(db).list_runs(limit=limit)
    return ItemsResponse(items=[
        AgentRunOut(id=r.id, agent_name=r.agent_name, run_type=r.run_type,
                    status=r.status, input_summary=r.input_summary,
                    output_summary=r.output_summary, error_message=r.error_message,
                    started_at=r.started_at, completed_at=r.completed_at)
        for r in records
    ])


# ══════════════════════════════════════════════════════════════════════
# CONFIG + CONTROL
# ══════════════════════════════════════════════════════════════════════
config_router = APIRouter(tags=["config"])


@config_router.get("/config", response_model=ConfigResponse)
async def get_config(db: AsyncSession = Depends(get_db)):
    return ConfigResponse(**get_config_service(db).get_config())


@config_router.post("/update-config", response_model=UpdateConfigResponse)
async def update_config(
    req: UpdateConfigRequest,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_auth),
):
    require_admin(auth)
    cfg = get_config_service(db)
    applied = await cfg.update_config(req.changed_by, req.reason or "", req.updates)
    return UpdateConfigResponse(success=True, applied=applied)


control_router = APIRouter(tags=["control"])


@control_router.post("/kill-switch", response_model=KillSwitchResponse)
async def kill_switch(
    req: KillSwitchRequest,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_auth),
):
    require_admin(auth)
    await IncidentService(db).create_incident(
        title="Kill switch activated", category="kill_switch",
        severity="critical", source=req.triggered_by,
        status="open", summary=req.reason,
    )
    cfg = get_config_service(db)
    cfg._mode = "shadow"
    return KillSwitchResponse(
        success=True, mode="shadow", orders_cancelled=0, positions_closed=0,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@control_router.post("/set-mode", response_model=SetModeResponse)
async def set_mode(
    req: SetModeRequest,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_auth),
):
    require_admin(auth)
    cfg = get_config_service(db)
    try:
        old_mode = cfg.mode
        cfg.mode = req.mode
        await GenericRepository(db, ConfigChangeRecord).create(
            config_type="runtime", config_key="mode",
            old_value=old_mode, new_value=req.mode,
            changed_by=req.changed_by, reason=f"Mode: {old_mode} → {req.mode}",
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return SetModeResponse(success=True, mode=cfg.mode, live_locked=cfg.live_locked)


# ══════════════════════════════════════════════════════════════════════
# METRICS
# ══════════════════════════════════════════════════════════════════════
metrics_router = APIRouter(tags=["metrics"])


@metrics_router.get("/metrics/overview")
async def metrics_overview(db: AsyncSession = Depends(get_db)):
    from backend.services.metrics_service import MetricsService
    return await MetricsService(db).overview()


@metrics_router.get("/metrics/strategies")
async def metrics_strategies(db: AsyncSession = Depends(get_db)):
    from backend.services.metrics_service import MetricsService
    return {"strategies": await MetricsService(db).by_strategy()}


@metrics_router.get("/metrics/sessions")
async def metrics_sessions(db: AsyncSession = Depends(get_db)):
    from backend.services.metrics_service import MetricsService
    return {"sessions": await MetricsService(db).by_session()}


# ══════════════════════════════════════════════════════════════════════
# RECONCILIATION
# ══════════════════════════════════════════════════════════════════════
reconciliation_router = APIRouter(tags=["reconciliation"])


@reconciliation_router.get("/reconciliation-status")
async def reconciliation_status(db: AsyncSession = Depends(get_db)):
    from backend.services.reconciliation_service import ReconciliationService
    return await ReconciliationService(db).get_status()


