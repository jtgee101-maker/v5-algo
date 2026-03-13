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
    """Create the demo account record if the DB is empty."""
    try:
        from backend.db.models import Account
        from backend.db.repositories.base import GenericRepository

        async with AsyncSessionLocal() as session:
            repo = GenericRepository(session, Account)
            existing = await repo.list_all(limit=1)
            if not existing:
                await repo.create(
                    id="acct_demo_1",
                    broker_name="gatesfx",
                    account_name="GatesFX Demo",
                    account_type="demo",
                    mode="shadow",
                    balance=0,
                    equity=0,
                    margin_used=0,
                    free_margin=0,
                    drawdown_pct=0,
                    status="disconnected",
                    currency="USD",
                    updated_at=datetime.now(timezone.utc).isoformat(),
                )
                await session.commit()
    except Exception:
        pass  # Non-critical — account will be created when pipeline runs


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create DB tables on startup. Seed account if empty."""
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

# CORS — allow Base44 and local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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


@app.post("/api/broker-test")
async def broker_test():
    """Test the TradeLocker broker connection using env var credentials.

    Returns connection status, account info, and available instruments.
    """
    import structlog
    logger = structlog.get_logger(__name__)

    result = {
        "connected": False,
        "auth": None,
        "account": None,
        "instruments": [],
        "error": None,
    }

    # Check env vars
    required = ["TRADELOCKER_EMAIL", "TRADELOCKER_PASSWORD", "TRADELOCKER_SERVER", "TRADELOCKER_ACCOUNT_ID"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        result["error"] = f"Missing environment variables: {missing}"
        return result

    try:
        from core.execution.client import TradeLockerClient

        client = TradeLockerClient()
        await client.connect()
        result["auth"] = "success"
        result["connected"] = True

        # Get account state
        try:
            acct = await client.get_account_state()
            result["account"] = {
                "equity": acct.get("equity"),
                "balance": acct.get("balance"),
                "margin_used": acct.get("marginUsed"),
                "free_margin": acct.get("freeMargin"),
            }

            # Update DB account record
            try:
                from backend.db.models import Account
                from backend.db.repositories.base import GenericRepository
                async with AsyncSessionLocal() as session:
                    repo = GenericRepository(session, Account)
                    await repo.update_by_id(
                        "acct_demo_1",
                        balance=float(acct.get("balance", 0)),
                        equity=float(acct.get("equity", 0)),
                        margin_used=float(acct.get("marginUsed", 0)),
                        free_margin=float(acct.get("freeMargin", 0)),
                        status="connected",
                        updated_at=datetime.now(timezone.utc).isoformat(),
                    )
                    await session.commit()
            except Exception as e:
                logger.warning("broker_test.db_update_failed", error=str(e))

        except Exception as e:
            result["account"] = f"Failed: {str(e)}"

        # Get instruments
        try:
            instruments = await client.get_instruments()
            result["instruments"] = [
                {
                    "name": i.get("name", ""),
                    "id": i.get("tradableInstrumentId", ""),
                }
                for i in instruments[:20]
            ]
        except Exception as e:
            result["instruments"] = f"Failed: {str(e)}"

        await client.disconnect()

    except Exception as e:
        result["error"] = str(e)
        result["auth"] = "failed"

    return result


@app.post("/api/seed-demo")
async def seed_demo():
    """Seed the database with demo data for UI testing."""
    try:
        import json
        from backend.db.models import (
            Account, TradeSignalRecord, RiskEventRecord,
            IncidentRecord, JournalEntryRecord, AgentRunRecord,
        )
        from backend.db.repositories.base import GenericRepository

        now = datetime.now(timezone.utc)
        created = []

        async with AsyncSessionLocal() as session:
            # Ensure account exists
            acct_repo = GenericRepository(session, Account)
            acct = await acct_repo.get_by_id("acct_demo_1")
            if not acct:
                await acct_repo.create(
                    id="acct_demo_1", broker_name="gatesfx",
                    account_name="GatesFX Demo", account_type="demo",
                    mode="shadow", balance=5000, equity=5000,
                    status="connected", currency="USD",
                    updated_at=now.isoformat(),
                )
                created.append("account")

            # Add sample signals
            sig_repo = GenericRepository(session, TradeSignalRecord)
            existing_sigs = await sig_repo.list_all(limit=1)
            if not existing_sigs:
                for i, (sym, side, conf, status) in enumerate([
                    ("NAS100", "buy", 0.78, "pending"),
                    ("EURUSD", "buy", 0.74, "pending"),
                    ("US30", "sell", 0.82, "approved"),
                    ("BTCUSD", "sell", 0.65, "rejected"),
                ]):
                    await sig_repo.create(
                        symbol=sym, strategy_name="ny_sweep_reversal",
                        strategy_version="v1",
                        timestamp=now.isoformat(), side=side,
                        confidence=conf, entry_price=18245.5 + i * 100,
                        stop_price=18210.0 + i * 100,
                        take_profit_1=18290.0 + i * 100,
                        confluence_tags=json.dumps(["smt_divergence", "sweep_rejected"]),
                        status=status,
                        json_payload="{}",
                    )
                created.append("signals")

            # Add sample incidents
            inc_repo = GenericRepository(session, IncidentRecord)
            existing_inc = await inc_repo.list_all(limit=1)
            if not existing_inc:
                await inc_repo.create(
                    title="System initialized",
                    category="system", severity="info",
                    source="seed", status="resolved",
                    summary="Demo data seeded successfully",
                    created_at=now.isoformat(),
                    resolved_at=now.isoformat(),
                )
                created.append("incidents")

            await session.commit()

        return {"success": True, "created": created}
    except Exception as e:
        return {"success": False, "error": str(e)}
