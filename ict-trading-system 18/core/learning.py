"""Trade Memory & Learning Engine — learns from your $128K in 30 days.

Tracks every entry/exit, calculates what worked, what didn't,
and builds adaptive rules from your actual trading patterns.

Key metrics it learns:
- Win rate by symbol, by hour, by strategy
- Average winner vs average loser size
- Entry timing quality (did you enter at mid-FVG or extremes?)
- Exit quality (did you exit at liquidity targets or panic close?)
- Holding time patterns (what duration maximizes P&L?)
- Mistakes: revenge trades, oversizing, moving stops, FOMO entries
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)


class TradeMemory:
    """Persistent memory of all trades for pattern learning."""

    def __init__(self):
        self._trades: list[dict] = []
        self._rules: list[dict] = []
        self._patterns: dict[str, Any] = {}

    def record_trade(self, trade: dict) -> None:
        """Record a completed trade with full context."""
        trade.setdefault("recorded_at", datetime.now(timezone.utc).isoformat())
        trade.setdefault("lessons", [])
        self._trades.append(trade)
        self._update_patterns()

    def get_all_trades(self) -> list[dict]:
        return self._trades

    def get_trades_by_symbol(self, symbol: str) -> list[dict]:
        return [t for t in self._trades if t.get("symbol", "").upper() == symbol.upper()]

    def _update_patterns(self) -> None:
        """Recompute patterns from all trades."""
        if not self._trades:
            return

        winners = [t for t in self._trades if t.get("pnl", 0) > 0]
        losers = [t for t in self._trades if t.get("pnl", 0) < 0]

        total_pnl = sum(t.get("pnl", 0) for t in self._trades)
        win_rate = len(winners) / len(self._trades) if self._trades else 0
        avg_win = sum(t.get("pnl", 0) for t in winners) / len(winners) if winners else 0
        avg_loss = sum(t.get("pnl", 0) for t in losers) / len(losers) if losers else 0
        profit_factor = abs(avg_win * len(winners)) / abs(avg_loss * len(losers)) if losers and avg_loss != 0 else float('inf')

        # By symbol
        by_symbol = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0})
        for t in self._trades:
            sym = t.get("symbol", "UNKNOWN")
            by_symbol[sym]["trades"] += 1
            by_symbol[sym]["pnl"] += t.get("pnl", 0)
            if t.get("pnl", 0) > 0:
                by_symbol[sym]["wins"] += 1

        # By hour of entry
        by_hour = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0})
        for t in self._trades:
            try:
                entry_time = t.get("entry_time", "")
                if entry_time:
                    dt = datetime.fromisoformat(entry_time.replace("Z", "+00:00"))
                    hour = dt.hour
                    by_hour[hour]["trades"] += 1
                    by_hour[hour]["pnl"] += t.get("pnl", 0)
                    if t.get("pnl", 0) > 0:
                        by_hour[hour]["wins"] += 1
            except Exception:
                pass

        # Holding time analysis
        hold_times = []
        for t in self._trades:
            entry = t.get("entry_time")
            exit_ = t.get("exit_time")
            if entry and exit_:
                try:
                    dt_entry = datetime.fromisoformat(entry.replace("Z", "+00:00"))
                    dt_exit = datetime.fromisoformat(exit_.replace("Z", "+00:00"))
                    hold_minutes = (dt_exit - dt_entry).total_seconds() / 60
                    hold_times.append({
                        "minutes": hold_minutes,
                        "pnl": t.get("pnl", 0),
                        "symbol": t.get("symbol"),
                    })
                except Exception:
                    pass

        # Optimal hold time
        winning_holds = [h["minutes"] for h in hold_times if h["pnl"] > 0]
        losing_holds = [h["minutes"] for h in hold_times if h["pnl"] < 0]
        avg_winning_hold = sum(winning_holds) / len(winning_holds) if winning_holds else 0
        avg_losing_hold = sum(losing_holds) / len(losing_holds) if losing_holds else 0

        self._patterns = {
            "total_trades": len(self._trades),
            "total_pnl": round(total_pnl, 2),
            "win_rate": round(win_rate, 4),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "profit_factor": round(profit_factor, 2) if profit_factor != float('inf') else "∞",
            "expectancy": round(win_rate * avg_win + (1 - win_rate) * avg_loss, 2),
            "by_symbol": {k: {**v, "win_rate": round(v["wins"] / v["trades"], 2) if v["trades"] > 0 else 0, "pnl": round(v["pnl"], 2)} for k, v in by_symbol.items()},
            "by_hour": {str(k): {**v, "win_rate": round(v["wins"] / v["trades"], 2) if v["trades"] > 0 else 0} for k, v in sorted(by_hour.items())},
            "hold_time": {
                "avg_winning_hold_minutes": round(avg_winning_hold, 1),
                "avg_losing_hold_minutes": round(avg_losing_hold, 1),
                "insight": "Cut losers faster" if avg_losing_hold > avg_winning_hold * 1.5 else "Good discipline",
            },
            "best_symbol": max(by_symbol.items(), key=lambda x: x[1]["pnl"])[0] if by_symbol else None,
            "worst_symbol": min(by_symbol.items(), key=lambda x: x[1]["pnl"])[0] if by_symbol else None,
        }

    def get_patterns(self) -> dict:
        return self._patterns

    def detect_mistakes(self) -> list[dict]:
        """Analyze trades for common mistakes."""
        mistakes = []

        # Check for revenge trades (loss followed by immediate entry on same symbol)
        for i in range(1, len(self._trades)):
            prev = self._trades[i - 1]
            curr = self._trades[i]
            if (prev.get("pnl", 0) < 0 and
                curr.get("symbol") == prev.get("symbol") and
                prev.get("exit_time") and curr.get("entry_time")):
                try:
                    dt_exit = datetime.fromisoformat(prev["exit_time"].replace("Z", "+00:00"))
                    dt_entry = datetime.fromisoformat(curr["entry_time"].replace("Z", "+00:00"))
                    gap_minutes = (dt_entry - dt_exit).total_seconds() / 60
                    if gap_minutes < 30:
                        mistakes.append({
                            "type": "revenge_trade",
                            "severity": "high",
                            "trade_index": i,
                            "symbol": curr.get("symbol"),
                            "gap_minutes": round(gap_minutes, 1),
                            "message": f"Possible revenge trade on {curr['symbol']} — entered {int(gap_minutes)}min after a loss",
                            "rule": "Wait minimum 30 minutes after a loss before re-entering same symbol",
                        })
                except Exception:
                    pass

        # Check for oversizing
        for i, t in enumerate(self._trades):
            risk_pct = t.get("risk_pct", 0)
            if risk_pct > 5:
                mistakes.append({
                    "type": "oversize",
                    "severity": "high",
                    "trade_index": i,
                    "symbol": t.get("symbol"),
                    "risk_pct": risk_pct,
                    "message": f"Position risk {risk_pct}% exceeds 5% threshold on {t.get('symbol')}",
                    "rule": "Max 2% risk per trade, 5% absolute maximum",
                })

        # Check for consecutive losses (tilt indicator)
        consec_losses = 0
        max_consec = 0
        for t in self._trades:
            if t.get("pnl", 0) < 0:
                consec_losses += 1
                max_consec = max(max_consec, consec_losses)
            else:
                consec_losses = 0

        if max_consec >= 3:
            mistakes.append({
                "type": "consecutive_losses",
                "severity": "medium",
                "count": max_consec,
                "message": f"Had {max_consec} consecutive losses — possible tilt or strategy misalignment",
                "rule": "Stop trading after 3 consecutive losses. Review and reset.",
            })

        return mistakes

    def generate_rules(self) -> list[dict]:
        """Generate adaptive trading rules from patterns."""
        rules = []
        patterns = self._patterns

        if not patterns or patterns.get("total_trades", 0) < 5:
            return [{"rule": "Need at least 5 trades to generate rules", "type": "info"}]

        # Best time to trade
        by_hour = patterns.get("by_hour", {})
        if by_hour:
            best_hour = max(by_hour.items(), key=lambda x: x[1].get("pnl", 0))
            worst_hour = min(by_hour.items(), key=lambda x: x[1].get("pnl", 0))
            if best_hour[1]["pnl"] > 0:
                rules.append({
                    "type": "timing",
                    "rule": f"Best trading hour: {best_hour[0]}:00 UTC (P&L: ${best_hour[1]['pnl']:.0f})",
                    "action": f"Prioritize entries around {best_hour[0]}:00 UTC",
                })
            if worst_hour[1]["pnl"] < 0:
                rules.append({
                    "type": "timing",
                    "rule": f"Worst trading hour: {worst_hour[0]}:00 UTC (P&L: ${worst_hour[1]['pnl']:.0f})",
                    "action": f"Avoid entries at {worst_hour[0]}:00 UTC or reduce size",
                })

        # Best and worst symbols
        by_symbol = patterns.get("by_symbol", {})
        for sym, data in by_symbol.items():
            if data["trades"] >= 3:
                if data["win_rate"] >= 0.7:
                    rules.append({
                        "type": "symbol_strength",
                        "rule": f"{sym}: {data['win_rate']:.0%} win rate over {data['trades']} trades",
                        "action": f"Increase conviction on {sym} setups",
                    })
                elif data["win_rate"] <= 0.3:
                    rules.append({
                        "type": "symbol_weakness",
                        "rule": f"{sym}: only {data['win_rate']:.0%} win rate over {data['trades']} trades",
                        "action": f"Reduce size or skip {sym} until edge is clearer",
                    })

        # Hold time rule
        hold = patterns.get("hold_time", {})
        if hold.get("avg_winning_hold_minutes", 0) > 0:
            rules.append({
                "type": "hold_time",
                "rule": f"Avg winning hold: {hold['avg_winning_hold_minutes']:.0f}min, Avg losing hold: {hold['avg_losing_hold_minutes']:.0f}min",
                "action": hold.get("insight", ""),
            })

        # Win rate rule
        wr = patterns.get("win_rate", 0)
        if wr < 0.5:
            rules.append({
                "type": "accuracy",
                "rule": f"Win rate is {wr:.0%} — below 50%",
                "action": "Focus on higher confidence setups only (DRM score 5+ out of 7)",
            })

        # Expectancy check
        exp = patterns.get("expectancy", 0)
        if exp > 0:
            rules.append({
                "type": "expectancy",
                "rule": f"Positive expectancy: ${exp:.2f} per trade",
                "action": "Edge is real — keep trading the system",
            })
        elif exp < 0:
            rules.append({
                "type": "expectancy",
                "rule": f"Negative expectancy: ${exp:.2f} per trade",
                "action": "STOP — review strategy before taking more trades",
            })

        self._rules = rules
        return rules


class PairsAnalyzer:
    """Pairs trading analysis — cointegration testing from the notebook.

    Adapted from KidQuant/Pairs-Trading-With-Python to work with
    our 6 symbols: BTCUSD, NAS100, US30, EURUSD, XAUUSD, USOIL.

    Tests for cointegrated pairs, calculates spread z-scores,
    and generates mean-reversion trading signals.
    """

    def __init__(self):
        self._pairs_cache: dict[str, Any] = {}

    def find_cointegrated_pairs(self, price_data: dict[str, list[float]], cutoff: float = 0.05) -> dict:
        """Test all symbol pairs for cointegration.

        Args:
            price_data: {symbol: [price1, price2, ...]} — daily closing prices
            cutoff: p-value threshold (0.05 = 95% confidence)

        Returns: {pairs: [{sym1, sym2, pvalue, cointegrated}], matrix: {...}}
        """
        import numpy as np
        from statsmodels.tsa.stattools import coint

        symbols = list(price_data.keys())
        n = len(symbols)
        pvalue_matrix = {}
        pairs = []

        for i in range(n):
            for j in range(i + 1, n):
                s1_name, s2_name = symbols[i], symbols[j]
                s1 = np.array(price_data[s1_name], dtype=float)
                s2 = np.array(price_data[s2_name], dtype=float)

                # Need same length
                min_len = min(len(s1), len(s2))
                if min_len < 30:
                    continue
                s1, s2 = s1[:min_len], s2[:min_len]

                # Remove any NaN/inf
                mask = np.isfinite(s1) & np.isfinite(s2)
                s1, s2 = s1[mask], s2[mask]

                if len(s1) < 30:
                    continue

                try:
                    score, pvalue, _ = coint(s1, s2)
                    is_coint = pvalue < cutoff
                    pair_key = f"{s1_name}/{s2_name}"
                    pvalue_matrix[pair_key] = round(pvalue, 6)

                    pairs.append({
                        "sym1": s1_name,
                        "sym2": s2_name,
                        "pvalue": round(pvalue, 6),
                        "score": round(float(score), 4),
                        "cointegrated": is_coint,
                        "data_points": len(s1),
                    })
                except Exception as e:
                    pairs.append({
                        "sym1": s1_name, "sym2": s2_name,
                        "error": str(e)[:100],
                    })

        # Sort by p-value (lowest = most cointegrated)
        pairs.sort(key=lambda x: x.get("pvalue", 1))

        return {
            "pairs": pairs,
            "pvalue_matrix": pvalue_matrix,
            "cointegrated_pairs": [p for p in pairs if p.get("cointegrated")],
            "total_tested": len(pairs),
            "cutoff": cutoff,
        }

    def calculate_spread_zscore(
        self, prices1: list[float], prices2: list[float],
        window_long: int = 60, window_short: int = 5,
    ) -> dict:
        """Calculate the spread z-score between two price series.

        Uses the rolling ratio approach from the notebook:
        ratio = S1 / S2
        z-score = (MA_short(ratio) - MA_long(ratio)) / STD_long(ratio)

        Buy when z < -1 (ratio compressed = S1 cheap relative to S2)
        Sell when z > +1 (ratio expanded = S1 expensive relative to S2)
        """
        import numpy as np
        import pandas as pd

        s1 = pd.Series(prices1, dtype=float)
        s2 = pd.Series(prices2, dtype=float)

        ratio = s1 / s2
        ratio = ratio.dropna()

        if len(ratio) < window_long + 10:
            return {"error": f"Need {window_long + 10}+ data points, got {len(ratio)}"}

        ma_short = ratio.rolling(window=window_short).mean()
        ma_long = ratio.rolling(window=window_long).mean()
        std_long = ratio.rolling(window=window_long).std()

        zscore = (ma_short - ma_long) / std_long
        zscore = zscore.dropna()

        if len(zscore) == 0:
            return {"error": "insufficient data for z-score calculation"}

        current_z = float(zscore.iloc[-1])
        current_ratio = float(ratio.iloc[-1])

        # Signal
        if current_z < -1.0:
            signal = "buy_ratio"
            signal_text = "BUY ratio (S1 cheap relative to S2)"
            strength = min(abs(current_z) / 2.0, 1.0)
        elif current_z > 1.0:
            signal = "sell_ratio"
            signal_text = "SELL ratio (S1 expensive relative to S2)"
            strength = min(abs(current_z) / 2.0, 1.0)
        else:
            signal = "neutral"
            signal_text = "No signal — within normal range"
            strength = 0

        return {
            "current_zscore": round(current_z, 4),
            "current_ratio": round(current_ratio, 6),
            "mean_ratio": round(float(ratio.mean()), 6),
            "std_ratio": round(float(ratio.std()), 6),
            "signal": signal,
            "signal_text": signal_text,
            "strength": round(strength, 2),
            "window_long": window_long,
            "window_short": window_short,
            "zscore_history": [round(float(z), 4) for z in zscore.tail(50).tolist()],
        }

    def stationarity_test(self, prices: list[float], cutoff: float = 0.05) -> dict:
        """Augmented Dickey-Fuller test for stationarity."""
        import numpy as np
        from statsmodels.tsa.stattools import adfuller

        series = np.array(prices, dtype=float)
        series = series[np.isfinite(series)]

        if len(series) < 20:
            return {"error": "need 20+ data points"}

        try:
            result = adfuller(series)
            pvalue = result[1]
            return {
                "stationary": pvalue < cutoff,
                "pvalue": round(pvalue, 6),
                "test_statistic": round(result[0], 4),
                "critical_values": {k: round(v, 4) for k, v in result[4].items()},
                "interpretation": "Stationary (mean-reverting)" if pvalue < cutoff else "Non-stationary (trending)",
            }
        except Exception as e:
            return {"error": str(e)[:200]}


# Singletons
_trade_memory = TradeMemory()
_pairs_analyzer = PairsAnalyzer()


def get_trade_memory() -> TradeMemory:
    return _trade_memory

def get_pairs_analyzer() -> PairsAnalyzer:
    return _pairs_analyzer
