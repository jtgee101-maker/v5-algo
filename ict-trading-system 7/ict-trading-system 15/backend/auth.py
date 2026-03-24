"""Authentication and authorization middleware.

Simple API key auth with role-based access control.
Roles: admin, operator, viewer.

API keys are stored in environment variable API_KEYS as JSON:
  export API_KEYS='{"admin-key-123": "admin", "operator-key-456": "operator", "viewer-key-789": "viewer"}'

Or set AUTH_DISABLED=true to bypass (for local development only).
"""

from __future__ import annotations

import json
import os
from typing import Optional

from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader

# Auth config
AUTH_DISABLED = os.environ.get("AUTH_DISABLED", "true").lower() == "true"

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _load_api_keys() -> dict[str, str]:
    """Load API key → role mapping from environment."""
    raw = os.environ.get("API_KEYS", "{}")
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}


class AuthContext:
    """Represents the authenticated user context."""

    def __init__(self, api_key: str, role: str):
        self.api_key = api_key
        self.role = role  # admin, operator, viewer

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def is_operator(self) -> bool:
        return self.role in ("admin", "operator")

    @property
    def is_viewer(self) -> bool:
        return self.role in ("admin", "operator", "viewer")


# ── Dependency Functions ──────────────────────────────────────────────

async def get_auth(api_key: Optional[str] = Security(_api_key_header)) -> AuthContext:
    """Authenticate the request. Returns AuthContext.

    If AUTH_DISABLED=true, returns an admin context (for dev).
    """
    if AUTH_DISABLED:
        return AuthContext(api_key="dev", role="admin")

    if not api_key:
        raise HTTPException(status_code=401, detail="Missing API key")

    keys = _load_api_keys()
    role = keys.get(api_key)
    if role is None:
        raise HTTPException(status_code=401, detail="Invalid API key")

    return AuthContext(api_key=api_key, role=role)


def require_admin(auth: AuthContext) -> AuthContext:
    """Require admin role."""
    if not auth.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return auth


def require_operator(auth: AuthContext) -> AuthContext:
    """Require operator or admin role."""
    if not auth.is_operator:
        raise HTTPException(status_code=403, detail="Operator access required")
    return auth


def require_viewer(auth: AuthContext) -> AuthContext:
    """Require any authenticated role."""
    if not auth.is_viewer:
        raise HTTPException(status_code=403, detail="Authentication required")
    return auth
