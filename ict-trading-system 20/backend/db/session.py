"""Database session management — async SQLAlchemy engine + session factory."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.db.base import Base
from backend.db.models import *  # noqa: F401, F403 — ensure all models are loaded
from backend.settings import DATABASE_URL, DATABASE_SYNC_URL

# Async engine (for FastAPI)
async_engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

# Sync engine (for scripts, migrations, seeding)
sync_engine = create_engine(DATABASE_SYNC_URL, echo=False)


async def get_db() -> AsyncSession:
    """FastAPI dependency — yields an async DB session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def create_tables() -> None:
    """Create all tables (async)."""
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def create_tables_sync() -> None:
    """Create all tables (sync — for scripts)."""
    Base.metadata.create_all(sync_engine)
