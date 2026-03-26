"""Monitor Agent — checks broker health, data freshness, execution integrity.

This agent advises and creates incidents. It does NOT modify live execution.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import AsyncSessionLocal
from backend.services.core_services import (
    AccountService, IncidentService, MarketService, RiskService,
)

logger = structlog.get_logger(__name__)


async def run_monitor_check() -> str:
    """Run a full health check cycle. Returns summary string."""
    issues: list[str] = []
    checks_passed: list[str] = []

    async with AsyncSessionLocal() as session:
        # 1. Check account state freshness
        acct_svc = AccountService(session)
        acct = await acct_svc.get_primary()
        if acct is None:
            issues.append("No account configured in database")
        elif acct.status != "connected":
            issues.append(f"Account status is '{acct.status}', not connected")
        else:
            # Check if account was updated recently
            try:
                updated = datetime.fromisoformat(acct.updated_at)
                age = (datetime.now(timezone.utc) - updated).total_seconds()
                if age > 300:  # 5 minutes stale
                    issues.append(f"Account state is {int(age)}s stale")
                else:
                    checks_passed.append("account_fresh")
            except (ValueError, TypeError):
                issues.append("Account updated_at is invalid")

        # 2. Check market state freshness
        mkt_svc = MarketService(session)
        recent = await mkt_svc.list_states(limit=1)
        if not recent:
            issues.append("No market states in database")
        else:
            try:
                ts = datetime.fromisoformat(recent[0].timestamp)
                age = (datetime.now(timezone.utc) - ts).total_seconds()
                if age > 600:  # 10 minutes
                    issues.append(f"Latest market state is {int(age)}s old")
                else:
                    checks_passed.append("market_data_fresh")
            except (ValueError, TypeError):
                pass

        # 3. Check for high-severity unresolved risk events
        risk_svc = RiskService(session)
        events = await risk_svc.list_events(limit=10)
        critical_unresolved = [
            e for e in events
            if e.severity == "critical" and e.resolved_at is None
        ]
        if critical_unresolved:
            issues.append(f"{len(critical_unresolved)} unresolved critical risk event(s)")
        else:
            checks_passed.append("no_critical_risk_events")

        # 4. Create incidents for issues
        inc_svc = IncidentService(session)
        for issue in issues:
            await inc_svc.create_incident(
                title=f"Monitor alert: {issue[:80]}",
                category="monitor_check",
                severity="warning" if "stale" in issue.lower() else "high",
                source="monitor_agent",
                status="open",
                summary=issue,
            )

        await session.commit()

    summary = f"Monitor check: {len(checks_passed)} passed, {len(issues)} issues"
    if issues:
        summary += f" — Issues: {'; '.join(issues)}"
    logger.info("monitor_agent.completed", passed=len(checks_passed), issues=len(issues))
    return summary
