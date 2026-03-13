"""FastAPI application — ICT Trade Mission Control API."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
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
from backend.db.session import create_tables
from backend.settings import VERSION


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create DB tables on startup. Ensure data directory exists for SQLite."""
    from backend.settings import DATA_DIR
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    await create_tables()
    yield


app = FastAPI(
    title="ICT Trade Mission Control",
    description="Self-healing agent-assisted CFD trading system API",
    version=VERSION,
    lifespan=lifespan,
)

# CORS — allow Base44 and local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount all routers under /api
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


@app.post("/api/seed-demo")
async def seed_demo_data():
    """Seed demo records for empty dashboards."""
    from asyncio import to_thread

    from scripts.bootstrap_demo_data import seed

    await to_thread(seed)
    return {"success": True, "message": "Demo data seeded."}


@app.post("/api/broker-test")
async def broker_test():
    """Verify TradeLocker auth and account connectivity from env vars."""
    from core.execution.client import BrokerError, TradeLockerClient

    client = TradeLockerClient()
    try:
        await client.connect()
        account = await client.get_account_state()
        return {"success": True, "base_url": client.base_url, "account": account}
    except BrokerError as exc:
        raise HTTPException(status_code=502, detail={"success": False, "error": exc.detail})
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"success": False, "error": str(exc)})
    finally:
        await client.disconnect()
