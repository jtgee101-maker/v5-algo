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
