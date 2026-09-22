"""Shared API dependencies."""
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from ..db.session import SessionLocal


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as s:
        yield s
