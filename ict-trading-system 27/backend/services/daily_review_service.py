"""Daily review service — trade journal with reasoning, streak tracking, daily P&L.

Provides endpoints for:
- Daily performance summary with streak tracking
- Individual trade journals with entry reasoning, expected R:R, and final P&L
- Automated journal generation from signal→approval→execution→close lifecycle
- Weekly rollup reports
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import (
    AgentRunRecord, JournalEntryRecord, TradeResultRecord,
    TradeSignalRecord, ApprovedOrderRecord,
)
from backend.db.repositories.base import GenericRepository

logger = structlog.get_logger(__name__)


class DailyReviewService:
    """Generates daily reviews, trade journals, and streak data."""

    def __init__(self, session: AsyncSession):
        self.signal_repo = GenericRepository(session, TradeSignalRecord)
        self.trade_repo = GenericRepository(session, TradeResultRecord)
        self.order_repo = GenericRepository(session, ApprovedOrderRecord)
        self.journal_repo = GenericRepository(session, JournalEntryRecord)
        self.agent_repo = GenericRepository(session, AgentRunRecord)
        self.session = session

    async def daily_summary(self, date_str: Optional[str] = None) -> dict[str, Any]:
        """Full daily performance summary with streak tracking."""
        if date_str:
            target_date = datetime.fromisoformat(date_str).date()
        else:
            target_date = datetime.now(timezone.utc).date()

        date_prefix = target_date.isoformat()

        # Get all signals for the day
        all_signals = await self.signal_repo.list_all(limit=500, order_by="timestamp", desc=True)
        day_signals = [s for s in all_signals if s.timestamp and s.timestamp.startswith(date_prefix)]

        # Get all trades for the day
        all_trades = await self.trade_repo.list_all(limit=500, order_by="closed_at", desc=True)
        day_trades = [t for t in all_trades if t.closed_at and t.closed_at.startswith(date_prefix)]
        day_opened = [t for t in all_trades if t.opened_at and t.opened_at.startswith(date_prefix)]

        # Compute daily P&L
        closed = [t for t in day_trades if t.status == "closed"]
        winners = [t for t in closed if (t.pnl or 0) > 0]
        losers = [t for t in closed if (t.pnl or 0) < 0]
        daily_pnl = sum(t.pnl or 0 for t in closed)
        daily_fees = sum(t.fees or 0 for t in closed)

        # Signal stats
        pending = len([s for s in day_signals if s.status == "pending"])
        approved = len([s for s in day_signals if s.status in ("approved", "executed")])
        rejected = len([s for s in day_signals if s.status == "rejected"])
        expired = len([s for s in day_signals if s.status == "expired"])

        # Strategy breakdown
        by_strategy = defaultdict(lambda: {"trades": 0, "pnl": 0, "wins": 0})
        for t in closed:
            strat = t.strategy_name or "unknown"
            by_strategy[strat]["trades"] += 1
            by_strategy[strat]["pnl"] += (t.pnl or 0)
            if (t.pnl or 0) > 0:
                by_strategy[strat]["wins"] += 1

        # Symbol breakdown
        by_symbol = defaultdict(lambda: {"trades": 0, "pnl": 0})
        for t in closed:
            by_symbol[t.symbol]["trades"] += 1
            by_symbol[t.symbol]["pnl"] += (t.pnl or 0)

        # Streak calculation
        streak = await self._calculate_streak(all_trades)

        # Best and worst trade
        best = max(closed, key=lambda t: t.pnl or 0) if closed else None
        worst = min(closed, key=lambda t: t.pnl or 0) if closed else None

        return {
            "date": date_prefix,
            "daily_pnl": round(daily_pnl, 2),
            "daily_fees": round(daily_fees, 2),
            "net_pnl": round(daily_pnl - daily_fees, 2),
            "trades_opened": len(day_opened),
            "trades_closed": len(closed),
            "winners": len(winners),
            "losers": len(losers),
            "win_rate": round(len(winners) / len(closed), 4) if closed else 0,
            "signals": {
                "total": len(day_signals),
                "pending": pending,
                "approved": approved,
                "rejected": rejected,
                "expired": expired,
            },
            "by_strategy": {k: v for k, v in by_strategy.items()},
            "by_symbol": {k: v for k, v in by_symbol.items()},
            "streak": streak,
            "best_trade": {
                "symbol": best.symbol, "pnl": best.pnl, "strategy": best.strategy_name
            } if best else None,
            "worst_trade": {
                "symbol": worst.symbol, "pnl": worst.pnl, "strategy": worst.strategy_name
            } if worst else None,
        }

    async def trade_journal(self, trade_id: Optional[str] = None) -> list[dict[str, Any]]:
        """Full trade journal entries with reasoning chain.

        For each trade, shows:
        - Signal reasoning (why it was generated)
        - Confluence tags (what confirmed the setup)
        - Expected R:R at entry
        - Approval decision (who approved and when)
        - Entry execution details
        - Exit details and final P&L
        - Lessons learned
        """
        trades = await self.trade_repo.list_all(limit=100, order_by="closed_at", desc=True)
        if trade_id:
            trades = [t for t in trades if t.id == trade_id]

        all_signals = await self.signal_repo.list_all(limit=500, order_by="timestamp", desc=True)
        all_orders = await self.order_repo.list_all(limit=500, order_by="created_at", desc=True)
        all_journals = await self.journal_repo.list_all(limit=500, order_by="created_at", desc=True)

        journal_entries = []
        for trade in trades:
            # Find the matching order
            order = next((o for o in all_orders if o.id == trade.approved_order_id), None)

            # Find the matching signal
            signal = None
            if order:
                signal = next((s for s in all_signals if s.id == order.signal_id), None)

            # Find any journal notes for this trade
            notes = [j for j in all_journals if j.trade_result_id == trade.id]

            # Calculate expected R:R from signal
            expected_rr = None
            if signal and signal.stop_price and signal.entry_price and signal.take_profit_1:
                risk = abs(signal.entry_price - signal.stop_price)
                reward = abs(signal.take_profit_1 - signal.entry_price)
                expected_rr = round(reward / risk, 2) if risk > 0 else None

            # Calculate actual R:R from trade
            actual_rr = None
            if trade.entry_price and trade.exit_price and trade.stop_price:
                risk = abs(trade.entry_price - trade.stop_price)
                actual_move = trade.exit_price - trade.entry_price
                if trade.symbol and signal and signal.side == "sell":
                    actual_move = trade.entry_price - trade.exit_price
                actual_rr = round(actual_move / risk, 2) if risk > 0 else None

            # Parse confluence tags
            tags = []
            if signal and signal.confluence_tags:
                try:
                    tags = json.loads(signal.confluence_tags)
                except (json.JSONDecodeError, TypeError):
                    tags = signal.confluence_tags.split(",") if signal.confluence_tags else []

            entry = {
                "trade_id": trade.id,
                "symbol": trade.symbol,
                "strategy": trade.strategy_name,
                "status": trade.status,

                # Signal reasoning
                "signal": {
                    "id": signal.id if signal else None,
                    "timestamp": signal.timestamp if signal else None,
                    "side": signal.side if signal else None,
                    "confidence": signal.confidence if signal else None,
                    "confluence_tags": tags,
                    "invalidation": signal.invalidation_reason if signal else None,
                    "risk_score": signal.risk_score if signal else None,
                } if signal else None,

                # Expected trade parameters at signal time
                "expected": {
                    "entry_price": signal.entry_price if signal else None,
                    "stop_price": signal.stop_price if signal else None,
                    "take_profit_1": signal.take_profit_1 if signal else None,
                    "take_profit_2": signal.take_profit_2 if signal else None,
                    "reward_risk": expected_rr,
                    "risk_pct": order.risk_pct if order else None,
                },

                # Approval
                "approval": {
                    "approved_by": signal.approved_by if signal else None,
                    "approved_at": signal.approved_at if signal else None,
                    "rejected_by": signal.rejected_by if signal else None,
                    "rejection_reason": signal.rejection_reason if signal else None,
                },

                # Execution
                "execution": {
                    "opened_at": trade.opened_at,
                    "closed_at": trade.closed_at,
                    "entry_price": trade.entry_price,
                    "exit_price": trade.exit_price,
                    "stop_price": trade.stop_price,
                    "quantity": trade.quantity,
                    "slippage": trade.slippage,
                },

                # Results
                "result": {
                    "pnl": trade.pnl,
                    "pnl_pct": trade.pnl_pct,
                    "fees": trade.fees,
                    "net_pnl": round((trade.pnl or 0) - (trade.fees or 0), 2),
                    "actual_rr": actual_rr,
                    "outcome": "win" if (trade.pnl or 0) > 0 else "loss" if (trade.pnl or 0) < 0 else "breakeven",
                },

                # Lessons
                "notes": [
                    {
                        "summary": j.summary,
                        "lesson": j.lesson,
                        "created_by": j.created_by,
                        "created_at": j.created_at,
                    }
                    for j in notes
                ],
            }
            journal_entries.append(entry)

        return journal_entries

    async def streak_data(self) -> dict[str, Any]:
        """Calculate trading streak and consistency metrics."""
        all_trades = await self.trade_repo.list_all(limit=1000, order_by="closed_at", desc=True)
        return await self._calculate_streak(all_trades)

    async def weekly_rollup(self) -> dict[str, Any]:
        """Weekly performance rollup — last 7 days."""
        now = datetime.now(timezone.utc)
        week_start = (now - timedelta(days=7)).date().isoformat()

        all_trades = await self.trade_repo.list_all(limit=1000, order_by="closed_at", desc=True)
        week_trades = [
            t for t in all_trades
            if t.closed_at and t.closed_at >= week_start and t.status == "closed"
        ]

        all_signals = await self.signal_repo.list_all(limit=1000, order_by="timestamp", desc=True)
        week_signals = [s for s in all_signals if s.timestamp and s.timestamp >= week_start]

        daily_pnl = defaultdict(float)
        for t in week_trades:
            day = t.closed_at[:10] if t.closed_at else "unknown"
            daily_pnl[day] += (t.pnl or 0)

        winners = [t for t in week_trades if (t.pnl or 0) > 0]
        total_pnl = sum(t.pnl or 0 for t in week_trades)
        win_rate = len(winners) / len(week_trades) if week_trades else 0

        # Winning days vs losing days
        winning_days = sum(1 for v in daily_pnl.values() if v > 0)
        losing_days = sum(1 for v in daily_pnl.values() if v < 0)

        return {
            "period": f"{week_start} to {now.date().isoformat()}",
            "total_trades": len(week_trades),
            "total_signals": len(week_signals),
            "total_pnl": round(total_pnl, 2),
            "win_rate": round(win_rate, 4),
            "winning_days": winning_days,
            "losing_days": losing_days,
            "daily_pnl": {k: round(v, 2) for k, v in sorted(daily_pnl.items())},
            "by_strategy": self._group_by_strategy(week_trades),
            "by_symbol": self._group_by_symbol(week_trades),
        }

    async def generate_auto_journal(self, trade_id: str) -> dict[str, Any]:
        """Auto-generate a journal entry for a closed trade."""
        trades = await self.trade_repo.list_all(limit=500, order_by="closed_at", desc=True)
        trade = next((t for t in trades if t.id == trade_id), None)
        if not trade:
            return {"error": "Trade not found"}

        # Find signal chain
        orders = await self.order_repo.list_all(limit=500)
        order = next((o for o in orders if o.id == trade.approved_order_id), None)

        signals = await self.signal_repo.list_all(limit=500)
        signal = next((s for s in signals if order and s.id == order.signal_id), None)

        tags = []
        if signal and signal.confluence_tags:
            try:
                tags = json.loads(signal.confluence_tags)
            except Exception:
                tags = []

        # Build reasoning summary
        outcome = "WIN" if (trade.pnl or 0) > 0 else "LOSS" if (trade.pnl or 0) < 0 else "BREAKEVEN"

        reasoning_parts = []
        if signal:
            reasoning_parts.append(f"Strategy: {signal.strategy_name}")
            reasoning_parts.append(f"Confidence: {signal.confidence:.0%}")
            if tags:
                reasoning_parts.append(f"Confluence: {', '.join(tags)}")
            reasoning_parts.append(f"Expected R:R at entry")

        summary = (
            f"{outcome}: {trade.symbol} {trade.strategy_name or 'unknown'} | "
            f"P&L: ${trade.pnl or 0:.2f} | "
            f"{'  |  '.join(reasoning_parts)}"
        )

        lesson = None
        if (trade.pnl or 0) > 0:
            lesson = f"Setup worked as expected. Confluence tags that confirmed: {', '.join(tags)}."
        elif (trade.pnl or 0) < 0:
            lesson = f"Setup failed. Review: was invalidation respected? Check if {', '.join(tags)} were actually present."

        # Persist journal
        await self.journal_repo.create(
            trade_result_id=trade.id,
            strategy_name=trade.strategy_name,
            symbol=trade.symbol,
            session_name="auto",
            summary=summary,
            lesson=lesson,
            tags=json.dumps(tags + [outcome.lower()]),
            created_by="auto_journal",
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        await self.session.commit()

        return {"success": True, "summary": summary, "lesson": lesson}

    async def _calculate_streak(self, all_trades: list) -> dict[str, Any]:
        """Calculate win/loss streak and consistency."""
        closed = sorted(
            [t for t in all_trades if t.status == "closed" and t.closed_at],
            key=lambda t: t.closed_at,
        )
        if not closed:
            return {"current_streak": 0, "streak_type": "none", "best_win_streak": 0,
                    "worst_loss_streak": 0, "consecutive_profitable_days": 0}

        # Current streak
        current_streak = 0
        streak_type = "none"
        for t in reversed(closed):
            if current_streak == 0:
                streak_type = "win" if (t.pnl or 0) > 0 else "loss"
                current_streak = 1
            elif (streak_type == "win" and (t.pnl or 0) > 0) or \
                 (streak_type == "loss" and (t.pnl or 0) < 0):
                current_streak += 1
            else:
                break

        # Best win streak / worst loss streak
        best_win = 0
        worst_loss = 0
        current_win = 0
        current_loss = 0
        for t in closed:
            if (t.pnl or 0) > 0:
                current_win += 1
                current_loss = 0
            else:
                current_loss += 1
                current_win = 0
            best_win = max(best_win, current_win)
            worst_loss = max(worst_loss, current_loss)

        # Consecutive profitable days
        daily_pnl = defaultdict(float)
        for t in closed:
            day = t.closed_at[:10] if t.closed_at else ""
            daily_pnl[day] += (t.pnl or 0)

        profitable_days = 0
        for day in sorted(daily_pnl.keys(), reverse=True):
            if daily_pnl[day] > 0:
                profitable_days += 1
            else:
                break

        return {
            "current_streak": current_streak,
            "streak_type": streak_type,
            "best_win_streak": best_win,
            "worst_loss_streak": worst_loss,
            "consecutive_profitable_days": profitable_days,
            "total_trading_days": len(daily_pnl),
            "profitable_days": sum(1 for v in daily_pnl.values() if v > 0),
            "losing_days": sum(1 for v in daily_pnl.values() if v < 0),
        }

    def _group_by_strategy(self, trades: list) -> dict:
        grouped = defaultdict(lambda: {"trades": 0, "pnl": 0, "wins": 0})
        for t in trades:
            s = t.strategy_name or "unknown"
            grouped[s]["trades"] += 1
            grouped[s]["pnl"] = round(grouped[s]["pnl"] + (t.pnl or 0), 2)
            if (t.pnl or 0) > 0:
                grouped[s]["wins"] += 1
        return dict(grouped)

    def _group_by_symbol(self, trades: list) -> dict:
        grouped = defaultdict(lambda: {"trades": 0, "pnl": 0})
        for t in trades:
            grouped[t.symbol]["trades"] += 1
            grouped[t.symbol]["pnl"] = round(grouped[t.symbol]["pnl"] + (t.pnl or 0), 2)
        return dict(grouped)
