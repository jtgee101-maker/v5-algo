"""FastAPI application — ICT Trade Mission Control API."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routers import (
    account_router,
    agents_router,
    config_router,
    control_router,
    health_router,
    incidents_router,
    journals_router,
    market_router,
    metrics_router,
    reconciliation_router,
    risk_router,
    signals_router,
    trades_router,
)
from backend.db.session import create_tables, AsyncSessionLocal
from backend.settings import VERSION


async def _auto_seed_account():
    try:
        from backend.db.models import Account
        from backend.db.repositories.base import GenericRepository
        async with AsyncSessionLocal() as session:
            repo = GenericRepository(session, Account)
            existing = await repo.list_all(limit=1)
            if not existing:
                await repo.create(
                    id="acct_demo_1", broker_name="gatesfx",
                    account_name="GatesFX Demo", account_type="demo",
                    mode="shadow", balance=0, equity=0, margin_used=0,
                    free_margin=0, drawdown_pct=0, status="disconnected",
                    currency="USD", updated_at=datetime.now(timezone.utc).isoformat(),
                )
                await session.commit()
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    from backend.settings import DATA_DIR
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    await create_tables()
    await _auto_seed_account()
    yield


app = FastAPI(
    title="ICT Trade Mission Control",
    description="Self-healing agent-assisted CFD trading system API",
    version=VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, prefix="/api")
app.include_router(account_router, prefix="/api")
app.include_router(market_router, prefix="/api")
app.include_router(signals_router, prefix="/api")
app.include_router(trades_router, prefix="/api")
app.include_router(risk_router, prefix="/api")
app.include_router(incidents_router, prefix="/api")
app.include_router(config_router, prefix="/api")
app.include_router(control_router, prefix="/api")
app.include_router(journals_router, prefix="/api")
app.include_router(agents_router, prefix="/api")
app.include_router(metrics_router, prefix="/api")
app.include_router(reconciliation_router, prefix="/api")


@app.get("/")
async def root():
    return {"name": "ICT Trade Mission Control", "version": VERSION, "docs": "/docs"}


@app.post("/api/broker-test")
async def broker_test():
    result = {
        "connected": False, "auth": None, "all_accounts": None,
        "account": None, "instruments": [], "error": None,
    }
    required = ["TRADELOCKER_EMAIL", "TRADELOCKER_PASSWORD", "TRADELOCKER_SERVER", "TRADELOCKER_ACCOUNT_ID"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        result["error"] = f"Missing env vars: {missing}"
        return result
    try:
        from core.execution.client import TradeLockerClient
        client = TradeLockerClient()
        await client.connect()
        result["auth"] = "success"
        result["connected"] = True
        try:
            resp = await client._client.get(
                "/auth/jwt/all-accounts",
                headers={"Authorization": f"Bearer {client._access_token}"},
            )
            result["all_accounts"] = resp.json() if resp.status_code in (200, 201) else resp.text[:500]
        except Exception as e:
            result["all_accounts"] = str(e)
        try:
            result["account"] = await client.get_account_state()
        except Exception as e:
            result["account"] = str(e)
        try:
            instruments = await client.get_instruments()
            result["instruments"] = [{"name": i.get("name", ""), "id": i.get("tradableInstrumentId", "")} for i in instruments[:20]]
        except Exception as e:
            result["instruments"] = str(e)
        await client.disconnect()
    except Exception as e:
        result["error"] = str(e)
        result["auth"] = "failed"
    return result


@app.post("/api/seed-demo")
async def seed_demo():
    try:
        import json
        from backend.db.models import Account, TradeSignalRecord
        from backend.db.repositories.base import GenericRepository
        now = datetime.now(timezone.utc)
        created = []
        async with AsyncSessionLocal() as session:
            repo = GenericRepository(session, Account)
            if not await repo.get_by_id("acct_demo_1"):
                await repo.create(
                    id="acct_demo_1", broker_name="gatesfx", account_name="GatesFX Demo",
                    account_type="demo", mode="shadow", balance=5000, equity=5000,
                    status="connected", currency="USD", updated_at=now.isoformat(),
                )
                created.append("account")
            sig_repo = GenericRepository(session, TradeSignalRecord)
            if not await sig_repo.list_all(limit=1):
                for sym, side, conf, st in [("NAS100","buy",0.78,"pending"),("EURUSD","buy",0.74,"pending"),("US30","sell",0.82,"approved"),("BTCUSD","sell",0.65,"rejected")]:
                    await sig_repo.create(symbol=sym, strategy_name="ny_sweep_reversal", strategy_version="v1", timestamp=now.isoformat(), side=side, confidence=conf, entry_price=18245.5, stop_price=18210.0, take_profit_1=18290.0, confluence_tags=json.dumps(["smt_divergence"]), status=st, json_payload="{}")
                created.append("signals")
            await session.commit()
        return {"success": True, "created": created}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/run-scan")
async def run_scan():
    """Run one market scan cycle. Base44 calls this on a timer."""
    import json as json_mod

    now = datetime.now(timezone.utc)
    hour = now.hour
    weekday = now.weekday()

    result = {
        "timestamp": now.isoformat(),
        "symbols_scanned": [],
        "signals_generated": [],
        "errors": [],
        "session": "off_hours",
        "candle_counts": {},
    }

    # Session-aware pair selection
    active_pairs = ["BTCUSD"]  # Crypto 24/7
    result["session"] = "crypto_only"

    if weekday < 5:  # Mon-Fri
        if 13 <= hour <= 21:
            active_pairs.extend(["NAS100", "US30", "EURUSD"])
            result["session"] = "ny_session"
        elif 8 <= hour < 13:
            active_pairs.append("EURUSD")
            result["session"] = "london_pre_ny"

    try:
        from core.execution.client import TradeLockerClient

        client = TradeLockerClient()
        await client.connect()
    except Exception as e:
        result["errors"].append(f"Broker connect failed: {str(e)}")
        return result

    for symbol in active_pairs:
        try:
            instruments = await client.get_instruments()
            inst = next((i for i in instruments if i.get("name") == symbol), None)
            if not inst:
                result["errors"].append(f"{symbol}: not found in instruments")
                continue

            inst_id = inst.get("tradableInstrumentId")
            acc_id = os.environ.get("TRADELOCKER_ACCOUNT_ID", "")

            # Fetch 5-minute candles — try multiple TradeLocker API paths
            acc_num = os.environ.get("TRADELOCKER_ACC_NUM", "3")
            candle_urls = [
                f"/trade/accounts/{acc_id}/instruments/{inst_id}/candles",
                f"/trade/accounts/{acc_num}/instruments/{inst_id}/candles",
                f"/trade/history/lastCandles/{inst_id}",
                f"/trade/accounts/{acc_id}/historicalCandles/{inst_id}",
            ]
            resp = None
            used_url = None
            status_by_url = {}
            for url in candle_urls:
                try:
                    resp = await client._client.get(
                        url,
                        headers=client._auth_headers(),
                        params={"resolution": "5", "count": 200},
                    )
                    status_by_url[url] = resp.status_code
                    if resp.status_code in (200, 201):
                        used_url = url
                        break
                except Exception:
                    status_by_url[url] = "failed"
                    continue

            if not resp or resp.status_code not in (200, 201):
                tried = [f"{u} → {status_by_url.get(u, 'failed')}" for u in candle_urls]
                result["errors"].append(f"{symbol}: candles not found. Tried: {tried}")
                result["symbols_scanned"].append(symbol)
                continue

            result["candle_counts"][f"{symbol}_url"] = used_url
            candle_data = resp.json()
            result["symbols_scanned"].append(symbol)

            # Try building market structure and running strategies
            # This may fail if candle format doesn't match yet — that's OK
            # The scan still proves the data pipeline works
            try:
                from core.market_structure.engine import MarketStructureEngine

                ms_engine = MarketStructureEngine()
                market_state = ms_engine.build(symbol=symbol, candle_data=candle_data, timestamp=now)

                from core.strategy.engine import StrategyEngine

                strat_engine = StrategyEngine()
                signals = strat_engine.evaluate(market_state)

                for signal in signals:
                    from backend.db.models import TradeSignalRecord
                    from backend.db.repositories.base import GenericRepository

                    async with AsyncSessionLocal() as session:
                        repo = GenericRepository(session, TradeSignalRecord)
                        await repo.create(
                            symbol=signal.symbol,
                            strategy_name=signal.strategy_id,
                            strategy_version="v1",
                            timestamp=now.isoformat(),
                            side="buy" if signal.direction.value == "long" else "sell",
                            confidence=signal.confidence,
                            entry_price=signal.entry_price,
                            stop_price=signal.stop_price,
                            take_profit_1=signal.targets[0].price if signal.targets else None,
                            confluence_tags=json_mod.dumps(signal.confluence_tags),
                            status="pending",
                            json_payload="{}",
                        )
                        await session.commit()
                    result["signals_generated"].append(
                        {
                            "symbol": signal.symbol,
                            "strategy": signal.strategy_id,
                            "direction": signal.direction.value,
                            "confidence": signal.confidence,
                        }
                    )
            except Exception as e:
                result["errors"].append(f"{symbol}: analysis error — {str(e)[:200]}")

        except Exception as e:
            result["errors"].append(f"{symbol}: {str(e)[:200]}")

    try:
        await client.disconnect()
    except Exception:
        pass

    return result
