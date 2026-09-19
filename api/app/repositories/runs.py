"""All Run queries."""
import uuid

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Run


async def create(s: AsyncSession, label: str) -> Run:
    run = Run(label=label)
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


async def finish(s: AsyncSession, run: Run, stats: dict) -> None:
    run.stats = stats
    run.finished_at = func.now()


async def save_score(s: AsyncSession, run_id: str, score: dict) -> None:
    run = await get(s, run_id)
    if run:
        run.score = score
        await s.commit()
