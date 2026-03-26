"""Metrics service — computes performance analytics from persisted trade data.

Provides: win rate, profit factor, expectancy, avg win/loss, drawdown,
rejection rate, expiration rate, per-strategy and per-session attribution.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from typing import Any, Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import TradeResultRecord, TradeSignalRecord
from backend.db.repositories.base import GenericRepository

logger = structlog.get_logger(__name__)


class MetricsService:
    """Computes trading performance metrics from the database."""

    def __init__(self, session: AsyncSession):
        self.trade_repo = GenericRepository(session, TradeResultRecord)
        self.signal_repo = GenericRepository(session, TradeSignalRecord)

    async def overview(self) -> dict[str, Any]:
        """System-wide performance overview."""
        trades = await self.trade_repo.list_all(limit=1000, order_by="closed_at", desc=True)
        signals = await self.signal_repo.list_all(limit=1000, order_by="timestamp", desc=True)

        closed = [t for t in trades if t.status == "closed"]
        open_trades = [t for t in trades if t.status == "open"]
        winners = [t for t in closed if (t.pnl or 0) > 0]
        losers = [t for t in closed if (t.pnl or 0) < 0]
        breakeven = [t for t in closed if (t.pnl or 0) == 0]

        total_pnl = sum(t.pnl or 0 for t in closed)
        gross_profit = sum(t.pnl or 0 for t in winners)
        gross_loss = abs(sum(t.pnl or 0 for t in losers))
        avg_win = (gross_profit / len(winners)) if winners else 0
        avg_loss = (gross_loss / len(losers)) if losers else 0
        win_rate = len(winners) / len(closed) if closed else 0
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf") if gross_profit > 0 else 0
        expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss) if closed else 0

        # Max drawdown from trade sequence
        max_dd = self._calculate_max_drawdown(closed)

        # Signal metrics
        status_counts = Counter(s.status for s in signals)
        total_signals = len(signals)
        rejection_rate = status_counts.get("rejected", 0) / total_signals if total_signals else 0
        expiration_rate = status_counts.get("expired", 0) / total_signals if total_signals else 0
        approval_rate = (status_counts.get("approved", 0) + status_counts.get("executed", 0)) / total_signals if total_signals else 0

        return {
            "total_trades": len(closed),
            "open_trades": len(open_trades),
            "winners": len(winners),
            "losers": len(losers),
            "breakeven": len(breakeven),
            "win_rate": round(win_rate, 4),
            "total_pnl": round(total_pnl, 2),
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "profit_factor": round(profit_factor, 4) if profit_factor != float("inf") else 999.0,
            "expectancy": round(expectancy, 4),
            "max_drawdown": round(max_dd, 4),
            "total_signals": total_signals,
            "signal_status": dict(status_counts),
            "rejection_rate": round(rejection_rate, 4),
            "expiration_rate": round(expiration_rate, 4),
            "approval_rate": round(approval_rate, 4),
        }

    async def by_strategy(self) -> list[dict[str, Any]]:
        """Per-strategy performance breakdown."""
        trades = await self.trade_repo.list_all(limit=1000, order_by="closed_at", desc=True)
        signals = await self.signal_repo.list_all(limit=1000, order_by="timestamp", desc=True)

        closed = [t for t in trades if t.status == "closed"]

        # Group trades by strategy
        by_strat: dict[str, list] = defaultdict(list)
        for t in closed:
            by_strat[t.strategy_name or "unknown"].append(t)

        # Group signals by strategy
        sig_by_strat: dict[str, list] = defaultdict(list)
        for s in signals:
            sig_by_strat[s.strategy_name or "unknown"].append(s)

        results = []
        for strat_name, strat_trades in by_strat.items():
            winners = [t for t in strat_trades if (t.pnl or 0) > 0]
            losers = [t for t in strat_trades if (t.pnl or 0) < 0]
            total_pnl = sum(t.pnl or 0 for t in strat_trades)
            gross_profit = sum(t.pnl or 0 for t in winners)
            gross_loss = abs(sum(t.pnl or 0 for t in losers))
            win_rate = len(winners) / len(strat_trades) if strat_trades else 0
            avg_win = gross_profit / len(winners) if winners else 0
            avg_loss = gross_loss / len(losers) if losers else 0
            pf = gross_profit / gross_loss if gross_loss > 0 else 999.0
            exp = (win_rate * avg_win) - ((1 - win_rate) * avg_loss) if strat_trades else 0
            max_dd = self._calculate_max_drawdown(strat_trades)

            strat_sigs = sig_by_strat.get(strat_name, [])
            sig_statuses = Counter(s.status for s in strat_sigs)

            # Confluence tag analysis
            tag_wins: dict[str, int] = defaultdict(int)
            tag_total: dict[str, int] = defaultdict(int)
            for s in strat_sigs:
                tags = self._parse_tags(s.confluence_tags)
                for tag in tags:
                    tag_total[tag] += 1
            for t in winners:
                # Match winner back to signal tags (approximate)
                matching_sigs = [s for s in strat_sigs if s.symbol == t.symbol]
                for ms in matching_sigs[-1:]:
                    for tag in self._parse_tags(ms.confluence_tags):
                        tag_wins[tag] += 1

            tag_analysis = {
                tag: {"total": tag_total[tag], "wins": tag_wins.get(tag, 0),
                      "win_rate": round(tag_wins.get(tag, 0) / tag_total[tag], 3) if tag_total[tag] > 0 else 0}
                for tag in tag_total
            }

            results.append({
                "strategy": strat_name,
                "trades": len(strat_trades),
                "winners": len(winners),
                "losers": len(losers),
                "win_rate": round(win_rate, 4),
                "total_pnl": round(total_pnl, 2),
                "avg_win": round(avg_win, 2),
                "avg_loss": round(avg_loss, 2),
                "profit_factor": round(pf, 4),
                "expectancy": round(exp, 4),
                "max_drawdown": round(max_dd, 4),
                "signals": len(strat_sigs),
                "signal_status": dict(sig_statuses),
                "confluence_tags": tag_analysis,
            })

        return sorted(results, key=lambda r: r["total_pnl"], reverse=True)

    async def by_session(self) -> list[dict[str, Any]]:
        """Performance broken down by session (from signal data)."""
        signals = await self.signal_repo.list_all(limit=1000, order_by="timestamp", desc=True)
        trades = await self.trade_repo.list_all(limit=1000, order_by="closed_at", desc=True)

        # Group signals by hour bucket (proxy for session)
        by_hour: dict[str, list] = defaultdict(list)
        for s in signals:
            try:
                hour = s.timestamp.split("T")[1][:2] if "T" in s.timestamp else "00"
            except (IndexError, AttributeError):
                hour = "00"
            by_hour[f"hour_{hour}"].append(s)

        # For trades, use opened_at
        trade_by_hour: dict[str, list] = defaultdict(list)
        for t in trades:
            if t.opened_at and "T" in t.opened_at:
                hour = t.opened_at.split("T")[1][:2]
                trade_by_hour[f"hour_{hour}"].append(t)

        results = []
        for session_key, session_trades in trade_by_hour.items():
            closed = [t for t in session_trades if t.status == "closed"]
            if not closed:
                continue
            winners = [t for t in closed if (t.pnl or 0) > 0]
            total_pnl = sum(t.pnl or 0 for t in closed)
            win_rate = len(winners) / len(closed) if closed else 0

            session_sigs = by_hour.get(session_key, [])

            results.append({
                "session": session_key,
                "trades": len(closed),
                "win_rate": round(win_rate, 4),
                "total_pnl": round(total_pnl, 2),
                "signals": len(session_sigs),
            })

        return sorted(results, key=lambda r: r["total_pnl"], reverse=True)

    def _calculate_max_drawdown(self, trades: list) -> float:
        """Calculate max drawdown from a sequence of trade P&Ls."""
        if not trades:
            return 0.0
        equity_curve = 0.0
        peak = 0.0
        max_dd = 0.0
        for t in trades:
            equity_curve += (t.pnl or 0)
            if equity_curve > peak:
                peak = equity_curve
            dd = (peak - equity_curve) / peak if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
        return max_dd

    def _parse_tags(self, tags_str: Optional[str]) -> list[str]:
        if not tags_str:
            return []
        try:
            return json.loads(tags_str)
        except (json.JSONDecodeError, TypeError):
            return tags_str.split(",") if tags_str else []
