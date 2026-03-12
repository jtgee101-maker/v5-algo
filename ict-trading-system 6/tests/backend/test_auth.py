"""Tests for authentication and role-based access control.

Covers:
- Unauthenticated access when auth is enabled
- Admin-only endpoints blocked for operator/viewer
- Operator endpoints blocked for viewer
- Read endpoints accessible to all
"""

from __future__ import annotations

import os
import json
import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.app import app
from backend.db.base import Base
from backend.db.models import *  # noqa
from backend.dependencies import reset_config_service
import backend.auth as auth_module


@pytest.fixture(autouse=True)
def setup_auth_test():
    """Set up test DB and enable auth with test keys."""
    # Create in-memory DB
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    asyncio.run((lambda: _setup_async(engine))())

    import backend.db.session as sess
    sess.async_engine = engine
    sess.AsyncSessionLocal = sessions

    async def override_get_db():
        async with sessions() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    from backend.db.session import get_db
    app.dependency_overrides[get_db] = override_get_db
    reset_config_service()

    # Enable auth with test keys
    auth_module.AUTH_DISABLED = False
    os.environ["API_KEYS"] = json.dumps({
        "admin-key": "admin",
        "operator-key": "operator",
        "viewer-key": "viewer",
    })

    yield

    # Cleanup
    app.dependency_overrides.clear()
    reset_config_service()
    auth_module.AUTH_DISABLED = True
    os.environ.pop("API_KEYS", None)


async def _setup_async(engine):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


client = TestClient(app)


class TestUnauthenticated:
    """Endpoints requiring auth should reject unauthenticated requests."""

    def test_approve_no_key(self):
        r = client.post("/api/approve-signal", json={
            "signal_id": "x", "approved_by": "t",
        })
        assert r.status_code == 401

    def test_reject_no_key(self):
        r = client.post("/api/reject-signal", json={
            "signal_id": "x", "rejected_by": "t", "reason": "r",
        })
        assert r.status_code == 401

    def test_kill_switch_no_key(self):
        r = client.post("/api/kill-switch", json={
            "triggered_by": "t", "reason": "r",
        })
        assert r.status_code == 401

    def test_set_mode_no_key(self):
        r = client.post("/api/set-mode", json={
            "changed_by": "t", "mode": "shadow",
        })
        assert r.status_code == 401

    def test_update_config_no_key(self):
        r = client.post("/api/update-config", json={
            "changed_by": "t", "reason": "r", "updates": {},
        })
        assert r.status_code == 401

    def test_invalid_key(self):
        r = client.post(
            "/api/kill-switch",
            json={"triggered_by": "t", "reason": "r"},
            headers={"X-API-Key": "wrong-key"},
        )
        assert r.status_code == 401


class TestAdminOnly:
    """Admin-only endpoints must reject operator and viewer."""

    def test_kill_switch_admin_ok(self):
        r = client.post(
            "/api/kill-switch",
            json={"triggered_by": "t", "reason": "test"},
            headers={"X-API-Key": "admin-key"},
        )
        assert r.status_code == 200

    def test_kill_switch_operator_forbidden(self):
        r = client.post(
            "/api/kill-switch",
            json={"triggered_by": "t", "reason": "test"},
            headers={"X-API-Key": "operator-key"},
        )
        assert r.status_code == 403

    def test_kill_switch_viewer_forbidden(self):
        r = client.post(
            "/api/kill-switch",
            json={"triggered_by": "t", "reason": "test"},
            headers={"X-API-Key": "viewer-key"},
        )
        assert r.status_code == 403

    def test_set_mode_operator_forbidden(self):
        r = client.post(
            "/api/set-mode",
            json={"changed_by": "t", "mode": "shadow"},
            headers={"X-API-Key": "operator-key"},
        )
        assert r.status_code == 403

    def test_update_config_operator_forbidden(self):
        r = client.post(
            "/api/update-config",
            json={"changed_by": "t", "reason": "r", "updates": {}},
            headers={"X-API-Key": "operator-key"},
        )
        assert r.status_code == 403


class TestOperatorAccess:
    """Operator can approve/reject but not admin actions."""

    def test_approve_operator_ok(self):
        # Will 404 because no signal exists, but auth passes
        r = client.post(
            "/api/approve-signal",
            json={"signal_id": "x", "approved_by": "t"},
            headers={"X-API-Key": "operator-key"},
        )
        assert r.status_code == 404  # Not 401 or 403

    def test_reject_operator_ok(self):
        r = client.post(
            "/api/reject-signal",
            json={"signal_id": "x", "rejected_by": "t", "reason": "r"},
            headers={"X-API-Key": "operator-key"},
        )
        assert r.status_code == 404  # Not 401 or 403

    def test_approve_viewer_forbidden(self):
        r = client.post(
            "/api/approve-signal",
            json={"signal_id": "x", "approved_by": "t"},
            headers={"X-API-Key": "viewer-key"},
        )
        assert r.status_code == 403


class TestReadEndpoints:
    """Read endpoints should work for any valid key."""

    def test_health_viewer(self):
        r = client.get("/api/health", headers={"X-API-Key": "viewer-key"})
        assert r.status_code == 200

    def test_signals_viewer(self):
        r = client.get("/api/signals", headers={"X-API-Key": "viewer-key"})
        assert r.status_code == 200

    def test_config_viewer(self):
        r = client.get("/api/config", headers={"X-API-Key": "viewer-key"})
        assert r.status_code == 200

    def test_metrics_overview(self):
        r = client.get("/api/metrics/overview", headers={"X-API-Key": "viewer-key"})
        assert r.status_code == 200

    def test_metrics_strategies(self):
        r = client.get("/api/metrics/strategies", headers={"X-API-Key": "viewer-key"})
        assert r.status_code == 200

    def test_metrics_sessions(self):
        r = client.get("/api/metrics/sessions", headers={"X-API-Key": "viewer-key"})
        assert r.status_code == 200
