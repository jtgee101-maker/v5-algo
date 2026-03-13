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
    review_router,
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
app.include_router(review_router, prefix="/api")


@app.get("/")
async def root():
    return {"name": "ICT Trade Mission Control", "version": VERSION, "docs": "/docs"}


# ══════════════════════════════════════════════════════════════════════
# BROKER TEST
# ══════════════════════════════════════════════════════════════════════

@app.post("/api/broker-test")
async def broker_test():
    """Verify TradeLocker auth and account connectivity."""
    result = {
        "connected": False, "auth": None, "all_accounts": None,
        "account": None, "instruments": [], "error": None,
    }
    required = ["TRADELOCKER_EMAIL", "TRADELOCKER_PASSWORD", "TRADELOCKER_SERVER"]
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
            result["instruments"] = [
                {"name": i.get("name", ""), "id": i.get("tradableInstrumentId", "")}
                for i in instruments[:30]
            ]
        except Exception as e:
            result["instruments"] = str(e)
        await client.disconnect()
    except Exception as e:
        result["error"] = str(e)
        result["auth"] = "failed"
    return result


# ══════════════════════════════════════════════════════════════════════
# SEED DEMO DATA
# ══════════════════════════════════════════════════════════════════════

@app.post("/api/seed-demo")
async def seed_demo():
    """Seed the database with demo data for UI testing."""
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
                    account_type="demo", mode="shadow", balance=50000, equity=50000,
                    free_margin=50000, status="connected", currency="USD",
                    updated_at=now.isoformat(),
                )
                created.append("account")
            sig_repo = GenericRepository(session, TradeSignalRecord)
            if not await sig_repo.list_all(limit=1):
                for sym, side, conf, st in [
                    ("NAS100", "buy", 0.78, "pending"),
                    ("EURUSD", "buy", 0.74, "pending"),
                    ("US30", "sell", 0.82, "approved"),
                    ("BTCUSD", "sell", 0.65, "rejected"),
                ]:
                    await sig_repo.create(
                        symbol=sym, strategy_name="ny_sweep_reversal",
                        strategy_version="v1", timestamp=now.isoformat(),
                        side=side, confidence=conf, entry_price=18245.5,
                        stop_price=18210.0, take_profit_1=18290.0,
                        confluence_tags=json.dumps(["smt_divergence", "sweep_rejected"]),
                        status=st, json_payload="{}",
                    )
                created.append("signals")
            await session.commit()
        return {"success": True, "created": created}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ══════════════════════════════════════════════════════════════════════
# MARKET SCANNER — called by Base44 on a timer
# ══════════════════════════════════════════════════════════════════════

@app.post("/api/run-scan")
async def run_scan():
    """Scan active pairs based on session, run strategies, persist signals.

    Session logic:
    - BTCUSD: 24/7 (always scanned)
    - EURUSD: Mon-Fri 08:00-21:00 UTC (London + NY)
    - NAS100, US30: Mon-Fri 13:00-21:00 UTC (NY session)

    Base44 calls this every 60 seconds when auto-scan is enabled.
    """
    import json as json_mod

    now = datetime.now(timezone.utc)
    hour, weekday = now.hour, now.weekday()

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

    # Connect to broker
    try:
        from core.execution.client import TradeLockerClient
        client = TradeLockerClient()
        await client.connect()
    except Exception as e:
        result["errors"].append(f"Broker: {str(e)[:200]}")
        return result

    # Update account balance in DB
    try:
        acct_data = await client.get_account_state()
        if acct_data and isinstance(acct_data, dict) and acct_data.get("s") == "ok":
            details = acct_data.get("d", {}).get("accountDetailsData", [])
            if len(details) >= 5:
                from backend.db.models import Account
                from backend.db.repositories.base import GenericRepository
                async with AsyncSessionLocal() as session:
                    repo = GenericRepository(session, Account)
                    await repo.update_by_id(
                        "acct_demo_1",
                        balance=float(details[0]),
                        equity=float(details[1]),
                        free_margin=float(details[4]) if len(details) > 4 else 0,
                        status="connected",
                        updated_at=now.isoformat(),
                    )
                    await session.commit()
    except Exception as e:
        result["errors"].append(f"Account update: {str(e)[:100]}")

    # Scan each active pair
    for symbol in active_pairs:
        try:
            instruments = await client.get_instruments()
            inst = next((i for i in instruments if i.get("name") == symbol), None)
            if not inst:
                result["errors"].append(f"{symbol}: not found in broker instruments")
                continue

            inst_id = inst.get("tradableInstrumentId")
            acc_id = os.environ.get("TRADELOCKER_ACCOUNT_ID", "")

            # Fetch 5-minute candles
            resp = await client._client.get(
                f"/trade/accounts/{acc_id}/instruments/{inst_id}/candles",
                headers=client._auth_headers(),
                params={"resolution": "5", "count": 200},
            )

            if resp.status_code not in (200, 201):
                result["errors"].append(f"{symbol}: candles HTTP {resp.status_code}")
                result["symbols_scanned"].append(symbol)
                continue

            candle_data = resp.json()
            result["symbols_scanned"].append(symbol)

            # Count candles for diagnostics
            if isinstance(candle_data, dict) and "d" in candle_data:
                bars = candle_data["d"]
                if isinstance(bars, list):
                    result["candle_counts"][symbol] = len(bars)
                elif isinstance(bars, dict):
                    first_key = next(iter(bars), None)
                    if first_key and isinstance(bars[first_key], list):
                        result["candle_counts"][symbol] = len(bars[first_key])

            # Try market structure + strategy analysis
            try:
                from core.market_structure.engine import MarketStructureEngine
                market_state = MarketStructureEngine().build(
                    symbol=symbol, candle_data=candle_data, timestamp=now
                )

                from core.strategy.engine import StrategyEngine
                signals = StrategyEngine().evaluate(market_state)

                for signal in signals:
                    from backend.db.models import TradeSignalRecord
                    from backend.db.repositories.base import GenericRepository
                    async with AsyncSessionLocal() as session:
                        await GenericRepository(session, TradeSignalRecord).create(
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
                            json_payload=json_mod.dumps({
                                "reward_risk": signal.reward_risk,
                                "invalidation": signal.invalidation,
                            }),
                        )
                        await session.commit()

                    result["signals_generated"].append({
                        "symbol": signal.symbol,
                        "strategy": signal.strategy_id,
                        "direction": signal.direction.value,
                        "confidence": round(signal.confidence, 3),
                        "entry": signal.entry_price,
                        "stop": signal.stop_price,
                        "rr": signal.reward_risk,
                    })

            except Exception as e:
                result["errors"].append(f"{symbol}: analysis — {str(e)[:200]}")

        except Exception as e:
            result["errors"].append(f"{symbol}: {str(e)[:200]}")

    try:
        await client.disconnect()
    except Exception:
        pass

    return result
