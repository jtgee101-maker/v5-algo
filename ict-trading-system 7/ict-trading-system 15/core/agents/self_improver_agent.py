"""Self-Improver Agent — the meta-agent that measures and proposes system improvements.

Runs the cycle: measure → diagnose → propose → report.
NEVER auto-applies changes. All proposals require human approval.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta

import structlog
from backend.db.session import AsyncSessionLocal
from backend.db.models import (
    AgentRunRecord, IncidentRecord, MarketStateRecord,
    RiskEventRecord, TradeResultRecord, TradeSignalRecord,
)
from backend.db.repositories.base import GenericRepository
from backend.services.core_services import JournalService

logger = structlog.get_logger(__name__)


async def run_self_improvement_cycle() -> str:
    """Run the full measure → diagnose → propose cycle."""
    async with AsyncSessionLocal() as session:
        journal_svc = JournalService(session)

        # ── MEASURE ──────────────────────────────────────────────────
        metrics: dict = {}

        # Signal metrics
        sig_repo = GenericRepository(session, TradeSignalRecord)
        all_signals = await sig_repo.list_all(limit=200, order_by="timestamp", desc=True)
        status_counts = Counter(s.status for s in all_signals)
        metrics["total_signals"] = len(all_signals)
        metrics["status_breakdown"] = dict(status_counts)

        if all_signals:
            avg_conf = sum(s.confidence for s in all_signals) / len(all_signals)
            metrics["avg_confidence"] = round(avg_conf, 3)

        # Trade metrics
        trade_repo = GenericRepository(session, TradeResultRecord)
        trades = await trade_repo.list_all(limit=100, order_by="closed_at", desc=True)
        winners = [t for t in trades if (t.pnl or 0) > 0]
        losers = [t for t in trades if (t.pnl or 0) < 0]
        metrics["total_trades"] = len(trades)
        metrics["winners"] = len(winners)
        metrics["losers"] = len(losers)
        if trades:
            metrics["win_rate"] = round(len(winners) / len(trades), 3)
            metrics["total_pnl"] = round(sum(t.pnl or 0 for t in trades), 2)
        else:
            metrics["win_rate"] = 0
            metrics["total_pnl"] = 0

        # Incident metrics
        inc_repo = GenericRepository(session, IncidentRecord)
        incidents = await inc_repo.list_all(limit=50, order_by="created_at", desc=True)
        open_incidents = [i for i in incidents if i.status == "open"]
        metrics["total_incidents"] = len(incidents)
        metrics["open_incidents"] = len(open_incidents)

        # Risk event metrics
        risk_repo = GenericRepository(session, RiskEventRecord)
        risk_events = await risk_repo.list_all(limit=50, order_by="triggered_at", desc=True)
        metrics["risk_events"] = len(risk_events)
        metrics["critical_risk"] = len([e for e in risk_events if e.severity == "critical"])

        # Agent run metrics
        agent_repo = GenericRepository(session, AgentRunRecord)
        agent_runs = await agent_repo.list_all(limit=50, order_by="started_at", desc=True)
        failed_runs = [r for r in agent_runs if r.status == "failed"]
        metrics["agent_runs"] = len(agent_runs)
        metrics["failed_agent_runs"] = len(failed_runs)

        # ── DIAGNOSE ─────────────────────────────────────────────────
        issues: list[str] = []
        proposals: list[dict] = []

        # Issue: high rejection rate
        rejected = status_counts.get("rejected", 0)
        if metrics["total_signals"] > 0 and rejected / metrics["total_signals"] > 0.7:
            issues.append(f"High signal rejection rate: {rejected}/{metrics['total_signals']}")
            proposals.append({
                "target": "config/strategy.yaml",
                "change": "Lower min_confidence_threshold from 0.65 to 0.60",
                "reason": "Too many signals being rejected — structure detection may be too strict",
                "risk": "Lower confidence may increase false positives",
            })

        # Issue: high expiration rate
        expired = status_counts.get("expired", 0)
        if metrics["total_signals"] > 10 and expired / metrics["total_signals"] > 0.4:
            issues.append(f"High expiration rate: {expired}/{metrics['total_signals']}")
            proposals.append({
                "target": "backend/settings.py",
                "change": "Increase SIGNAL_EXPIRY_SECONDS from 900 to 1800",
                "reason": "Signals expire before operator can review them",
                "risk": "Stale signals may be approved after market conditions change",
            })

        # Issue: negative expectancy
        if metrics["total_pnl"] < 0 and metrics["total_trades"] > 10:
            issues.append(f"Negative total P&L: ${metrics['total_pnl']}")
            proposals.append({
                "target": "config/strategy.yaml",
                "change": "Increase min_reward_risk from 2.0 to 2.5 for sweep reversal",
                "reason": f"Net P&L is ${metrics['total_pnl']} across {metrics['total_trades']} trades",
                "risk": "Fewer setups will qualify — may reduce signal count",
            })

        # Issue: confidence calibration drift
        if metrics.get("avg_confidence", 0) > 0 and metrics["win_rate"] > 0:
            expected = metrics["avg_confidence"]
            actual = metrics["win_rate"]
            drift = abs(expected - actual)
            if drift > 0.15 and metrics["total_trades"] > 10:
                issues.append(f"Confidence calibration drift: expected {expected:.0%}, actual {actual:.0%}")
                proposals.append({
                    "target": "core/strategy/scorer.py",
                    "change": "Re-calibrate confidence weights based on actual win rates per bin",
                    "reason": f"Drift of {drift:.0%} between confidence and realized win rate",
                    "risk": "Requires walk-forward validation before deployment",
                })

        # Issue: unresolved incidents
        if metrics["open_incidents"] > 3:
            issues.append(f"{metrics['open_incidents']} unresolved incidents")

        # Issue: agent failures
        if metrics["failed_agent_runs"] > 2:
            issues.append(f"{metrics['failed_agent_runs']} failed agent runs")

        # ── REPORT ───────────────────────────────────────────────────
        summary_parts = [
            f"Self-improvement cycle complete.",
            f"Metrics: {metrics['total_signals']} signals, {metrics['total_trades']} trades, "
            f"{metrics['win_rate']:.0%} WR, ${metrics['total_pnl']} P&L.",
            f"Issues: {len(issues)}.",
            f"Proposals: {len(proposals)}.",
        ]

        proposal_text = ""
        for i, p in enumerate(proposals):
            proposal_text += (
                f"\nProposal {i+1}: {p['change']}\n"
                f"  Target: {p['target']}\n"
                f"  Reason: {p['reason']}\n"
                f"  Risk: {p['risk']}\n"
            )

        full_summary = " ".join(summary_parts)
        if issues:
            full_summary += " Issues: " + "; ".join(issues)

        await journal_svc.create_entry(
            strategy_name="self_improver",
            symbol="SYSTEM",
            session_name="improvement_cycle",
            summary=full_summary[:500],
            lesson=proposal_text[:2000] if proposals else None,
            tags=json.dumps(["self_improvement", "proposals"]),
            created_by="self_improver_agent",
        )
        await session.commit()

    result = f"Self-improvement: {len(issues)} issues, {len(proposals)} proposals"
    logger.info("self_improver.completed", issues=len(issues), proposals=len(proposals))
    return result
