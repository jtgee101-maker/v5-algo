"""Broker discovery — finds working TradeLocker API endpoints.

Run: python scripts/discover_broker.py

Outputs a JSON config of working endpoints that run_scan uses.
Saves to data/broker_endpoints.json for the scanner to read.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def discover():
    from core.execution.client import TradeLockerClient

    print("=" * 60)
    print("TradeLocker API Endpoint Discovery")
    print("=" * 60)

    # Connect
    client = TradeLockerClient()
    await client.connect()
    print("✅ Auth successful")
    print(f"   Base URL: {client.base_url}")

    # Get all instruments
    instruments = await client.get_instruments()
    print(f"✅ Found {len(instruments)} instruments")

    # Find our target symbols and close matches
    targets = ["BTCUSD", "NAS100", "US30", "EURUSD"]
    found_instruments = {}

    for name in targets:
        inst = next((i for i in instruments if i.get("name") == name), None)
        if inst:
            found_instruments[name] = inst
            print(f"   ✅ {name}: tradableInstrumentId={inst.get('tradableInstrumentId')}")
        else:
            # Try partial/fuzzy match
            matches = [
                i for i in instruments
                if name.lower().replace("usd", "") in i.get("name", "").lower()
                or name.lower() in i.get("name", "").lower()
            ]
            if matches:
                best = matches[0]
                found_instruments[name] = best
                print(f"   ⚠️  {name}: not exact. Using '{best.get('name')}' (id={best.get('tradableInstrumentId')})")
                print(f"       Other matches: {[m.get('name') for m in matches[:5]]}")
            else:
                print(f"   ❌ {name}: NOT FOUND in broker instruments")

    # Test candle URL patterns
    acc_id = os.environ.get("TRADELOCKER_ACCOUNT_ID", "1967672")
    acc_num = os.environ.get("TRADELOCKER_ACC_NUM", "3")

    # Pick any found instrument for testing
    test_inst = None
    test_symbol = None
    for sym in targets:
        if sym in found_instruments:
            test_inst = found_instruments[sym]
            test_symbol = sym
            break

    if not test_inst:
        print("❌ No instruments found to test candle URLs")
        await client.disconnect()
        return

    inst_id = test_inst.get("tradableInstrumentId")
    print(f"\n🔍 Testing candle URL patterns with {test_symbol} (id={inst_id}):")

    patterns = [
        ("/trade/accounts/{acc_num}/instruments/{inst_id}/candles", {"acc_num": acc_num, "inst_id": inst_id}),
        ("/trade/accounts/{acc_id}/instruments/{inst_id}/candles", {"acc_id": acc_id, "inst_id": inst_id}),
        ("/trade/instruments/{inst_id}/candles", {"inst_id": inst_id}),
        ("/trade/history/{inst_id}/candles", {"inst_id": inst_id}),
        ("/trade/accounts/{acc_num}/history/{inst_id}/candles", {"acc_num": acc_num, "inst_id": inst_id}),
        ("/history/candles/{inst_id}", {"inst_id": inst_id}),
        ("/accounts/{acc_num}/instruments/{inst_id}/candles", {"acc_num": acc_num, "inst_id": inst_id}),
        ("/instruments/{inst_id}/candles", {"inst_id": inst_id}),
    ]

    # Also try different resolution params
    param_variations = [
        {"resolution": "5", "count": "10"},
        {"resolution": "300", "count": "10"},  # 5min in seconds
        {"resolution": "5m", "count": "10"},
        {"resolution": "5", "size": "10"},
        {"resolution": "5", "limit": "10"},
        {"bars": "10", "resolution": "5"},
    ]

    working_url = None
    working_params = None

    for pattern_template, pattern_vars in patterns:
        url = pattern_template.format(**pattern_vars)
        for params in param_variations:
            try:
                resp = await client._client.get(
                    url, headers=client._auth_headers(), params=params,
                )
                status = resp.status_code

                if status in (200, 201):
                    body = resp.text[:300]
                    # Check if response actually has candle data
                    try:
                        data = resp.json()
                        has_data = bool(data.get("d") or data.get("candles") or data.get("data") or (isinstance(data, list) and len(data) > 0))
                    except Exception:
                        has_data = False

                    if has_data:
                        print(f"   ✅ {status} {url} params={params}")
                        print(f"      Response keys: {list(data.keys()) if isinstance(data, dict) else 'list'}")
                        print(f"      Preview: {body[:150]}")
                        if not working_url:
                            working_url = pattern_template
                            working_params = params
                    else:
                        print(f"   ⚠️  {status} {url} params={params} — response but no candle data")
                        print(f"      Preview: {body[:100]}")
                elif status == 404:
                    pass  # Skip 404s silently
                else:
                    print(f"   ❌ {status} {url} params={params}")
                    print(f"      Body: {resp.text[:100]}")
            except Exception as e:
                print(f"   💥 {url} params={params}: {str(e)[:80]}")

    # Also try the REST endpoint documentation pattern
    print("\n🔍 Testing additional patterns:")
    extra_urls = [
        f"/trade/accounts/{acc_num}/historicalCandles/{inst_id}",
        f"/trade/accounts/{acc_num}/candles",
        f"/trade/candles",
        f"/api/trade/accounts/{acc_num}/instruments/{inst_id}/candles",
    ]
    for url in extra_urls:
        for params in param_variations[:2]:
            try:
                resp = await client._client.get(
                    url, headers=client._auth_headers(), params=params,
                )
                if resp.status_code in (200, 201):
                    print(f"   ✅ {resp.status_code} {url}")
                    print(f"      Preview: {resp.text[:150]}")
                    if not working_url:
                        working_url = url
                        working_params = params
                elif resp.status_code != 404:
                    print(f"   ❌ {resp.status_code} {url}: {resp.text[:80]}")
            except Exception:
                pass

    await client.disconnect()

    # Save results
    result = {
        "discovered_at": __import__("datetime").datetime.now().isoformat(),
        "base_url": os.environ.get("TRADELOCKER_BASE_URL", "https://demo.tradelocker.com/backend-api"),
        "acc_id": acc_id,
        "acc_num": acc_num,
        "instruments": {
            sym: {"name": inst.get("name"), "id": inst.get("tradableInstrumentId")}
            for sym, inst in found_instruments.items()
        },
        "working_candle_url": working_url,
        "working_candle_params": working_params,
    }

    # Save to data/
    output_path = Path("data/broker_endpoints.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2))

    print(f"\n{'=' * 60}")
    if working_url:
        print(f"✅ WORKING CANDLE URL: {working_url}")
        print(f"   Params: {working_params}")
    else:
        print("❌ NO WORKING CANDLE URL FOUND")
        print("   Check TradeLocker API docs or contact GatesFX support")
    print(f"Results saved to: {output_path}")
    print(f"{'=' * 60}")

    return result


if __name__ == "__main__":
    asyncio.run(discover())
