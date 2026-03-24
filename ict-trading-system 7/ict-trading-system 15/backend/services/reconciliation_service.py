"""Reconciliation service — persists and retrieves reconciliation state.

The reconcile_broker_state.py script writes results here.
The /api/reconciliation-status endpoint reads from here.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import IncidentRecord
from backend.db.repositories.base import GenericRepository


# In-memory cache of last reconciliation result
# (Persisted incidents are the durable record; this is for quick API reads)
_last_recon: dict[str, Any] = {
    "last_run": None,
    "status": "never_run",
    "mismatches": 0,
    "details": [],
}


class ReconciliationService:
    """Service for reconciliation state queries."""

    def __init__(self, session: AsyncSession):
        self.incident_repo = GenericRepository(session, IncidentRecord)

    async def get_status(self) -> dict[str, Any]:
        """Get current reconciliation status from DB incidents."""
        # Check for recent reconciliation incidents
        incidents = await self.incident_repo.list_all(
            limit=20, order_by="created_at", desc=True, category="reconciliation"
        )

        if not incidents:
            return {
                "last_run": _last_recon.get("last_run"),
                "status": _last_recon.get("status", "never_run"),
                "mismatches": 0,
                "details": [],
            }

        latest = incidents[0]
        open_recon = [i for i in incidents if i.status == "open"]

        return {
            "last_run": latest.created_at,
            "status": "mismatches_found" if open_recon else "clean",
            "mismatches": len(open_recon),
            "details": [
                {
                    "id": i.id,
                    "severity": i.severity,
                    "summary": i.summary,
                    "created_at": i.created_at,
                }
                for i in open_recon
            ],
        }


def update_last_recon(status: str, mismatches: int, details: list) -> None:
    """Called by the reconciliation script to update in-memory cache."""
    global _last_recon
    _last_recon = {
        "last_run": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "mismatches": mismatches,
        "details": details,
    }
