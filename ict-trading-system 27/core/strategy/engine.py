"""Strategy Decision Engine — evaluates all active strategies against market state.

This is Engine B. It takes a MarketState and produces TradeSignal objects
from whichever strategies detect valid setups.
"""

from __future__ import annotations

from typing import Optional

import structlog
import yaml

from core.models import MarketState, TradeSignal
from core.strategy.ny_sweep_reversal import NYSweepReversalStrategy
from core.strategy.ny_continuation import NYContinuationStrategy
from core.strategy.psych_level_rejection import PsychLevelStrategy

logger = structlog.get_logger(__name__)


class StrategyEngine:
    """Runs all active strategies against a MarketState."""

    def __init__(self, config_path: str = "config/strategy.yaml"):
        with open(config_path) as f:
            cfg = yaml.safe_load(f)

        self.max_trades_per_strategy = cfg["global"]["max_trades_per_strategy_per_day"]
        self.strategies_cfg = cfg["strategies"]

        # Initialize active strategies
        self.strategies: list = []
        self._trade_counts: dict[str, int] = {}

        if self.strategies_cfg.get("ny_sweep_reversal", {}).get("status") == "active":
            self.strategies.append(NYSweepReversalStrategy(config_path))

        if self.strategies_cfg.get("ny_continuation", {}).get("status") == "active":
            self.strategies.append(NYContinuationStrategy(config_path))

        if self.strategies_cfg.get("psych_level_model", {}).get("status") == "active":
            self.strategies.append(PsychLevelStrategy(config_path))

        logger.info("strategy_engine.initialized", active_count=len(self.strategies))

    def evaluate(self, state: MarketState) -> list[TradeSignal]:
        """Run all active strategies and collect signals."""
        signals: list[TradeSignal] = []

        for strategy in self.strategies:
            strat_id = strategy.strategy_id

            # Check per-strategy daily trade limit
            count = self._trade_counts.get(strat_id, 0)
            if count >= self.max_trades_per_strategy:
                logger.debug(
                    "strategy_engine.daily_limit",
                    strategy=strat_id,
                    count=count,
                )
                continue

            try:
                signal = strategy.evaluate(state)
                if signal is not None:
                    signals.append(signal)
                    logger.info(
                        "strategy_engine.signal_generated",
                        strategy=strat_id,
                        symbol=state.symbol,
                        direction=signal.direction,
                        confidence=signal.confidence,
                    )
            except Exception as e:
                logger.error(
                    "strategy_engine.evaluate_error",
                    strategy=strat_id,
                    symbol=state.symbol,
                    error=str(e),
                )

        return signals

    def record_trade(self, strategy_id: str) -> None:
        """Increment daily trade counter for a strategy."""
        self._trade_counts[strategy_id] = self._trade_counts.get(strategy_id, 0) + 1

    def reset_daily_counts(self) -> None:
        """Reset trade counters at start of new trading day."""
        self._trade_counts.clear()

    @property
    def active_strategy_ids(self) -> list[str]:
        return [s.strategy_id for s in self.strategies]
