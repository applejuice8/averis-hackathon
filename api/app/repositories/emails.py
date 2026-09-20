"""All Email + joined PipelineResult queries."""
from sqlalchemy import delete, desc, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Email, PipelineResult, Review


def latest_result_ids():
    """Latest result for each email, including emails untouched by a subset run."""
    return select(PipelineResult.id).distinct(PipelineResult.email_id).order_by(
        PipelineResult.email_id, desc(PipelineResult.created_at), desc(PipelineResult.id)
    )


def to_record(email: Email) -> dict:
    """ORM row -> the dict the pipeline consumes (same keys as inbox JSON)."""
    return {
        "email_id": email.email_id,
        "from": email.sender,
        "subject": email.subject,
        "body": email.body,
        "attachments": email.attachments or [],
    }


def list_all_statement(email_ids: list[str] | None, source: str | None):
    stmt = select(Email).order_by(Email.email_id)
    if source is not None:
        stmt = stmt.where(Email.source == source)
    if email_ids:
        stmt = stmt.where(Email.email_id.in_(email_ids))
    return stmt


async def list_all(s: AsyncSession, email_ids: list[str] | None = None, source: str | None = "dataset"):
    """Batch runs see dataset emails only, so submissions stay exactly the
    scored inbox; uploads are processed one at a time on arrival."""
    return (await s.execute(list_all_statement(email_ids, source))).scalars().all()


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


async def create_upload(s: AsyncSession, record: dict) -> Email:
    row = Email(
        email_id=record["email_id"],
        sender=record["from"],
        subject=record["subject"],
        body=record["body"],
        attachments=record["attachments"],
        source="upload",
    )
    s.add(row)
    await s.flush()
    return row


def upload_delete_statements():
    """Reviews -> results -> emails (FK order), scoped to uploaded emails."""
    uploads = select(Email.email_id).where(Email.source == "upload")
    upload_results = select(PipelineResult.id).where(PipelineResult.email_id.in_(uploads))
    return [
        delete(Review).where(Review.result_id.in_(upload_results)),
        delete(PipelineResult).where(PipelineResult.email_id.in_(uploads)),
        delete(Email).where(Email.source == "upload"),
    ]


async def delete_uploads(s: AsyncSession) -> list[str]:
    """Remove every uploaded email with its results and reviews. Returns the
    ids so the caller can delete their files. The caller commits."""
    ids = list((await s.execute(select(Email.email_id).where(Email.source == "upload"))).scalars().all())
    for stmt in upload_delete_statements():
        await s.execute(stmt)
    return ids
