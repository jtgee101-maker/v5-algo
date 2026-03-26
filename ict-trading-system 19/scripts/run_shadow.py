"""Run the trading pipeline in shadow mode.

Shadow mode:
- Connects to broker
- Fetches real market data
- Generates market structure labels
- Produces trade signals
- Runs risk gate
- Logs everything
- Places NO orders

Usage:
  python scripts/run_shadow.py
"""

import asyncio
import structlog

from core.pipeline import TradingPipeline


def main() -> None:
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),  # Human-readable for dev
        ],
    )

    print("=" * 60)
    print("ICT Trading System — SHADOW MODE")
    print("=" * 60)
    print("No orders will be placed.")
    print("Signals and decisions will be logged to data/signals/")
    print("Press Ctrl+C to stop.")
    print("=" * 60)

    pipeline = TradingPipeline(mode="shadow")
    asyncio.run(pipeline.start())


if __name__ == "__main__":
    main()
