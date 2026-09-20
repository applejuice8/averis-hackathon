"""All Email + joined PipelineResult queries."""
from sqlalchemy import desc, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Email, PipelineResult


def latest_result_ids():
    """Latest result for each email, including emails untouched by a subset run."""
    return select(PipelineResult.id).distinct(PipelineResult.email_id).order_by(
        PipelineResult.email_id, desc(PipelineResult.created_at), desc(PipelineResult.id)
    )


async def list_all(s: AsyncSession, email_ids: list[str] | None = None):
    stmt = select(Email).order_by(Email.email_id)
    if email_ids:
        stmt = stmt.where(Email.email_id.in_(email_ids))
    return (await s.execute(stmt)).scalars().all()


async def list_with_latest_results(
    s: AsyncSession,
    queue: str | None = None,
    status: str | None = None,
    q: str | None = None,
) -> list[tuple[Email, PipelineResult | None]]:
    """Inbox view: every email outer-joined to its latest available result."""
    stmt = (
        select(Email, PipelineResult)
        .outerjoin(
            PipelineResult,
            (PipelineResult.email_id == Email.email_id)
            & (PipelineResult.id.in_(latest_result_ids())),
        )
        .order_by(Email.email_id)
    )
    rows = (await s.execute(stmt)).all()
    if queue or status or q:
        rows = [
            (e, r)
            for e, r in rows
            if (not queue or (r and r.category == queue))
            and (not status or (r and r.status == status))
            and (
                not q
                or q.lower() in (e.email_id + (e.subject or "") + (e.sender or "")).lower()
            )
        ]
    return rows


async def get_by_id(s: AsyncSession, email_id: str) -> Email | None:
    return (
        await s.execute(select(Email).where(Email.email_id == email_id))
    ).scalar_one_or_none()


async def upsert_many(s: AsyncSession, records: list[dict]) -> int:
    for rec in records:
        stmt = (
            insert(Email)
            .values(
                email_id=rec["email_id"],
                sender=rec.get("from", ""),
                subject=rec.get("subject", ""),
                body=rec.get("body", ""),
                attachments=rec.get("attachments", []),
            )
            .on_conflict_do_update(
                index_elements=["email_id"],
                set_={
                    "sender": rec.get("from", ""),
                    "subject": rec.get("subject", ""),
                    "body": rec.get("body", ""),
                    "attachments": rec.get("attachments", []),
                },
            )
        )
        await s.execute(stmt)
    await s.commit()
    return len(records)
