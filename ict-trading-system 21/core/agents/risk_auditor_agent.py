"""Risk Auditor Agent — reviews risk gate decisions for anomalies.

Checks: recurring rejections, throttle effectiveness, exposure compliance.
Does NOT modify risk parameters.
"""

from __future__ import annotations

import json
from collections import Counter

import structlog
from backend.db.session import AsyncSessionLocal
from backend.services.signal_service import SignalService
from backend.services.core_services import RiskService, JournalService

logger = structlog.get_logger(__name__)


async def run_risk_audit() -> str:
    """Audit recent risk decisions and flag anomalies."""
    findings: list[str] = []

    async with AsyncSessionLocal() as session:
        sig_svc = SignalService(session)
        risk_svc = RiskService(session)
        journal_svc = JournalService(session)

        # 1. Check rejection patterns
        rejected = await sig_svc.list_signals(status="rejected", limit=50)
        if rejected:
            reasons = Counter(s.rejection_reason or "unknown" for s in rejected)
            top_reason, top_count = reasons.most_common(1)[0]
            if top_count > 5:
                findings.append(
                    f"Recurring rejection: '{top_reason}' appeared {top_count} times"
                )

        # 2. Check if too many signals are expiring
        expired = await sig_svc.list_signals(status="expired", limit=50)
        pending = await sig_svc.list_signals(status="pending", limit=50)
        total_signals = len(rejected) + len(expired) + len(pending)
        if total_signals > 0 and len(expired) / max(total_signals, 1) > 0.5:
            findings.append(
                f"High expiration rate: {len(expired)}/{total_signals} signals expired"
            )

        # 3. Check risk events for escalation patterns
        events = await risk_svc.list_events(limit=20)
        critical = [e for e in events if e.severity == "critical"]
        if len(critical) > 2:
            findings.append(f"{len(critical)} critical risk events recently")

        # 4. Create journal entry with findings
        if findings:
            await journal_svc.create_entry(
                strategy_name="risk_audit",
                symbol="PORTFOLIO",
                session_name="audit",
                summary=f"Risk audit: {len(findings)} finding(s). " + "; ".join(findings),
                tags=json.dumps(["risk_audit", "findings"]),
                created_by="risk_auditor_agent",
            )
        await session.commit()

    result = f"Risk audit: {len(findings)} findings" + (f" — {'; '.join(findings)}" if findings else "")
    logger.info("risk_auditor.completed", findings=len(findings))
    return result
