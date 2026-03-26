"""Agent runtime — schedules and runs all Claude agents.

Agents advise and review. They NEVER directly modify live strategy/risk/execution.
All agent outputs are persisted for human review.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import AsyncSessionLocal
from backend.services.core_services import AgentService

logger = structlog.get_logger(__name__)


class AgentRunner:
    """Runs an agent function with persistence and error handling."""

    def __init__(self, agent_name: str):
        self.agent_name = agent_name

    async def run(
        self,
        fn,
        run_type: str = "scheduled",
        input_summary: str = "",
    ) -> Optional[str]:
        """Execute an agent function with audit trail.

        Returns the agent run ID.
        """
        async with AsyncSessionLocal() as session:
            svc = AgentService(session)
            run = await svc.start_run(self.agent_name, run_type, input_summary)
            await session.commit()
            run_id = run.id

        try:
            output = await fn()
            output_str = str(output) if output else "completed"

            async with AsyncSessionLocal() as session:
                svc = AgentService(session)
                await svc.complete_run(run_id, output_summary=output_str[:2000])
                await session.commit()

            logger.info(f"agent.{self.agent_name}.completed", run_id=run_id)
            return run_id

        except Exception as e:
            async with AsyncSessionLocal() as session:
                svc = AgentService(session)
                await svc.complete_run(run_id, error=str(e)[:2000])
                await session.commit()

            logger.error(f"agent.{self.agent_name}.failed", run_id=run_id, error=str(e))
            return run_id


class AgentScheduler:
    """Simple scheduler that runs agents at fixed intervals."""

    def __init__(self):
        self.agents: list[tuple[str, callable, int]] = []  # (name, fn, interval_seconds)
        self.running = False

    def register(self, name: str, fn, interval_seconds: int):
        self.agents.append((name, fn, interval_seconds))

    async def start(self):
        self.running = True
        tasks = [self._run_loop(name, fn, interval) for name, fn, interval in self.agents]
        await asyncio.gather(*tasks)

    async def stop(self):
        self.running = False

    async def _run_loop(self, name: str, fn, interval: int):
        runner = AgentRunner(name)
        while self.running:
            await runner.run(fn, run_type="scheduled")
            await asyncio.sleep(interval)
