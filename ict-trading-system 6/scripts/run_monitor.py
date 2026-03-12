"""Run the agent monitoring loop.

Schedules:
  - monitor_agent: every 120 seconds
  - risk_auditor_agent: every 15 minutes
  - journal_agent daily review: at end of session / on demand
  - strategy_research: every 30 minutes
  - self_improver: every 60 minutes

Usage:
  python scripts/run_monitor.py
  python scripts/run_monitor.py --once  # Single pass, no loop
"""

import argparse
import asyncio

import structlog

from backend.db.session import create_tables_sync
from core.agents.runtime import AgentRunner, AgentScheduler
from core.agents.monitor_agent import run_monitor_check
from core.agents.risk_auditor_agent import run_risk_audit
from core.agents.journal_agent import run_daily_review
from core.agents.strategy_research_agent import run_strategy_research
from core.agents.self_improver_agent import run_self_improvement_cycle


async def run_once():
    """Run all agents once (for testing or manual execution)."""
    print("Running all agents once...")

    agents = [
        ("monitor_agent", run_monitor_check),
        ("risk_auditor_agent", run_risk_audit),
        ("journal_agent", run_daily_review),
        ("strategy_research_agent", run_strategy_research),
        ("self_improver_agent", run_self_improvement_cycle),
    ]

    for name, fn in agents:
        print(f"\n  Running {name}...")
        runner = AgentRunner(name)
        run_id = await runner.run(fn, run_type="manual")
        print(f"  {name} complete (run_id: {run_id})")

    print("\nAll agents complete.")


async def run_scheduled():
    """Run agents on their configured schedules."""
    scheduler = AgentScheduler()

    scheduler.register("monitor_agent", run_monitor_check, interval_seconds=120)
    scheduler.register("risk_auditor_agent", run_risk_audit, interval_seconds=900)
    scheduler.register("strategy_research_agent", run_strategy_research, interval_seconds=1800)
    scheduler.register("self_improver_agent", run_self_improvement_cycle, interval_seconds=3600)

    print("=" * 60)
    print("ICT Trading System — Agent Monitor")
    print("=" * 60)
    print("  monitor_agent:          every 2 min")
    print("  risk_auditor_agent:     every 15 min")
    print("  strategy_research_agent: every 30 min")
    print("  self_improver_agent:    every 60 min")
    print("=" * 60)
    print("Press Ctrl+C to stop.")

    try:
        await scheduler.start()
    except KeyboardInterrupt:
        await scheduler.stop()
        print("\nMonitor stopped.")


def main():
    parser = argparse.ArgumentParser(description="ICT Agent Monitor")
    parser.add_argument("--once", action="store_true", help="Run all agents once then exit")
    args = parser.parse_args()

    structlog.configure(processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ])

    create_tables_sync()

    if args.once:
        asyncio.run(run_once())
    else:
        asyncio.run(run_scheduled())


if __name__ == "__main__":
    main()
