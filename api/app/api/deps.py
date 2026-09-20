"""Shared API dependencies."""
import hmac
from collections.abc import AsyncIterator

from fastapi import Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..db.session import SessionLocal


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as s:
        yield s


def require_reviewer(x_demo_passcode: str | None = Header(default=None)) -> None:
    """Gate for writes and quota-spending calls. Open when no passcode is
    configured (local dev); otherwise X-Demo-Passcode must match."""
    expected = settings.demo_passcode
    if not expected:
        return
    if not x_demo_passcode or not hmac.compare_digest(x_demo_passcode.encode(), expected.encode()):
        raise HTTPException(401, "Reviewer passcode required. Unlock reviewer mode to make changes.")
