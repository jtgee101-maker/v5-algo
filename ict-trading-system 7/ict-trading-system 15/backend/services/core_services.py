"""Core services — business logic for all entities except signals (see signal_service.py)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import (
    Account, AgentRunRecord, ConfigChangeRecord, IncidentRecord,
    JournalEntryRecord, MarketStateRecord, RiskEventRecord,
    TradeResultRecord,
)
from backend.db.repositories.base import GenericRepository
from backend.settings import DEFAULT_MODE, LIVE_LOCKED, MANUAL_APPROVAL_REQUIRED


class AccountService:
    def __init__(self, session: AsyncSession):
        self.repo = GenericRepository(session, Account)

    async def get_primary(self) -> Optional[Account]:
        accts = await self.repo.list_all(limit=1, order_by="updated_at")
        return accts[0] if accts else None

    async def upsert(self, **kwargs) -> Account:
        existing = await self.get_primary()
        if existing:
            return await self.repo.update_by_id(existing.id, **kwargs)
        return await self.repo.create(**kwargs)


class MarketService:
    def __init__(self, session: AsyncSession):
        self.repo = GenericRepository(session, MarketStateRecord)

    async def list_states(
        self, symbol: Optional[str] = None, limit: int = 20
    ) -> list[MarketStateRecord]:
        filters = {}
        if symbol:
            filters["symbol"] = symbol
        return await self.repo.list_all(limit=limit, order_by="timestamp", desc=True, **filters)

    async def create(self, **kwargs) -> MarketStateRecord:
        return await self.repo.create(**kwargs)


class TradeService:
    def __init__(self, session: AsyncSession):
        self.repo = GenericRepository(session, TradeResultRecord)

    async def list_trades(
        self, symbol: Optional[str] = None, status: Optional[str] = None, limit: int = 50
    ) -> list[TradeResultRecord]:
        filters = {}
        if symbol:
            filters["symbol"] = symbol
        if status:
            filters["status"] = status
        return await self.repo.list_all(limit=limit, order_by="closed_at", desc=True, **filters)

    async def create(self, **kwargs) -> TradeResultRecord:
        return await self.repo.create(**kwargs)


class RiskService:
    def __init__(self, session: AsyncSession):
        self.repo = GenericRepository(session, RiskEventRecord)

    async def list_events(self, limit: int = 50) -> list[RiskEventRecord]:
        return await self.repo.list_all(limit=limit, order_by="triggered_at", desc=True)

    async def create_event(self, **kwargs) -> RiskEventRecord:
        return await self.repo.create(**kwargs)


class IncidentService:
    def __init__(self, session: AsyncSession):
        self.repo = GenericRepository(session, IncidentRecord)

    async def list_incidents(
        self, status: Optional[str] = None, limit: int = 50
    ) -> list[IncidentRecord]:
        filters = {}
        if status:
            filters["status"] = status
        return await self.repo.list_all(limit=limit, order_by="created_at", desc=True, **filters)

    async def create_incident(self, **kwargs) -> IncidentRecord:
        return await self.repo.create(**kwargs)

    async def resolve(self, incident_id: str) -> Optional[IncidentRecord]:
        now = datetime.now(timezone.utc).isoformat()
        return await self.repo.update_by_id(incident_id, status="resolved", resolved_at=now)


class JournalService:
    def __init__(self, session: AsyncSession):
        self.repo = GenericRepository(session, JournalEntryRecord)

    async def list_entries(self, limit: int = 50) -> list[JournalEntryRecord]:
        return await self.repo.list_all(limit=limit, order_by="created_at", desc=True)

    async def create_entry(self, **kwargs) -> JournalEntryRecord:
        return await self.repo.create(**kwargs)


class AgentService:
    def __init__(self, session: AsyncSession):
        self.repo = GenericRepository(session, AgentRunRecord)

    async def list_runs(self, limit: int = 50) -> list[AgentRunRecord]:
        return await self.repo.list_all(limit=limit, order_by="started_at", desc=True)

    async def start_run(self, agent_name: str, run_type: str, input_summary: str = "") -> AgentRunRecord:
        return await self.repo.create(
            agent_name=agent_name,
            run_type=run_type,
            status="started",
            input_summary=input_summary,
            started_at=datetime.now(timezone.utc).isoformat(),
        )

    async def complete_run(
        self, run_id: str, output_summary: str = "", error: Optional[str] = None
    ) -> Optional[AgentRunRecord]:
        status = "failed" if error else "completed"
        return await self.repo.update_by_id(
            run_id,
            status=status,
            output_summary=output_summary,
            error_message=error,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )


class ConfigService:
    """Manages runtime config with validation, versioning, and audit."""

    def __init__(self, session: AsyncSession):
        self.config_repo = GenericRepository(session, ConfigChangeRecord)
        self._mode = DEFAULT_MODE
        self._manual_approval = MANUAL_APPROVAL_REQUIRED
        self._live_locked = LIVE_LOCKED
        self._risk_config = self._load_risk_config()
        self._symbols = ["NAS100", "US30", "EURUSD", "BTCUSD"]

    def _load_risk_config(self) -> dict:
        try:
            with open("config/risk.yaml") as f:
                cfg = yaml.safe_load(f)
            return {
                "risk_per_trade_pct": cfg["base_risk"]["risk_per_trade"] * 100,
                "max_daily_loss_pct": cfg["limits"]["max_daily_loss"] * 100,
                "max_weekly_loss_pct": cfg["limits"]["max_weekly_loss"] * 100,
                "max_account_drawdown_pct": cfg["limits"]["max_drawdown"] * 100,
            }
        except Exception:
            return {
                "risk_per_trade_pct": 0.25,
                "max_daily_loss_pct": 1.5,
                "max_weekly_loss_pct": 4.0,
                "max_account_drawdown_pct": 18.0,
            }

    def get_config(self) -> dict:
        return {
            "mode": self._mode,
            "manual_approval_required": self._manual_approval,
            "allowed_symbols": self._symbols,
            "risk": self._risk_config,
        }

    async def update_config(self, changed_by: str, reason: str, updates: dict) -> dict:
        applied = {}
        for key, value in updates.items():
            old_value = None
            if key == "manual_approval_required":
                old_value = str(self._manual_approval)
                self._manual_approval = bool(value)
                applied[key] = value
            elif key.startswith("risk."):
                risk_key = key.replace("risk.", "")
                if risk_key in self._risk_config:
                    old_value = str(self._risk_config[risk_key])
                    self._risk_config[risk_key] = float(value)
                    applied[key] = value

            if old_value is not None:
                await self.config_repo.create(
                    config_type="runtime",
                    config_key=key,
                    old_value=old_value,
                    new_value=str(value),
                    changed_by=changed_by,
                    reason=reason or "",
                )
        return applied

    @property
    def mode(self) -> str:
        return self._mode

    @mode.setter
    def mode(self, value: str) -> None:
        if value == "live" and self._live_locked:
            raise ValueError("Live mode is locked. Set LIVE_LOCKED=false to enable.")
        if value not in ("shadow", "demo", "live"):
            raise ValueError(f"Invalid mode: {value}")
        self._mode = value

    @property
    def manual_approval(self) -> bool:
        return self._manual_approval

    @property
    def live_locked(self) -> bool:
        return self._live_locked
