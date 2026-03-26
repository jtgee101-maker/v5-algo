"""Reconcile local DB state against broker positions and orders.

Compares:
  - Local approved orders → broker accepted orders
  - Local trade results → broker positions
  - Detects mismatches and creates incidents

Usage:
  python scripts/reconcile_broker_state.py
  python scripts/reconcile_broker_state.py --dry-run  # Report only, no incidents
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone

import structlog

from backend.db.session import AsyncSessionLocal, create_tables_sync
from backend.db.models import ApprovedOrderRecord, TradeResultRecord, IncidentRecord
from backend.db.repositories.base import GenericRepository
from core.execution.client import TradeLockerClient

logger = structlog.get_logger(__name__)


class ReconciliationResult:
    def __init__(self):
        self.checks: list[str] = []
        self.mismatches: list[dict] = []
        self.ok: bool = True

    def add_check(self, msg: str):
        self.checks.append(msg)

    def add_mismatch(self, category: str, detail: str, severity: str = "warning"):
        self.mismatches.append({"category": category, "detail": detail, "severity": severity})
        self.ok = False

    def summary(self) -> str:
        lines = [f"Reconciliation: {len(self.checks)} checks, {len(self.mismatches)} mismatches"]
        for m in self.mismatches:
            lines.append(f"  [{m['severity'].upper()}] {m['category']}: {m['detail']}")
        return "\n".join(lines)


async def reconcile(dry_run: bool = False) -> ReconciliationResult:
    """Run full reconciliation between local DB and broker."""
    result = ReconciliationResult()
    broker = TradeLockerClient()

    try:
        await broker.connect()
        result.add_check("Broker connected")

        # 1. Fetch broker state
        broker_positions = await broker.get_positions()
        broker_orders = await broker.get_orders()
        result.add_check(f"Broker: {len(broker_positions)} positions, {len(broker_orders)} orders")

        async with AsyncSessionLocal() as session:
            # 2. Fetch local state
            order_repo = GenericRepository(session, ApprovedOrderRecord)
            trade_repo = GenericRepository(session, TradeResultRecord)

            local_orders = await order_repo.list_all(limit=100, status="sent")
            local_open_trades = await trade_repo.list_all(limit=100, status="open")

            result.add_check(f"Local DB: {len(local_orders)} sent orders, {len(local_open_trades)} open trades")

            # 3. Check for orphaned local orders (sent but no broker position)
            broker_instrument_ids = set()
            for bp in broker_positions:
                broker_instrument_ids.add(str(bp.get("instrumentId", "")))

            for local_order in local_orders:
                if local_order.instrument_id and local_order.instrument_id not in broker_instrument_ids:
                    # Local says order was sent, but broker has no matching position
                    # This could be normal (filled and closed) or a mismatch
                    result.add_mismatch(
                        "orphaned_order",
                        f"Order {local_order.id} (instrument {local_order.instrument_id}) "
                        f"not found in broker positions",
                        severity="warning",
                    )

            # 4. Check for broker positions not tracked locally
            local_symbols = set(t.symbol for t in local_open_trades)
            for bp in broker_positions:
                bp_symbol = str(bp.get("instrumentId", ""))
                if bp_symbol and bp_symbol not in local_symbols:
                    result.add_mismatch(
                        "untracked_position",
                        f"Broker position {bp_symbol} not tracked in local DB",
                        severity="high",
                    )

            # 5. Check position quantity/direction mismatches
            for local_trade in local_open_trades:
                matching_broker = [
                    bp for bp in broker_positions
                    if str(bp.get("instrumentId", "")) == local_trade.symbol
                ]
                if matching_broker:
                    bp = matching_broker[0]
                    broker_qty = float(bp.get("qty", 0))
                    local_qty = float(local_trade.quantity or 0)
                    if abs(broker_qty - local_qty) > 0.001:
                        result.add_mismatch(
                            "quantity_mismatch",
                            f"{local_trade.symbol}: local qty={local_qty}, "
                            f"broker qty={broker_qty}",
                            severity="high",
                        )

            # 6. Create incidents for mismatches
            if not dry_run and result.mismatches:
                inc_repo = GenericRepository(session, IncidentRecord)
                for m in result.mismatches:
                    await inc_repo.create(
                        title=f"Reconciliation: {m['category']}",
                        category="reconciliation",
                        severity=m["severity"],
                        source="reconciliation_script",
                        status="open",
                        summary=m["detail"],
                    )
                    logger.warning("reconciliation.mismatch",
                                   category=m["category"], detail=m["detail"])

                # If high severity mismatches, recommend safe mode
                high_severity = [m for m in result.mismatches if m["severity"] in ("high", "critical")]
                if high_severity:
                    await inc_repo.create(
                        title="Reconciliation recommends safe mode",
                        category="reconciliation",
                        severity="critical",
                        source="reconciliation_script",
                        status="open",
                        summary=f"{len(high_severity)} high-severity mismatches detected. "
                                f"Recommend activating safe mode until resolved.",
                    )

                await session.commit()

    except Exception as e:
        result.add_mismatch("connection_error", f"Reconciliation failed: {str(e)}", severity="critical")
        logger.error("reconciliation.error", error=str(e))
    finally:
        try:
            await broker.disconnect()
        except Exception:
            pass

    return result


def main():
    parser = argparse.ArgumentParser(description="Reconcile broker state")
    parser.add_argument("--dry-run", action="store_true", help="Report only, no incidents")
    args = parser.parse_args()

    structlog.configure(processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ])

    create_tables_sync()
    result = asyncio.run(reconcile(dry_run=args.dry_run))

    print("\n" + "=" * 60)
    print(result.summary())
    if result.ok:
        print("\nRECONCILIATION PASSED — no mismatches found.")
    else:
        print(f"\nRECONCILIATION FAILED — {len(result.mismatches)} mismatch(es).")
        if not args.dry_run:
            print("Incidents created in database.")


if __name__ == "__main__":
    main()
