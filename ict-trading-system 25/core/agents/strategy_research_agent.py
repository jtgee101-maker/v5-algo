"""Strategy Research Agent — reviews signal quality by confluence tag and regime.

Compares strategy variants, analyzes which confluence tags correlate with
winning trades, and suggests threshold adjustments. NEVER auto-edits live logic.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict

import structlog
from backend.db.session import AsyncSessionLocal
from backend.services.core_services import JournalService, TradeService
from backend.services.signal_service import SignalService

logger = structlog.get_logger(__name__)


async def run_strategy_research() -> str:
    """Analyze signal-to-outcome quality and produce recommendations."""
    findings: list[str] = []
    recommendations: list[str] = []

    async with AsyncSessionLocal() as session:
        sig_svc = SignalService(session)
        trade_svc = TradeService(session)
        journal_svc = JournalService(session)

        # 1. Analyze executed signals vs outcomes
        executed = await sig_svc.list_signals(status="executed", limit=100)
        trades = await trade_svc.list_trades(limit=100)

        if not executed:
            return "Not enough executed signals for analysis."

        # 2. Confidence vs outcome correlation
        high_conf_signals = [s for s in executed if s.confidence >= 0.75]
        low_conf_signals = [s for s in executed if s.confidence < 0.65]

        findings.append(
            f"Executed signals: {len(executed)} total, "
            f"{len(high_conf_signals)} high-confidence (>=0.75), "
            f"{len(low_conf_signals)} low-confidence (<0.65)"
        )

        # 3. Confluence tag analysis
        tag_wins: dict[str, int] = defaultdict(int)
        tag_total: dict[str, int] = defaultdict(int)

        for sig in executed:
            tags = []
            if sig.confluence_tags:
                try:
                    tags = json.loads(sig.confluence_tags)
                except (json.JSONDecodeError, TypeError):
                    pass

            # Find matching trade result
            matching_trades = [t for t in trades if t.symbol == sig.symbol
                               and t.strategy_name == sig.strategy_name]
            is_winner = any((t.pnl or 0) > 0 for t in matching_trades)

            for tag in tags:
                tag_total[tag] += 1
                if is_winner:
                    tag_wins[tag] += 1

        if tag_total:
            tag_report = []
            for tag, total in sorted(tag_total.items(), key=lambda x: -x[1]):
                win_rate = tag_wins.get(tag, 0) / total if total > 0 else 0
                tag_report.append(f"{tag}: {total} signals, {win_rate:.0%} WR")
                if win_rate < 0.3 and total >= 5:
                    recommendations.append(
                        f"Consider removing '{tag}' as confluence — "
                        f"only {win_rate:.0%} win rate across {total} signals"
                    )
                if win_rate > 0.7 and total >= 5:
                    recommendations.append(
                        f"'{tag}' shows strong edge ({win_rate:.0%} WR) — "
                        f"consider increasing its confidence boost weight"
                    )
            findings.append("Tag analysis: " + "; ".join(tag_report))

        # 4. Strategy-level comparison
        by_strategy: dict[str, list] = defaultdict(list)
        for sig in executed:
            by_strategy[sig.strategy_name].append(sig)

        for strat_name, strat_sigs in by_strategy.items():
            avg_conf = sum(s.confidence for s in strat_sigs) / len(strat_sigs)
            findings.append(f"{strat_name}: {len(strat_sigs)} signals, avg confidence {avg_conf:.2f}")

            if avg_conf < 0.60:
                recommendations.append(
                    f"{strat_name}: average confidence below 0.60 — "
                    f"review structure detection thresholds"
                )

        # 5. Persist findings as journal entry
        summary = f"Strategy research: {len(findings)} findings, {len(recommendations)} recommendations"
        detail = "\n".join(findings + ["---"] + recommendations)

        await journal_svc.create_entry(
            strategy_name="strategy_research",
            symbol="PORTFOLIO",
            session_name="research",
            summary=summary,
            lesson=detail[:2000] if recommendations else None,
            tags=json.dumps(["strategy_research", "recommendations"]),
            created_by="strategy_research_agent",
        )
        await session.commit()

    result = f"Strategy research: {len(findings)} findings, {len(recommendations)} recs"
    logger.info("strategy_research.completed", findings=len(findings), recs=len(recommendations))
    return result
