"""Pipeline persistence service — bridges the trading loop to the database.

This is the single integration point. The pipeline calls this service
to persist market states, signals, orders, and results. It also checks
approval status before allowing execution.

DB is source of truth. JSON artifacts are optional secondary logging.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from typing import Any, Optional
from uuid import uuid4

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import (
    Account, ApprovedOrderRecord, IncidentRecord, MarketStateRecord,
    RiskEventRecord, TradeResultRecord, TradeSignalRecord,
)
from backend.db.repositories.base import GenericRepository
from backend.settings import SIGNAL_EXPIRY_SECONDS

logger = structlog.get_logger(__name__)


class PipelinePersistence:
    """Async service that persists all pipeline outputs to DB.

    Used directly by the pipeline loop. Each method is atomic.
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self.market_repo = GenericRepository(session, MarketStateRecord)
        self.signal_repo = GenericRepository(session, TradeSignalRecord)
        self.order_repo = GenericRepository(session, ApprovedOrderRecord)
        self.trade_repo = GenericRepository(session, TradeResultRecord)
        self.account_repo = GenericRepository(session, Account)
        self.risk_repo = GenericRepository(session, RiskEventRecord)
        self.incident_repo = GenericRepository(session, IncidentRecord)

    # ── Market State ──────────────────────────────────────────────────

    async def persist_market_state(
        self,
        symbol: str,
        timestamp: datetime,
        session_name: str,
        session_active: bool,
        market_state_dict: dict[str, Any],
    ) -> str:
        """Persist a MarketState snapshot. Returns record ID."""
        record_id = str(uuid4())

        # Extract flattened fields from the full market state
        session_ranges = market_state_dict.get("session_ranges", {})
        overnight = session_ranges.get("overnight", {})
        liquidity_pools = market_state_dict.get("liquidity_pools", [])

        # Find PDH/PDL from liquidity pools
        pdh = next((p["price"] for p in liquidity_pools if p.get("type") == "pdh"), None)
        pdl = next((p["price"] for p in liquidity_pools if p.get("type") == "pdl"), None)
        asia_h = next((p["price"] for p in liquidity_pools if p.get("type") == "asia_high"), None)
        asia_l = next((p["price"] for p in liquidity_pools if p.get("type") == "asia_low"), None)
        weekly_h = next((p["price"] for p in liquidity_pools if p.get("type") == "weekly_high"), None)
        weekly_l = next((p["price"] for p in liquidity_pools if p.get("type") == "weekly_low"), None)

        psych = market_state_dict.get("psych_levels") or {}
        smt_signals = market_state_dict.get("smt_signals", [])
        po3 = market_state_dict.get("po3_state", {})
        sweeps = market_state_dict.get("sweep_events", [])
        displacements = market_state_dict.get("displacement_candles", [])

        await self.market_repo.create(
            id=record_id,
            symbol=symbol,
            timestamp=timestamp.isoformat(),
            session_name=session_name,
            session_active=1 if session_active else 0,
            overnight_range_high=overnight.get("high"),
            overnight_range_low=overnight.get("low"),
            prior_day_high=pdh,
            prior_day_low=pdl,
            asia_high=asia_h,
            asia_low=asia_l,
            weekly_high=weekly_h,
            weekly_low=weekly_l,
            psych_level_nearest=psych.get("nearest_above"),
            smt_flag=1 if smt_signals else 0,
            po3_phase=po3.get("phase", "idle"),
            sweep_detected=1 if sweeps else 0,
            displacement_detected=1 if displacements else 0,
            bias=market_state_dict.get("structure_bias", "ranging"),
            structure_score=None,
            json_payload=json.dumps(market_state_dict, default=str),
        )

        logger.debug("persistence.market_state_saved", id=record_id, symbol=symbol)
        return record_id

    # ── Trade Signal ──────────────────────────────────────────────────

    async def persist_signal(
        self,
        signal_dict: dict[str, Any],
        risk_approved: bool,
        risk_rejection_reason: Optional[str] = None,
        manual_approval_required: bool = True,
    ) -> str:
        """Persist a trade signal from the strategy engine.

        If risk_approved=True and manual_approval_required=True, status='pending'.
        If risk_approved=True and manual_approval_required=False, status='approved'.
        If risk_approved=False, status='rejected' (by risk engine).
        """
        record_id = str(uuid4())
        now = datetime.now(timezone.utc)

        if not risk_approved:
            status = "rejected"
            rejection_reason = risk_rejection_reason
            rejected_by = "risk_engine"
            rejected_at = now.isoformat()
        elif manual_approval_required:
            status = "pending"
            rejection_reason = None
            rejected_by = None
            rejected_at = None
        else:
            status = "approved"
            rejection_reason = None
            rejected_by = None
            rejected_at = None

        direction = signal_dict.get("direction", "long")
        side = "buy" if direction in ("long", "buy") else "sell"
        targets = signal_dict.get("targets", [])
        confluence = signal_dict.get("confluence_tags", [])

        expires = (now + timedelta(seconds=SIGNAL_EXPIRY_SECONDS)).isoformat()

        await self.signal_repo.create(
            id=record_id,
            symbol=signal_dict.get("symbol", ""),
            strategy_name=signal_dict.get("strategy_id", ""),
            strategy_version=signal_dict.get("strategy_id", "").split("_")[-1] if "_v" in signal_dict.get("strategy_id", "") else "v1",
            timestamp=signal_dict.get("timestamp", now.isoformat()),
            side=side,
            confidence=signal_dict.get("confidence", 0),
            expected_value=signal_dict.get("reward_risk", 0) * signal_dict.get("confidence", 0),
            entry_price=signal_dict.get("entry_price", 0),
            stop_price=signal_dict.get("stop_price", 0),
            take_profit_1=targets[0]["price"] if len(targets) > 0 else None,
            take_profit_2=targets[1]["price"] if len(targets) > 1 else None,
            take_profit_3=targets[2]["price"] if len(targets) > 2 else None,
            invalidation_reason=signal_dict.get("invalidation"),
            risk_score=signal_dict.get("risk_pct_actual", 0),
            structure_score=signal_dict.get("confidence", 0),
            confluence_tags=json.dumps(confluence) if confluence else None,
            status=status,
            expires_at=expires if status == "pending" else None,
            rejected_by=rejected_by,
            rejected_at=rejected_at,
            rejection_reason=rejection_reason,
            approved_by="auto" if status == "approved" else None,
            approved_at=now.isoformat() if status == "approved" else None,
            json_payload=json.dumps(signal_dict, default=str),
        )

        logger.info("persistence.signal_saved", id=record_id, status=status,
                     symbol=signal_dict.get("symbol"))
        return record_id

    # ── Approval Check ────────────────────────────────────────────────

    async def get_approved_signals(self, symbol: Optional[str] = None) -> list[TradeSignalRecord]:
        """Get signals that have been approved and are ready for execution."""
        filters = {"status": "approved"}
        if symbol:
            filters["symbol"] = symbol
        return await self.signal_repo.list_all(
            limit=10, order_by="timestamp", desc=True, **filters
        )

    async def is_signal_approved(self, signal_id: str) -> bool:
        """Check if a specific signal has been approved."""
        record = await self.signal_repo.get_by_id(signal_id)
        return record is not None and record.status == "approved"

    async def mark_signal_executed(self, signal_id: str) -> None:
        """Mark a signal as executed after order placement."""
        await self.signal_repo.update_by_id(signal_id, status="executed")

    async def expire_stale_signals(self) -> int:
        """Expire pending signals past their expiry time."""
        pending = await self.signal_repo.list_all(limit=200, status="pending")
        now = datetime.now(timezone.utc)
        count = 0
        for sig in pending:
            if sig.expires_at:
                try:
                    exp = datetime.fromisoformat(sig.expires_at)
                    if now > exp:
                        await self.signal_repo.update_by_id(sig.id, status="expired")
                        count += 1
                except (ValueError, TypeError):
                    pass
        return count

    # ── Approved Order ────────────────────────────────────────────────

    async def persist_approved_order(
        self,
        signal_id: str,
        account_id: str,
        order_dict: dict[str, Any],
    ) -> str:
        """Persist an approved order before sending to broker."""
        record_id = str(uuid4())
        targets = order_dict.get("targets", [])

        await self.order_repo.create(
            id=record_id,
            signal_id=signal_id,
            account_id=account_id,
            symbol=order_dict.get("symbol", ""),
            side="buy" if order_dict.get("direction") in ("long", "buy") else "sell",
            order_type=order_dict.get("entry_type", "market"),
            entry_price=order_dict.get("entry_price", 0),
            stop_price=order_dict.get("stop_price", 0),
            take_profit=targets[0]["price"] if targets else None,
            quantity=order_dict.get("position_size", 0),
            risk_pct=order_dict.get("risk_pct_actual", 0),
            instrument_id=str(order_dict.get("instrument_id", "")),
            status="sent",
        )

        logger.info("persistence.order_saved", id=record_id, signal_id=signal_id)
        return record_id

    # ── Trade Result ──────────────────────────────────────────────────

    async def persist_trade_result(
        self,
        order_id: str,
        account_id: str,
        result_dict: dict[str, Any],
    ) -> str:
        """Persist a trade execution result."""
        record_id = str(uuid4())
        await self.trade_repo.create(
            id=record_id,
            approved_order_id=order_id,
            account_id=account_id,
            external_trade_id=result_dict.get("external_trade_id"),
            symbol=result_dict.get("symbol", ""),
            strategy_name=result_dict.get("strategy_name"),
            status=result_dict.get("status", "open"),
            entry_price=result_dict.get("entry_price"),
            exit_price=result_dict.get("exit_price"),
            stop_price=result_dict.get("stop_price"),
            take_profit=result_dict.get("take_profit"),
            quantity=result_dict.get("quantity"),
            pnl=result_dict.get("pnl"),
            pnl_pct=result_dict.get("pnl_pct"),
            fees=result_dict.get("fees"),
            slippage=result_dict.get("slippage"),
            opened_at=result_dict.get("opened_at"),
            closed_at=result_dict.get("closed_at"),
            json_payload=json.dumps(result_dict, default=str),
        )
        logger.info("persistence.trade_result_saved", id=record_id, order_id=order_id)
        return record_id

    # ── Account ───────────────────────────────────────────────────────

    async def update_account(
        self, account_id: str, **kwargs: Any
    ) -> None:
        """Update account state in DB."""
        kwargs["updated_at"] = datetime.now(timezone.utc).isoformat()
        await self.account_repo.update_by_id(account_id, **kwargs)

    # ── Risk Events ───────────────────────────────────────────────────

    async def persist_risk_event(
        self,
        account_id: str,
        event_type: str,
        severity: str,
        message: str,
        auto_action: Optional[str] = None,
    ) -> str:
        """Persist a risk event (throttle, limit breach, etc)."""
        record_id = str(uuid4())
        await self.risk_repo.create(
            id=record_id,
            account_id=account_id,
            event_type=event_type,
            severity=severity,
            message=message,
            auto_action_taken=auto_action,
        )
        return record_id

    # ── Incidents ─────────────────────────────────────────────────────

    async def create_incident(
        self,
        title: str,
        category: str,
        severity: str,
        source: str,
        summary: str,
        details: Optional[str] = None,
    ) -> str:
        """Create an incident record."""
        record_id = str(uuid4())
        await self.incident_repo.create(
            id=record_id,
            title=title,
            category=category,
            severity=severity,
            source=source,
            status="open",
            summary=summary,
            details=details,
        )
        logger.warning("persistence.incident_created", id=record_id, severity=severity, title=title)
        return record_id

    # ── Commit ────────────────────────────────────────────────────────

    async def commit(self) -> None:
        """Commit the current transaction."""
        await self.session.commit()
