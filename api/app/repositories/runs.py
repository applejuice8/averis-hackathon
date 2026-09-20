"""All Run queries."""
import uuid
from datetime import UTC, datetime

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Run


async def create(s: AsyncSession, label: str) -> Run:
    run = Run(label=label)
    s.add(run)
    await s.flush()
    return run


async def get_or_create(s: AsyncSession, label: str) -> Run:
    """Long-lived run collecting one-off results (uploads, retries). Marked
    finished at creation so it never shows as an in-progress batch."""
    run = (
        await s.execute(select(Run).where(Run.label == label).order_by(Run.started_at).limit(1))
    ).scalar_one_or_none()
    if run is None:
        run = Run(label=label, finished_at=datetime.now(UTC), stats={})
        s.add(run)
        await s.flush()
    return run


async def list_recent(s: AsyncSession, limit: int = 50):
    return (
        await s.execute(select(Run).order_by(desc(Run.started_at)).limit(limit))
    ).scalars().all()


async def get(s: AsyncSession, run_id: str | uuid.UUID) -> Run | None:
    if isinstance(run_id, str):
        run_id = uuid.UUID(run_id)
    return await s.get(Run, run_id)


async def delete(s: AsyncSession, run_id: str | uuid.UUID) -> None:
    run = await get(s, run_id)
    if run is not None:
        await s.delete(run)


async def finish(s: AsyncSession, run: Run, stats: dict) -> None:
    run.stats = stats
    run.error = None
    run.finished_at = func.now()


async def fail(s: AsyncSession, run: Run, error: str) -> None:
    run.error = error[:500]
    run.finished_at = datetime.now(UTC)


async def save_score(s: AsyncSession, run_id: str, score: dict) -> None:
    run = await get(s, run_id)
    if run:
        run.score = score
        await s.commit()
