"""FastAPI dependencies — clean dependency injection for all services."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import get_db
from backend.services.core_services import (
    AccountService, AgentService, ConfigService, IncidentService,
    JournalService, MarketService, RiskService, TradeService,
)
from backend.services.signal_service import SignalService
from backend.services.pipeline_persistence import PipelinePersistence


# Config is special — it holds runtime state across requests
_config_instance: ConfigService | None = None


def get_config_service(session: AsyncSession) -> ConfigService:
    """Get or create the config service singleton.

    The config service holds runtime state (mode, flags) so it must
    persist across requests. But it gets a fresh DB session each time.
    """
    global _config_instance
    if _config_instance is None:
        _config_instance = ConfigService(session)
    else:
        # Refresh the session reference for DB operations
        from backend.db.models import ConfigChangeRecord
        from backend.db.repositories.base import GenericRepository
        _config_instance.config_repo = GenericRepository(session, ConfigChangeRecord)
    return _config_instance


def reset_config_service() -> None:
    """Reset for testing."""
    global _config_instance
    _config_instance = None
