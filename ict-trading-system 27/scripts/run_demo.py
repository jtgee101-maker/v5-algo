"""Run the trading pipeline in demo mode.

Demo mode:
- Connects to TradeLocker demo account
- Generates real signals
- Runs risk gate
- Places DRY-RUN orders (validated but not sent to broker)
- Logs everything

This is Phase 4+. Only run after shadow mode has produced clean logs.

Usage:
  python scripts/run_demo.py
"""

import asyncio
import sys

import structlog

from core.pipeline import TradingPipeline


def check_gate() -> bool:
    """Verify that shadow mode prerequisites are met."""
    from pathlib import Path
    signals_dir = Path("data/signals")

    if not signals_dir.exists():
        print("GATE FAILED: No data/signals/ directory. Run shadow mode first.")
        return False

    signal_files = list(signals_dir.glob("signal_*.json"))
    if len(signal_files) < 10:
        print(f"GATE FAILED: Only {len(signal_files)} signals logged. Need at least 10 from shadow mode.")
        return False

    print(f"Gate check passed: {len(signal_files)} signals from shadow mode.")
    return True


def main() -> None:
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
    )

    print("=" * 60)
    print("ICT Trading System — DEMO MODE")
    print("=" * 60)

    if not check_gate():
        print("\nRun shadow mode first: python scripts/run_shadow.py")
        sys.exit(1)

    print("Orders will be VALIDATED but sent as DRY-RUN (not executed).")
    print("Press Ctrl+C to stop.")
    print("=" * 60)

    pipeline = TradingPipeline(mode="demo")
    asyncio.run(pipeline.start())


if __name__ == "__main__":
    main()
