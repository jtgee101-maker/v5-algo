"""Tests for the FastAPI backend API endpoints."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.app import app
from backend.db.base import Base
from backend.db.models import *  # noqa
from backend.dependencies import reset_config_service


@pytest.fixture(autouse=True)
def setup_test_db():
    """Create in-memory DB and override FastAPI dependencies."""
    test_engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    test_sessions = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async def setup():
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(setup())

    import backend.db.session as sess
    sess.async_engine = test_engine
    sess.AsyncSessionLocal = test_sessions

    async def override_get_db():
        async with test_sessions() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    from backend.db.session import get_db
    app.dependency_overrides[get_db] = override_get_db
    reset_config_service()

    yield

    app.dependency_overrides.clear()
    reset_config_service()


client = TestClient(app)


class TestHealth:
    def test_health_ok(self):
        r = client.get("/api/health")
        assert r.status_code == 200
        d = r.json()
        assert d["status"] == "ok"
        assert d["version"]

    def test_root(self):
        assert client.get("/").status_code == 200


class TestSignals:
    def test_list_empty(self):
        r = client.get("/api/signals")
        assert r.status_code == 200
        assert r.json()["items"] == []

    def test_approve_missing(self):
        assert client.post("/api/approve-signal", json={
            "signal_id": "x", "approved_by": "t"
        }).status_code == 404

    def test_reject_missing(self):
        assert client.post("/api/reject-signal", json={
            "signal_id": "x", "rejected_by": "t", "reason": "r"
        }).status_code == 404


class TestConfig:
    def test_get(self):
        r = client.get("/api/config")
        assert r.status_code == 200
        assert "risk" in r.json()

    def test_update(self):
        r = client.post("/api/update-config", json={
            "changed_by": "t", "reason": "test",
            "updates": {"manual_approval_required": False},
        })
        assert r.json()["success"]


class TestControl:
    def test_set_shadow(self):
        r = client.post("/api/set-mode", json={"changed_by": "t", "mode": "shadow"})
        assert r.json()["mode"] == "shadow"

    def test_set_demo(self):
        r = client.post("/api/set-mode", json={"changed_by": "t", "mode": "demo"})
        assert r.json()["mode"] == "demo"

    def test_live_locked(self):
        r = client.post("/api/set-mode", json={"changed_by": "t", "mode": "live"})
        assert r.status_code == 400

    def test_kill_switch(self):
        r = client.post("/api/kill-switch", json={"triggered_by": "t", "reason": "test"})
        d = r.json()
        assert d["success"]
        assert d["mode"] == "shadow"


class TestEmptyLists:
    def test_trades(self):
        assert client.get("/api/trades").json()["items"] == []

    def test_risk_events(self):
        assert client.get("/api/risk-events").json()["items"] == []

    def test_incidents(self):
        assert client.get("/api/incidents").json()["items"] == []

    def test_journals(self):
        assert client.get("/api/journals").json()["items"] == []

    def test_agents(self):
        assert client.get("/api/agents/runs").json()["items"] == []

    def test_market(self):
        assert client.get("/api/market-state").json()["items"] == []

    def test_account_404(self):
        assert client.get("/api/account-state").status_code == 404
