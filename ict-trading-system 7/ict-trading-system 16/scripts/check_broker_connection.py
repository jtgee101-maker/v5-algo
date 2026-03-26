"""Check broker connection — verify auth, account, instruments.

Run this before anything else to ensure TradeLocker credentials work.

Usage:
  python scripts/check_broker_connection.py
"""

import asyncio
import os
import sys

from core.execution.client import TradeLockerClient


async def check() -> bool:
    print("=" * 60)
    print("ICT Trading System — Broker Connection Check")
    print("=" * 60)

    # Check env vars
    required_env = [
        "TRADELOCKER_EMAIL",
        "TRADELOCKER_PASSWORD",
        "TRADELOCKER_SERVER",
        "TRADELOCKER_ACCOUNT_ID",
    ]
    missing = [v for v in required_env if not os.environ.get(v)]
    if missing:
        print(f"\nMissing environment variables: {missing}")
        print("Set them before running:")
        for v in missing:
            print(f"  export {v}='...'")
        return False

    client = TradeLockerClient()

    try:
        print("\n[1/4] Connecting and authenticating...")
        await client.connect()
        print("  OK: Authenticated successfully")

        print("\n[2/4] Fetching account state...")
        state = await client.get_account_state()
        equity = state.get("equity", "unknown")
        balance = state.get("balance", "unknown")
        print(f"  OK: Equity={equity}, Balance={balance}")

        print("\n[3/4] Fetching instruments...")
        instruments = await client.get_instruments()
        print(f"  OK: {len(instruments)} instruments available")
        for inst in instruments[:5]:
            print(f"      {inst.get('name', '?')} (ID: {inst.get('tradableInstrumentId', '?')})")
        if len(instruments) > 5:
            print(f"      ... and {len(instruments) - 5} more")

        print("\n[4/4] Testing dry-run order...")
        if instruments:
            first = instruments[0]
            result = await client.place_order(
                instrument_id=first.get("tradableInstrumentId", 0),
                side="buy",
                quantity=0.01,
                dry_run=True,
            )
            print(f"  OK: Dry-run order validated: {result}")

        await client.disconnect()

        print("\n" + "=" * 60)
        print("ALL CHECKS PASSED — broker connection is working.")
        return True

    except Exception as e:
        print(f"\n  FAILED: {e}")
        try:
            await client.disconnect()
        except Exception:
            pass
        return False


def main() -> None:
    success = asyncio.run(check())
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
