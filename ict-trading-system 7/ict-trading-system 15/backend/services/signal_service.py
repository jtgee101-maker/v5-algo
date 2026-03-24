"""Signal service — manages trade signal lifecycle and approval workflow."""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import TradeSignalRecord, ConfigChangeRecord
from backend.db.repositories.base import GenericRepository
from backend.settings import SIGNAL_EXPIRY_SECONDS


class SignalService:
    """Business logic for trade signals and the approval queue."""

    def __init__(self, session: AsyncSession):
        self.repo = GenericRepository(session, TradeSignalRecord)
        self.session = session

    async def list_signals(
        self,
        status: Optional[str] = None,
        symbol: Optional[str] = None,
        limit: int = 50,
    ) -> list[TradeSignalRecord]:
        filters = {}
        if status:
            filters["status"] = status
        if symbol:
            filters["symbol"] = symbol
        return await self.repo.list_all(
            limit=limit, order_by="timestamp", desc=True, **filters
        )

    async def create_signal(self, **kwargs) -> TradeSignalRecord:
        """Create a new signal with proper defaults."""
        if "expires_at" not in kwargs:
            expires = datetime.now(timezone.utc) + timedelta(seconds=SIGNAL_EXPIRY_SECONDS)
            kwargs["expires_at"] = expires.isoformat()
        if "status" not in kwargs:
            kwargs["status"] = "pending"
        return await self.repo.create(**kwargs)

    async def approve_signal(
        self, signal_id: str, approved_by: str, note: Optional[str] = None
    ) -> Optional[TradeSignalRecord]:
        """Approve a pending signal for execution."""
        signal = await self.repo.get_by_id(signal_id)
        if signal is None:
            return None
        if signal.status != "pending":
            return None

        # Check if expired
        if signal.expires_at:
            exp = datetime.fromisoformat(signal.expires_at)
            if datetime.now(timezone.utc) > exp:
                await self.repo.update_by_id(signal_id, status="expired")
                return await self.repo.get_by_id(signal_id)

        now = datetime.now(timezone.utc).isoformat()
        return await self.repo.update_by_id(
            signal_id,
            status="approved",
            approved_by=approved_by,
            approved_at=now,
        )

    async def reject_signal(
        self, signal_id: str, rejected_by: str, reason: str
    ) -> Optional[TradeSignalRecord]:
        """Reject a pending signal."""
        signal = await self.repo.get_by_id(signal_id)
        if signal is None:
            return None
        if signal.status != "pending":
            return None

        now = datetime.now(timezone.utc).isoformat()
        return await self.repo.update_by_id(
            signal_id,
            status="rejected",
            rejected_by=rejected_by,
            rejected_at=now,
            rejection_reason=reason,
        )

    async def expire_stale_signals(self) -> int:
        """Mark expired pending signals. Returns count of expired."""
        pending = await self.list_signals(status="pending", limit=200)
        now = datetime.now(timezone.utc)
        expired_count = 0
        for sig in pending:
            if sig.expires_at:
                exp = datetime.fromisoformat(sig.expires_at)
                if now > exp:
                    await self.repo.update_by_id(sig.id, status="expired")
                    expired_count += 1
        return expired_count

    async def mark_executed(self, signal_id: str) -> Optional[TradeSignalRecord]:
        """Mark an approved signal as executed."""
        return await self.repo.update_by_id(signal_id, status="executed")
