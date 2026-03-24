"""Run daily trade review via the journal agent.

Usage:
  python scripts/run_daily_review.py
"""

import asyncio
from core.agents.runtime import AgentRunner
from core.agents.journal_agent import run_daily_review


async def main():
    print("Running daily review...")
    runner = AgentRunner("journal_agent")
    run_id = await runner.run(run_daily_review, run_type="manual", input_summary="Daily review")
    print(f"Done. Agent run ID: {run_id}")


if __name__ == "__main__":
    from backend.db.session import create_tables_sync
    create_tables_sync()
    asyncio.run(main())
