"""All Review queries."""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Review


async def add(
    s: AsyncSession,
    result_id: uuid.UUID,
    action: str,
    payload: dict | None,
    reviewer: str | None,
) -> Review:
    row = Review(result_id=result_id, action=action, payload=payload, reviewer=reviewer)
    s.add(row)
    return row
