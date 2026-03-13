"""Run the trading pipeline + scheduled agents as a Render background worker.

Usage:
  python scripts/run_pipeline_worker.py

Environment:
  DEFAULT_MODE=shadow|demo|live (default: shadow)
  MANUAL_APPROVAL=true|false (default: true)
"""

from __future__ import annotations

import asyncio
import os

import structlog

from backend.db.session import create_tables
from core.agents.monitor_agent import run_monitor_check
from core.agents.risk_auditor_agent import run_risk_audit
from core.agents.runtime import AgentScheduler
from core.agents.self_improver_agent import run_self_improvement_cycle
from core.agents.strategy_research_agent import run_strategy_research
from core.pipeline import TradingPipeline


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


async def run_worker() -> None:
    await create_tables()

    mode = os.environ.get("DEFAULT_MODE", "shadow").strip().lower()
    manual_approval = _as_bool(os.environ.get("MANUAL_APPROVAL"), True)

    pipeline = TradingPipeline(mode=mode, manual_approval=manual_approval)

    scheduler = AgentScheduler()
    scheduler.register("monitor_agent", run_monitor_check, interval_seconds=120)
    scheduler.register("risk_auditor_agent", run_risk_audit, interval_seconds=900)
    scheduler.register("strategy_research_agent", run_strategy_research, interval_seconds=1800)
    scheduler.register("self_improver_agent", run_self_improvement_cycle, interval_seconds=3600)

    structlog.get_logger(__name__).info(
        "worker.starting",
        mode=mode,
        manual_approval=manual_approval,
        agents=4,
    )

    await asyncio.gather(
        pipeline.start(),
        scheduler.start(),
    )


def main() -> None:
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
    )
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
