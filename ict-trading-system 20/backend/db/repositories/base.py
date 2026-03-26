"""Generic repository — reusable CRUD operations for all models."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, Type, TypeVar
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.base import Base

T = TypeVar("T", bound=Base)


class GenericRepository:
    """Generic async CRUD repository."""

    def __init__(self, session: AsyncSession, model: Type[T]):
        self.session = session
        self.model = model

    async def get_by_id(self, id: str) -> Optional[T]:
        result = await self.session.execute(
            select(self.model).where(self.model.id == id)
        )
        return result.scalar_one_or_none()

    async def list_all(
        self,
        limit: int = 50,
        offset: int = 0,
        order_by: Optional[str] = None,
        desc: bool = True,
        **filters: Any,
    ) -> list[T]:
        stmt = select(self.model)
        for key, val in filters.items():
            if val is not None and hasattr(self.model, key):
                stmt = stmt.where(getattr(self.model, key) == val)
        if order_by and hasattr(self.model, order_by):
            col = getattr(self.model, order_by)
            stmt = stmt.order_by(col.desc() if desc else col.asc())
        stmt = stmt.limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, **kwargs: Any) -> T:
        if "id" not in kwargs:
            kwargs["id"] = str(uuid4())
        obj = self.model(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def update_by_id(self, id: str, **kwargs: Any) -> Optional[T]:
        await self.session.execute(
            update(self.model).where(self.model.id == id).values(**kwargs)
        )
        await self.session.flush()
        return await self.get_by_id(id)

    async def count(self, **filters: Any) -> int:
        stmt = select(self.model)
        for key, val in filters.items():
            if val is not None and hasattr(self.model, key):
                stmt = stmt.where(getattr(self.model, key) == val)
        result = await self.session.execute(stmt)
        return len(result.scalars().all())
