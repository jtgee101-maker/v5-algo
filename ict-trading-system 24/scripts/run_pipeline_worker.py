"""Pipeline worker — runs the trading pipeline as a background process.

Connects to TradeLocker, builds market structure, generates signals,
persists everything to the database. The API server reads from the same DB.

Usage (local):
  python scripts/run_pipeline_worker.py

Usage (Render Background Worker):
  Set as start command in render.yaml worker service.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone

import structlog


def setup():
    """Ensure DB tables exist and account record is seeded."""
    from backend.db.session import create_tables_sync, sync_engine
    from backend.db.base import Base
    from backend.settings import DATA_DIR

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    create_tables_sync()

    # Seed account if missing
    from sqlalchemy.orm import Session
    from backend.db.models import Account

    with Session(sync_engine) as session:
        existing = session.query(Account).first()
        if not existing:
            session.add(Account(
                id="acct_demo_1",
                broker_name="gatesfx",
                account_name="GatesFX Demo",
                account_type="demo",
                mode="shadow",
                balance=0,
                equity=0,
                margin_used=0,
                free_margin=0,
                drawdown_pct=0,
                status="disconnected",
                currency="USD",
                updated_at=datetime.now(timezone.utc).isoformat(),
            ))
            session.commit()
            print("Seeded demo account record.")


async def run_pipeline():
    """Run the trading pipeline in shadow mode with manual approval."""
    from core.pipeline import TradingPipeline

    mode = os.environ.get("DEFAULT_MODE", "shadow")
    manual_approval = os.environ.get("MANUAL_APPROVAL", "true").lower() == "true"

    print("=" * 60)
    print(f"ICT Trading Pipeline — {mode.upper()} MODE")
    print(f"Manual approval: {manual_approval}")
    print("=" * 60)

    pipeline = TradingPipeline(mode=mode, manual_approval=manual_approval)
    await pipeline.start()


async def run_agents():
    """Run the agent monitor loop."""
    from core.agents.runtime import AgentScheduler, AgentRunner
    from core.agents.monitor_agent import run_monitor_check
    from core.agents.risk_auditor_agent import run_risk_audit
    from core.agents.strategy_research_agent import run_strategy_research
    from core.agents.self_improver_agent import run_self_improvement_cycle

    scheduler = AgentScheduler()
    scheduler.register("monitor_agent", run_monitor_check, interval_seconds=120)
    scheduler.register("risk_auditor_agent", run_risk_audit, interval_seconds=900)
    scheduler.register("strategy_research_agent", run_strategy_research, interval_seconds=1800)
    scheduler.register("self_improver_agent", run_self_improvement_cycle, interval_seconds=3600)

    print("Agent scheduler started.")
    await scheduler.start()


async def main():
    """Run pipeline + agents concurrently."""
    await asyncio.gather(
        run_pipeline(),
        run_agents(),
    )


if __name__ == "__main__":
    structlog.configure(processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ])

    setup()

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nWorker stopped.")
