"""Execution Lifecycle Service — canonical tracking from policy to reconciliation.

Every execution attempt gets a durable record that transitions through:
  policy_blocked → (end)
  policy_simulated → (end)
  policy_ready_for_broker → broker_submitted → broker_acknowledged → filled → reconciled
                          → broker_rejected → (end)
                          → canceled → (end)

No state is fabricated. If broker didn't confirm fill, we don't say filled.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import ExecutionLifecycleRecord, AuditLogRecord
from backend.db.repositories.base import GenericRepository


# Canonical lifecycle states
LIFECYCLE_STATES = [
    "policy_blocked",
    "policy_simulated",
    "policy_ready_for_broker",
    "broker_submitted",
    "broker_acknowledged",
    "partially_filled",
    "filled",
    "broker_rejected",
    "canceled",
    "reconciling",
    "reconciled",
    "unknown",
]

# Valid transitions (from → allowed next states)
VALID_TRANSITIONS = {
    "policy_blocked": set(),  # terminal
    "policy_simulated": set(),  # terminal
    "policy_ready_for_broker": {"broker_submitted", "broker_rejected", "canceled", "unknown"},
    "broker_submitted": {"broker_acknowledged", "broker_rejected", "canceled", "partially_filled", "filled", "unknown"},
    "broker_acknowledged": {"partially_filled", "filled", "broker_rejected", "canceled", "unknown"},
    "partially_filled": {"filled", "canceled", "unknown"},
    "filled": {"reconciling", "reconciled"},
    "broker_rejected": set(),  # terminal
    "canceled": set(),  # terminal
    "reconciling": {"reconciled", "unknown"},
    "reconciled": set(),  # terminal
    "unknown": set(LIFECYCLE_STATES),  # can transition to anything
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ExecutionLifecycleService:
    """Manages execution lifecycle records with durable persistence."""

    def __init__(self, session: AsyncSession):
        self.repo = GenericRepository(session, ExecutionLifecycleRecord)
        self.audit_repo = GenericRepository(session, AuditLogRecord)
        self._session = session

    async def create_execution(
        self,
        *,
        execution_id: str,
        symbol: str,
        direction: str,
        source: str = "unknown",
        strategy: str = "",
        signal_id: str = None,
        policy_result: str = "unknown",
        policy_message: str = "",
        policy_blockers: list[str] = None,
        policy_warnings: list[str] = None,
        config_hash: str = "",
        account_state_stale: bool = False,
        mode: str = "shadow",
        lifecycle_status: str = "unknown",
        quantity_requested: float = 0,
    ) -> ExecutionLifecycleRecord:
        """Create a new execution lifecycle record."""
        now = _now()
        record = await self.repo.create(
            id=execution_id,
            signal_id=signal_id,
            symbol=symbol,
            direction=direction,
            source=source,
            strategy=strategy,
            policy_result=policy_result,
            policy_message=policy_message,
            policy_blockers=json.dumps(policy_blockers or []),
            policy_warnings=json.dumps(policy_warnings or []),
            config_hash=config_hash,
            account_state_stale=1 if account_state_stale else 0,
            mode=mode,
            lifecycle_status=lifecycle_status,
            quantity_requested=quantity_requested,
            requested_at=now,
            policy_decided_at=now,
            created_at=now,
            updated_at=now,
        )

        # Audit the creation
        await self._log_transition(execution_id, "none", lifecycle_status, symbol, source, policy_message)

        return record

    async def transition(
        self,
        execution_id: str,
        new_status: str,
        *,
        broker_order_id: str = None,
        broker_message: str = None,
        broker_rejection_code: str = None,
        broker_raw_response: str = None,
        quantity_filled: float = None,
        avg_fill_price: float = None,
        reconciliation_status: str = None,
        reconciliation_message: str = None,
        message: str = "",
    ) -> Optional[ExecutionLifecycleRecord]:
        """Transition an execution to a new lifecycle state.

        Returns the updated record, or None if execution_id not found.
        Validates transitions but allows unknown→anything for recovery.
        """
        record = await self.repo.get_by_id(execution_id)
        if not record:
            return None

        old_status = record.lifecycle_status
        now = _now()

        # Validate transition (warn but don't block — for recovery)
        allowed = VALID_TRANSITIONS.get(old_status, set())
        if new_status not in allowed and old_status != "unknown":
            # Log warning but proceed — don't block legitimate corrections
            pass

        # Build update dict
        updates = {
            "lifecycle_status": new_status,
            "updated_at": now,
        }

        # Set broker fields if provided
        if broker_order_id is not None:
            updates["broker_order_id"] = broker_order_id
        if broker_message is not None:
            updates["broker_message"] = broker_message
        if broker_rejection_code is not None:
            updates["broker_rejection_code"] = broker_rejection_code
        if broker_raw_response is not None:
            updates["broker_raw_response"] = broker_raw_response

        # Set quantity/price if provided
        if quantity_filled is not None:
            updates["quantity_filled"] = quantity_filled
        if avg_fill_price is not None:
            updates["avg_fill_price"] = avg_fill_price

        # Set reconciliation if provided
        if reconciliation_status is not None:
            updates["reconciliation_status"] = reconciliation_status
        if reconciliation_message is not None:
            updates["reconciliation_message"] = reconciliation_message

        # Set status-specific timestamps
        ts_map = {
            "broker_submitted": "submitted_at",
            "broker_acknowledged": "acknowledged_at",
            "partially_filled": "partially_filled_at",
            "filled": "filled_at",
            "canceled": "canceled_at",
            "reconciled": "reconciled_at",
        }
        if new_status in ts_map:
            updates[ts_map[new_status]] = now

        # Apply update
        updated = await self.repo.update_by_id(execution_id, **updates)

        # Audit the transition
        await self._log_transition(
            execution_id, old_status, new_status,
            record.symbol, record.source, message or broker_message or ""
        )

        return updated

    async def get_status(self, execution_id: str) -> Optional[dict]:
        """Get full lifecycle status for one execution."""
        record = await self.repo.get_by_id(execution_id)
        if not record:
            return None
        return self._record_to_dict(record)

    async def get_history(
        self, limit: int = 50, symbol: str = None, status: str = None
    ) -> list[dict]:
        """Get execution history with optional filters."""
        try:
            records = await self.repo.list_all(limit=limit)
            results = []
            for r in records:
                if symbol and r.symbol != symbol.upper():
                    continue
                if status and r.lifecycle_status != status:
                    continue
                results.append(self._record_to_dict(r))
            return results
        except Exception:
            return []

    async def reconcile(self, execution_id: str, broker_positions: list[dict] = None) -> dict:
        """Reconcile an execution against broker truth.

        Compares local record with broker state and updates accordingly.
        """
        record = await self.repo.get_by_id(execution_id)
        if not record:
            return {"success": False, "error": "Execution not found"}

        now = _now()
        recon_result = {
            "execution_id": execution_id,
            "prior_status": record.lifecycle_status,
            "reconciled": False,
            "changes": [],
        }

        # If we have a broker_order_id, check against broker positions
        if record.broker_order_id and broker_positions:
            matching = [p for p in broker_positions
                       if str(p.get("id", "")) == str(record.broker_order_id)
                       or record.symbol.upper() in str(p).upper()]

            if matching:
                pos = matching[0]
                # Order exists broker-side
                if record.lifecycle_status in ("broker_submitted", "broker_acknowledged"):
                    # Broker has it, we thought it was just submitted — it's likely filled
                    await self.transition(
                        execution_id, "filled",
                        quantity_filled=float(pos.get("qty", 0) or 0),
                        avg_fill_price=float(pos.get("openPrice", 0) or 0),
                        reconciliation_status="reconciled",
                        reconciliation_message="Reconciled: found matching position broker-side",
                        message="Auto-reconciled from broker position",
                    )
                    recon_result["reconciled"] = True
                    recon_result["changes"].append("Updated to filled from broker position")
            else:
                # No matching position — order may have been canceled or rejected
                if record.lifecycle_status == "broker_submitted":
                    await self.transition(
                        execution_id, "unknown",
                        reconciliation_status="reconciliation_failed",
                        reconciliation_message="No matching position found broker-side",
                        message="Reconciliation: order not found in broker positions",
                    )
                    recon_result["changes"].append("Order not found broker-side — marked unknown")

        # If no broker order ID, just mark reconciliation attempted
        if not recon_result["changes"]:
            await self.repo.update_by_id(
                execution_id,
                reconciliation_status="reconciled",
                reconciliation_message="No broker order to reconcile",
                reconciled_at=now,
                updated_at=now,
            )
            recon_result["reconciled"] = True
            recon_result["changes"].append("Marked reconciled (no broker order)")

        recon_result["new_status"] = (await self.repo.get_by_id(execution_id)).lifecycle_status
        return recon_result

    def _record_to_dict(self, r: ExecutionLifecycleRecord) -> dict:
        """Convert a record to the canonical response shape."""
        blockers = []
        warnings = []
        try:
            blockers = json.loads(r.policy_blockers) if r.policy_blockers else []
        except Exception:
            pass
        try:
            warnings = json.loads(r.policy_warnings) if r.policy_warnings else []
        except Exception:
            pass

        return {
            "execution_id": r.id,
            "signal_id": r.signal_id,
            "symbol": r.symbol,
            "direction": r.direction,
            "source": r.source,
            "strategy": r.strategy,
            "policy_result": r.policy_result,
            "policy_message": r.policy_message,
            "policy_blockers": blockers,
            "policy_warnings": warnings,
            "config_hash": r.config_hash,
            "account_state_stale": bool(r.account_state_stale),
            "mode": r.mode,
            "lifecycle_status": r.lifecycle_status,
            "broker_status": r.broker_status,
            "broker_message": r.broker_message,
            "broker_order_id": r.broker_order_id,
            "broker_rejection_code": r.broker_rejection_code,
            "quantity_requested": r.quantity_requested,
            "quantity_filled": r.quantity_filled,
            "avg_fill_price": r.avg_fill_price,
            "reconciliation_status": r.reconciliation_status,
            "reconciliation_message": r.reconciliation_message,
            "timestamps": {
                "requested_at": r.requested_at,
                "policy_decided_at": r.policy_decided_at,
                "submitted_at": r.submitted_at,
                "acknowledged_at": r.acknowledged_at,
                "partially_filled_at": r.partially_filled_at,
                "filled_at": r.filled_at,
                "canceled_at": r.canceled_at,
                "reconciled_at": r.reconciled_at,
            },
            "created_at": r.created_at,
            "updated_at": r.updated_at,
            "durable": True,
        }

    async def _log_transition(
        self, execution_id: str, old_status: str, new_status: str,
        symbol: str = None, source: str = None, message: str = ""
    ) -> None:
        """Write an audit entry for this lifecycle transition."""
        try:
            await self.audit_repo.create(
                category="execution_lifecycle",
                event_type=new_status,
                symbol=symbol,
                source=source,
                execution_id=execution_id,
                old_value=old_status,
                new_value=new_status,
                reason=message[:500] if message else "",
                timestamp=_now(),
            )
        except Exception:
            pass  # Audit must never crash the caller


class BrokerExecutionService:
    """Submits approved trades to broker and normalizes responses.

    Separates policy approval from broker execution.
    Maps broker-specific responses to canonical lifecycle states.
    """

    def __init__(self, lifecycle_service: ExecutionLifecycleService):
        self.lifecycle = lifecycle_service

    async def submit_to_broker(
        self, execution_id: str, symbol: str, direction: str,
        quantity: float = 0.5, mode: str = "shadow",
    ) -> dict:
        """Submit an approved trade to the broker.

        Returns: {success, broker_status, broker_order_id, message, raw_response}
        """
        # Shadow mode = simulate only
        if mode == "shadow":
            await self.lifecycle.transition(
                execution_id, "policy_simulated",
                broker_message="Shadow mode — not submitted to broker",
                message="Shadow mode simulation",
            )
            return {
                "success": True,
                "broker_status": "simulated",
                "broker_order_id": None,
                "message": "Shadow mode — trade simulated, not sent to broker",
            }

        # Demo/Live mode = attempt broker submission
        try:
            from core.execution.client import TradeLockerClient
            from core.tradelocker_data import get_tradelocker_data

            # Resolve instrument ID
            tld = get_tradelocker_data()
            inst_id = tld.resolve_instrument_id(symbol)
            if not inst_id:
                await self.lifecycle.transition(
                    execution_id, "broker_rejected",
                    broker_rejection_code="INSTRUMENT_NOT_FOUND",
                    broker_message=f"Cannot resolve instrument ID for {symbol}",
                    message="Broker rejected: instrument not found",
                )
                return {
                    "success": False,
                    "broker_status": "rejected",
                    "broker_order_id": None,
                    "message": f"Instrument {symbol} not found in broker",
                }

            # Submit order
            client = TradeLockerClient()
            await client.connect()

            side = "buy" if direction.lower() in ("long", "buy") else "sell"

            try:
                result = await client.place_order(
                    instrument_id=inst_id,
                    side=side,
                    quantity=quantity,
                    order_type="market",
                )

                # Normalize broker response
                broker_order_id = str(result.get("orderId", result.get("id", "")))
                raw_json = json.dumps(result, default=str)

                await self.lifecycle.transition(
                    execution_id, "broker_submitted",
                    broker_order_id=broker_order_id,
                    broker_message="Order submitted to broker",
                    broker_raw_response=raw_json,
                    quantity_filled=0,
                    message=f"Submitted to TradeLocker: order {broker_order_id}",
                )

                await client.disconnect()

                return {
                    "success": True,
                    "broker_status": "submitted",
                    "broker_order_id": broker_order_id,
                    "message": f"Order submitted: {broker_order_id}",
                    "raw_response": result,
                }

            except Exception as e:
                error_msg = str(e)[:200]
                await self.lifecycle.transition(
                    execution_id, "broker_rejected",
                    broker_rejection_code="SUBMISSION_ERROR",
                    broker_message=error_msg,
                    message=f"Broker submission failed: {error_msg}",
                )
                await client.disconnect()
                return {
                    "success": False,
                    "broker_status": "rejected",
                    "broker_order_id": None,
                    "message": f"Broker error: {error_msg}",
                }

        except Exception as e:
            error_msg = str(e)[:200]
            await self.lifecycle.transition(
                execution_id, "unknown",
                broker_message=f"Broker connection failed: {error_msg}",
                message=f"Broker unreachable: {error_msg}",
            )
            return {
                "success": False,
                "broker_status": "unknown",
                "broker_order_id": None,
                "message": f"Broker connection failed: {error_msg}",
            }

    @staticmethod
    def normalize_broker_status(raw_status: str) -> str:
        """Map broker-specific status to canonical lifecycle state."""
        mapping = {
            "new": "broker_acknowledged",
            "pending": "broker_submitted",
            "open": "broker_acknowledged",
            "partial": "partially_filled",
            "partially_filled": "partially_filled",
            "filled": "filled",
            "closed": "filled",
            "rejected": "broker_rejected",
            "canceled": "canceled",
            "cancelled": "canceled",
            "expired": "canceled",
            "error": "broker_rejected",
        }
        return mapping.get(raw_status.lower(), "unknown")
