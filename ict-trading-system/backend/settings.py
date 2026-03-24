"""Backend settings — environment-driven, Render-compatible.

Handles:
- Render's PORT env var
- Render's ephemeral filesystem (ensures data/ dir exists for SQLite)
- DATABASE_URL override for Postgres when available
- Safe sync URL derivation for both SQLite and Postgres
"""

from __future__ import annotations

import os
from pathlib import Path

# Project root
BASE_DIR = Path(__file__).resolve().parent.parent

# Ensure data directory exists (Render's filesystem is ephemeral but writable)
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Database
# Render sets DATABASE_URL for Postgres add-ons.
# Default to SQLite in data/ for local dev and free-tier Render.
_default_db = f"sqlite+aiosqlite:///{DATA_DIR}/ict_trading.db"
DATABASE_URL = os.environ.get("DATABASE_URL", _default_db)

# Handle Render's postgres:// prefix (SQLAlchemy needs postgresql://)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)

# Sync URL for scripts/seeding
if "sqlite" in DATABASE_URL:
    DATABASE_SYNC_URL = DATABASE_URL.replace("+aiosqlite", "")
elif "asyncpg" in DATABASE_URL:
    DATABASE_SYNC_URL = DATABASE_URL.replace("+asyncpg", "")
else:
    DATABASE_SYNC_URL = DATABASE_URL

# API — Render sets PORT automatically
API_HOST = os.environ.get("API_HOST", "0.0.0.0")
API_PORT = int(os.environ.get("PORT", os.environ.get("API_PORT", "8000")))
API_RELOAD = os.environ.get("API_RELOAD", "false").lower() == "true"

# Pipeline
DEFAULT_MODE = os.environ.get("DEFAULT_MODE", "shadow")
LIVE_LOCKED = os.environ.get("LIVE_LOCKED", "true").lower() == "true"
MANUAL_APPROVAL_REQUIRED = os.environ.get("MANUAL_APPROVAL", "true").lower() == "true"

# Auth
AUTH_DISABLED = os.environ.get("AUTH_DISABLED", "true").lower() == "true"

# Signal expiration
SIGNAL_EXPIRY_SECONDS = int(os.environ.get("SIGNAL_EXPIRY_SECONDS", "900"))  # 15 min

VERSION = "0.5.0"
