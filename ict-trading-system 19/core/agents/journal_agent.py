"""Journal Agent — reviews closed trades and produces session summaries.

Reads trade results, tags patterns, creates journal entries.
Does NOT modify strategy or execution.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import AsyncSessionLocal
from backend.services.core_services import JournalService, TradeService

logger = structlog.get_logger(__name__)


async def run_daily_review() -> str:
    """Review today's closed trades and create journal entries."""
    async with AsyncSessionLocal() as session:
        trade_svc = TradeService(session)
        journal_svc = JournalService(session)

        trades = await trade_svc.list_trades(status="closed", limit=50)
        if not trades:
            return "No closed trades to review today."

        # Analyze trades
        winners = [t for t in trades if (t.pnl or 0) > 0]
        losers = [t for t in trades if (t.pnl or 0) < 0]
        total_pnl = sum(t.pnl or 0 for t in trades)

        # Create summary journal entry
        summary_parts = [
            f"Daily review: {len(trades)} trades closed.",
            f"Winners: {len(winners)}, Losers: {len(losers)}.",
            f"Net P&L: ${total_pnl:.2f}.",
        ]

        if winners:
            best = max(winners, key=lambda t: t.pnl or 0)
            summary_parts.append(
                f"Best trade: {best.symbol} +${best.pnl:.2f} ({best.strategy_name})."
            )

        if losers:
            worst = min(losers, key=lambda t: t.pnl or 0)
            summary_parts.append(
                f"Worst trade: {worst.symbol} ${worst.pnl:.2f} ({worst.strategy_name})."
            )

        tags = ["daily_review"]
        if len(winners) > len(losers):
            tags.append("net_positive")
        elif len(losers) > len(winners):
            tags.append("net_negative")

        lesson = None
        if losers and winners:
            avg_win = sum(t.pnl or 0 for t in winners) / len(winners)
            avg_loss = abs(sum(t.pnl or 0 for t in losers) / len(losers))
            if avg_loss > avg_win * 1.5:
                lesson = "Average loss significantly exceeds average win — review stop placement."
            elif avg_win > avg_loss * 2:
                lesson = "Good risk/reward ratio maintained today."

        await journal_svc.create_entry(
            strategy_name="all",
            symbol="PORTFOLIO",
            session_name="ny",
            summary=" ".join(summary_parts),
            lesson=lesson,
            tags=json.dumps(tags),
            created_by="journal_agent",
        )

        await session.commit()

    result = f"Daily review complete: {len(trades)} trades, P&L ${total_pnl:.2f}"
    logger.info("journal_agent.daily_review", trades=len(trades), pnl=total_pnl)
    return result


async def run_weekly_review() -> str:
    """Run a weekly analytics summary."""
    async with AsyncSessionLocal() as session:
        trade_svc = TradeService(session)
        journal_svc = JournalService(session)

        trades = await trade_svc.list_trades(limit=200)
        if not trades:
            return "No trades this week."

        total = len(trades)
        winners = [t for t in trades if (t.pnl or 0) > 0]
        win_rate = len(winners) / total if total > 0 else 0
        total_pnl = sum(t.pnl or 0 for t in trades)

        # Strategy breakdown
        by_strategy: dict[str, list] = {}
        for t in trades:
            key = t.strategy_name or "unknown"
            by_strategy.setdefault(key, []).append(t)

        strat_summary = []
        for strat, strat_trades in by_strategy.items():
            strat_wins = [t for t in strat_trades if (t.pnl or 0) > 0]
            strat_wr = len(strat_wins) / len(strat_trades) if strat_trades else 0
            strat_pnl = sum(t.pnl or 0 for t in strat_trades)
            strat_summary.append(f"{strat}: {len(strat_trades)} trades, {strat_wr:.0%} WR, ${strat_pnl:.2f}")

        summary = (
            f"Weekly review: {total} trades, {win_rate:.0%} win rate, "
            f"Net P&L ${total_pnl:.2f}. "
            f"By strategy: {'; '.join(strat_summary)}"
        )

        await journal_svc.create_entry(
            strategy_name="all",
            symbol="PORTFOLIO",
            session_name="weekly",
            summary=summary,
            tags=json.dumps(["weekly_review"]),
            created_by="journal_agent",
        )
        await session.commit()

    logger.info("journal_agent.weekly_review", trades=total, pnl=total_pnl)
    return summary
