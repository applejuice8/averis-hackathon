"""All PipelineResult queries."""
import uuid
from collections.abc import Sequence

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import PipelineResult
from .emails import latest_run_id_subquery


async def latest_for_email(
    s: AsyncSession, email_id: str
) -> PipelineResult | None:
    return (
        await s.execute(
            select(PipelineResult)
            .where(PipelineResult.email_id == email_id)
            .order_by(desc(PipelineResult.created_at))
            .limit(1)
        )
    ).scalar_one_or_none()


async def add(s: AsyncSession, run_id: uuid.UUID, result: dict) -> PipelineResult:
    row = PipelineResult(run_id=run_id, **result)
    s.add(row)
    return row


async def stats_by_category_status(
    s: AsyncSession, run_id: uuid.UUID
) -> dict[str, int]:
    rows = await s.execute(
        select(PipelineResult.category, PipelineResult.status, func.count())
        .where(PipelineResult.run_id == run_id)
        .group_by(PipelineResult.category, PipelineResult.status)
    )
    return {f"{cat}:{status}": n for cat, status, n in rows}


async def count_for_run(s: AsyncSession, run_id: uuid.UUID) -> int:
    return (
        await s.execute(
            select(func.count())
            .select_from(PipelineResult)
            .where(PipelineResult.run_id == run_id)
        )
    ).scalar_one()


async def for_run(
    s: AsyncSession, run_id: str | uuid.UUID
) -> Sequence[PipelineResult]:
    if isinstance(run_id, str):
        run_id = uuid.UUID(run_id)
    return (
        await s.execute(
            select(PipelineResult).where(PipelineResult.run_id == run_id)
        )
    ).scalars().all()


async def review_queue(s: AsyncSession) -> Sequence[PipelineResult]:
    """NEEDS_REVIEW + FAILED results from the latest run."""
    return (
        await s.execute(
            select(PipelineResult)
            .where(PipelineResult.run_id == latest_run_id_subquery())
            .where(PipelineResult.status.in_(["NEEDS_REVIEW", "FAILED"]))
            .order_by(PipelineResult.email_id)
        )
    ).scalars().all()


async def get(s: AsyncSession, result_id: str | uuid.UUID) -> PipelineResult | None:
    if isinstance(result_id, str):
        result_id = uuid.UUID(result_id)
    return await s.get(PipelineResult, result_id)
