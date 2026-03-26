"""Durable Audit Service — persists all critical decisions to database.

Categories:
  risk_decision — every RiskPolicyEngine evaluation
  execution — every ExecutionGate attempt
  config_change — runtime config updates
  kill_switch — activations/deactivations
  breaker — circuit breaker trips/resets
  scanner_promotion — scanner → signal promotions
  signal_action — approve/reject decisions
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import AuditLogRecord
from backend.db.repositories.base import GenericRepository


class DurableAuditService:
    """Persists audit entries to the audit_log table."""

    def __init__(self, session: AsyncSession):
        self.repo = GenericRepository(session, AuditLogRecord)
        self._session = session

    async def log(
        self,
        *,
        category: str,
        event_type: str,
        symbol: str = None,
        direction: str = None,
        strategy: str = None,
        source: str = None,
        mode: str = None,
        result: str = None,
        blockers: list[str] = None,
        warnings: list[str] = None,
        config_hash: str = None,
        execution_id: str = None,
        actor: str = None,
        old_value: str = None,
        new_value: str = None,
        reason: str = None,
        equity: float = None,
        daily_pnl: float = None,
        payload: dict = None,
    ) -> AuditLogRecord:
        """Write one audit entry. Always succeeds or fails silently."""
        try:
            record = await self.repo.create(
                category=category,
                event_type=event_type,
                symbol=symbol,
                direction=direction,
                strategy=strategy,
                source=source,
                mode=mode,
                result=result,
                blockers=json.dumps(blockers) if blockers else None,
                warnings=json.dumps(warnings) if warnings else None,
                config_hash=config_hash,
                execution_id=execution_id,
                actor=actor,
                old_value=old_value,
                new_value=new_value,
                reason=reason,
                equity=equity,
                daily_pnl=daily_pnl,
                json_payload=json.dumps(payload, default=str) if payload else None,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            return record
        except Exception:
            # Audit logging must never crash the caller
            return None

    async def log_risk_decision(self, decision_dict: dict) -> None:
        """Persist a RiskPolicyEngine decision."""
        req = decision_dict.get("request_snapshot", {})
        await self.log(
            category="risk_decision",
            event_type="approved" if decision_dict.get("approved") else "blocked",
            symbol=req.get("symbol"),
            direction=req.get("direction"),
            strategy=req.get("strategy"),
            source=req.get("source"),
            mode=decision_dict.get("safety_state", {}).get("mode"),
            result="approved" if decision_dict.get("approved") else "blocked",
            blockers=decision_dict.get("blockers"),
            warnings=decision_dict.get("warnings"),
            config_hash=decision_dict.get("config_hash"),
            equity=decision_dict.get("portfolio_snapshot", {}).get("equity"),
            daily_pnl=decision_dict.get("portfolio_snapshot", {}).get("daily_pnl"),
            payload=decision_dict,
        )

    async def log_execution(self, audit: dict) -> None:
        """Persist an ExecutionGate audit record."""
        await self.log(
            category="execution",
            event_type=audit.get("result", "unknown"),
            symbol=audit.get("symbol"),
            direction=audit.get("direction"),
            strategy=audit.get("strategy"),
            source=audit.get("source"),
            mode=audit.get("mode"),
            result=audit.get("result"),
            blockers=audit.get("blockers"),
            warnings=audit.get("warnings"),
            config_hash=audit.get("config_hash"),
            execution_id=audit.get("execution_id"),
            equity=audit.get("equity"),
            daily_pnl=audit.get("daily_pnl"),
            payload=audit,
        )

    async def log_kill_switch(self, action: str, actor: str, reason: str) -> None:
        """Persist kill switch activation/deactivation."""
        await self.log(
            category="kill_switch",
            event_type=action,  # "activated" or "deactivated"
            actor=actor,
            reason=reason,
            source="control",
        )

    async def log_breaker_event(self, event_type: str, breaker_status: dict, source: str = "system") -> None:
        """Persist circuit breaker trip/reset."""
        await self.log(
            category="breaker",
            event_type=event_type,  # "tripped" or "reset"
            source=source,
            reason=breaker_status.get("trip_reason") or breaker_status.get("reset_reason"),
            payload=breaker_status,
        )

    async def log_signal_action(self, signal_id: str, action: str, actor: str, symbol: str = None) -> None:
        """Persist signal approve/reject."""
        await self.log(
            category="signal_action",
            event_type=action,  # "approved" or "rejected"
            symbol=symbol,
            actor=actor,
            execution_id=signal_id,
            source="operator",
        )

    async def log_scanner_promotion(self, symbol: str, direction: str, signal_id: str, confidence: str) -> None:
        """Persist scanner → signal promotion."""
        await self.log(
            category="scanner_promotion",
            event_type="promoted",
            symbol=symbol,
            direction=direction,
            execution_id=signal_id,
            source="scanner",
            payload={"confidence": confidence},
        )

    async def get_recent(self, category: str = None, limit: int = 50) -> list[dict]:
        """Get recent audit entries, optionally filtered by category."""
        try:
            records = await self.repo.list_all(limit=limit)
            # Filter by category if specified
            entries = []
            for r in records:
                d = {
                    "id": r.id,
                    "category": r.category,
                    "event_type": r.event_type,
                    "symbol": r.symbol,
                    "direction": r.direction,
                    "result": r.result,
                    "source": r.source,
                    "mode": r.mode,
                    "config_hash": r.config_hash,
                    "execution_id": r.execution_id,
                    "actor": r.actor,
                    "reason": r.reason,
                    "timestamp": r.timestamp,
                }
                if r.blockers:
                    try:
                        d["blockers"] = json.loads(r.blockers)
                    except Exception:
                        d["blockers"] = []
                if category and r.category != category:
                    continue
                entries.append(d)
            return entries
        except Exception:
            return []
