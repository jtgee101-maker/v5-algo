"""Tests for the approval workflow and pipeline persistence.

Covers:
- pending signal blocked from execution
- approved signal allowed in demo mode
- rejected/expired signal blocked
- market state persistence
- trade signal persistence
- risk event persistence
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.db.base import Base
from backend.db.models import (
    Account, MarketStateRecord, TradeSignalRecord,
    ApprovedOrderRecord, TradeResultRecord, RiskEventRecord,
)
from backend.services.pipeline_persistence import PipelinePersistence
from backend.services.signal_service import SignalService


@pytest.fixture
async def db_session():
    """Create an in-memory async SQLite session for testing."""
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        # Seed a test account
        acct = Account(
            id="test_acct", broker_name="test", account_name="Test",
            account_type="demo", mode="shadow", balance=10000, equity=10000,
            status="connected", updated_at=datetime.now(timezone.utc).isoformat(),
        )
        session.add(acct)
        await session.commit()
        yield session

    await engine.dispose()


class TestPipelinePersistence:

    @pytest.mark.asyncio
    async def test_persist_market_state(self, db_session):
        p = PipelinePersistence(db_session)
        record_id = await p.persist_market_state(
            symbol="NAS100",
            timestamp=datetime.now(timezone.utc),
            session_name="ny_killzone",
            session_active=True,
            market_state_dict={
                "session_ranges": {"overnight": {"high": 18450, "low": 18320}},
                "liquidity_pools": [
                    {"price": 18490, "type": "pdh"},
                    {"price": 18280, "type": "pdl"},
                ],
                "structure_bias": "bullish",
                "smt_signals": [],
                "po3_state": {"phase": "idle"},
                "sweep_events": [],
                "displacement_candles": [],
                "psych_levels": {"nearest_above": 18500},
            },
        )
        await p.commit()

        assert record_id
        # Verify persisted
        from backend.db.repositories.base import GenericRepository
        repo = GenericRepository(db_session, MarketStateRecord)
        record = await repo.get_by_id(record_id)
        assert record is not None
        assert record.symbol == "NAS100"
        assert record.session_name == "ny_killzone"
        assert record.prior_day_high == 18490
        assert record.prior_day_low == 18280

    @pytest.mark.asyncio
    async def test_persist_signal_risk_approved_manual(self, db_session):
        """Risk-approved signal with manual approval → status=pending."""
        p = PipelinePersistence(db_session)
        signal_id = await p.persist_signal(
            signal_dict={
                "symbol": "NAS100", "strategy_id": "ny_sweep_reversal_v1",
                "direction": "long", "confidence": 0.78,
                "entry_price": 18245.5, "stop_price": 18210.0,
                "reward_risk": 2.5, "timestamp": datetime.now(timezone.utc).isoformat(),
                "targets": [{"price": 18290, "pct_close": 0.5}],
                "confluence_tags": ["smt_divergence"],
            },
            risk_approved=True,
            manual_approval_required=True,
        )
        await p.commit()

        from backend.db.repositories.base import GenericRepository
        repo = GenericRepository(db_session, TradeSignalRecord)
        record = await repo.get_by_id(signal_id)
        assert record.status == "pending"
        assert record.expires_at is not None

    @pytest.mark.asyncio
    async def test_persist_signal_risk_approved_auto(self, db_session):
        """Risk-approved signal without manual approval → status=approved."""
        p = PipelinePersistence(db_session)
        signal_id = await p.persist_signal(
            signal_dict={
                "symbol": "EURUSD", "strategy_id": "ny_sweep_reversal_v1",
                "direction": "short", "confidence": 0.82,
                "entry_price": 1.0875, "stop_price": 1.0890,
                "reward_risk": 2.0, "timestamp": datetime.now(timezone.utc).isoformat(),
                "targets": [{"price": 1.0850, "pct_close": 0.5}],
                "confluence_tags": [],
            },
            risk_approved=True,
            manual_approval_required=False,
        )
        await p.commit()

        from backend.db.repositories.base import GenericRepository
        repo = GenericRepository(db_session, TradeSignalRecord)
        record = await repo.get_by_id(signal_id)
        assert record.status == "approved"

    @pytest.mark.asyncio
    async def test_persist_signal_risk_rejected(self, db_session):
        """Risk-rejected signal → status=rejected."""
        p = PipelinePersistence(db_session)
        signal_id = await p.persist_signal(
            signal_dict={
                "symbol": "NAS100", "strategy_id": "ny_sweep_reversal_v1",
                "direction": "long", "confidence": 0.55,
                "entry_price": 18245.5, "stop_price": 18210.0,
                "reward_risk": 1.0, "timestamp": datetime.now(timezone.utc).isoformat(),
                "targets": [], "confluence_tags": [],
            },
            risk_approved=False,
            risk_rejection_reason="daily_loss_limit",
        )
        await p.commit()

        from backend.db.repositories.base import GenericRepository
        repo = GenericRepository(db_session, TradeSignalRecord)
        record = await repo.get_by_id(signal_id)
        assert record.status == "rejected"
        assert record.rejection_reason == "daily_loss_limit"

    @pytest.mark.asyncio
    async def test_persist_risk_event(self, db_session):
        p = PipelinePersistence(db_session)
        event_id = await p.persist_risk_event(
            account_id="test_acct",
            event_type="daily_loss_throttle",
            severity="warning",
            message="Risk reduced by 25% after 5% drawdown",
            auto_action="reduced_risk",
        )
        await p.commit()
        assert event_id

    @pytest.mark.asyncio
    async def test_expire_stale_signals(self, db_session):
        """Pending signals past expiry should be marked expired."""
        p = PipelinePersistence(db_session)

        # Create an already-expired signal
        past = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        await p.signal_repo.create(
            symbol="NAS100", strategy_name="test", timestamp=past,
            side="buy", confidence=0.7, entry_price=18000, stop_price=17990,
            status="pending", expires_at=past, json_payload="{}",
        )
        await p.commit()

        count = await p.expire_stale_signals()
        await p.commit()
        assert count == 1


class TestApprovalWorkflow:

    @pytest.mark.asyncio
    async def test_approve_pending_signal(self, db_session):
        svc = SignalService(db_session)
        sig = await svc.create_signal(
            symbol="NAS100", strategy_name="test", timestamp=datetime.now(timezone.utc).isoformat(),
            side="buy", confidence=0.78, entry_price=18000, stop_price=17990,
            status="pending", json_payload="{}",
        )
        await db_session.commit()

        result = await svc.approve_signal(sig.id, "operator@test")
        await db_session.commit()

        assert result is not None
        assert result.status == "approved"
        assert result.approved_by == "operator@test"

    @pytest.mark.asyncio
    async def test_reject_pending_signal(self, db_session):
        svc = SignalService(db_session)
        sig = await svc.create_signal(
            symbol="NAS100", strategy_name="test", timestamp=datetime.now(timezone.utc).isoformat(),
            side="buy", confidence=0.6, entry_price=18000, stop_price=17990,
            status="pending", json_payload="{}",
        )
        await db_session.commit()

        result = await svc.reject_signal(sig.id, "operator@test", "Low confidence")
        await db_session.commit()

        assert result is not None
        assert result.status == "rejected"
        assert result.rejection_reason == "Low confidence"

    @pytest.mark.asyncio
    async def test_cannot_approve_rejected_signal(self, db_session):
        svc = SignalService(db_session)
        sig = await svc.create_signal(
            symbol="NAS100", strategy_name="test", timestamp=datetime.now(timezone.utc).isoformat(),
            side="buy", confidence=0.7, entry_price=18000, stop_price=17990,
            status="rejected", json_payload="{}",
        )
        await db_session.commit()

        result = await svc.approve_signal(sig.id, "operator@test")
        assert result is None  # Cannot approve a non-pending signal

    @pytest.mark.asyncio
    async def test_cannot_approve_expired_signal(self, db_session):
        svc = SignalService(db_session)
        past = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        sig = await svc.create_signal(
            symbol="NAS100", strategy_name="test", timestamp=past,
            side="buy", confidence=0.7, entry_price=18000, stop_price=17990,
            status="pending", expires_at=past, json_payload="{}",
        )
        await db_session.commit()

        result = await svc.approve_signal(sig.id, "operator@test")
        await db_session.commit()

        # Should auto-expire on approval attempt
        assert result is not None
        assert result.status == "expired"

    @pytest.mark.asyncio
    async def test_only_approved_signals_returned(self, db_session):
        """get_approved_signals should only return status=approved."""
        p = PipelinePersistence(db_session)

        for status in ("pending", "approved", "rejected", "expired", "executed"):
            await p.signal_repo.create(
                symbol="NAS100", strategy_name="test",
                timestamp=datetime.now(timezone.utc).isoformat(),
                side="buy", confidence=0.7, entry_price=18000, stop_price=17990,
                status=status, json_payload="{}",
            )
        await p.commit()

        approved = await p.get_approved_signals(symbol="NAS100")
        assert len(approved) == 1
        assert approved[0].status == "approved"

    @pytest.mark.asyncio
    async def test_mark_executed(self, db_session):
        p = PipelinePersistence(db_session)
        await p.signal_repo.create(
            id="sig_test", symbol="NAS100", strategy_name="test",
            timestamp=datetime.now(timezone.utc).isoformat(),
            side="buy", confidence=0.7, entry_price=18000, stop_price=17990,
            status="approved", json_payload="{}",
        )
        await p.commit()

        await p.mark_signal_executed("sig_test")
        await p.commit()

        record = await p.signal_repo.get_by_id("sig_test")
        assert record.status == "executed"
