"""Backend settings — environment-driven configuration."""

from __future__ import annotations

import os
from pathlib import Path

# Project root
BASE_DIR = Path(__file__).resolve().parent.parent

# Database
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    f"sqlite+aiosqlite:///{BASE_DIR}/data/ict_trading.db",
)
DATABASE_SYNC_URL = DATABASE_URL.replace("+aiosqlite", "")

# API
API_HOST = os.environ.get("API_HOST", "0.0.0.0")
API_PORT = int(os.environ.get("API_PORT", "8000"))
API_RELOAD = os.environ.get("API_RELOAD", "true").lower() == "true"

# Pipeline
DEFAULT_MODE = os.environ.get("DEFAULT_MODE", "shadow")
LIVE_LOCKED = os.environ.get("LIVE_LOCKED", "true").lower() == "true"
MANUAL_APPROVAL_REQUIRED = os.environ.get("MANUAL_APPROVAL", "true").lower() == "true"

# Signal expiration
SIGNAL_EXPIRY_SECONDS = int(os.environ.get("SIGNAL_EXPIRY_SECONDS", "900"))  # 15 min

VERSION = "0.5.0"
