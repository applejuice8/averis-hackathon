from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import SessionLocal
from ..models import Email, PipelineResult, Run

router = APIRouter(prefix="/api")


async def get_session():
    async with SessionLocal() as s:
        yield s


@router.get("/emails")
async def list_emails(
    queue: str | None = Query(default=None),
    status: str | None = Query(default=None),
    q: str | None = Query(default=None),
    s: AsyncSession = Depends(get_session),
):
    """All emails joined to their latest pipeline result (if any)."""
    latest_run = select(Run.id).order_by(desc(Run.started_at)).limit(1).scalar_subquery()
    stmt = (
        select(Email, PipelineResult)
        .outerjoin(
            PipelineResult,
            (PipelineResult.email_id == Email.email_id)
            & (PipelineResult.run_id == latest_run),
        )
        .order_by(Email.email_id)
    )
    rows = (await s.execute(stmt)).all()
    out = []
    for email, res in rows:
        item = {
            "email_id": email.email_id,
            "sender": email.sender,
            "subject": email.subject,
            "n_attachments": len(email.attachments or []),
            "category": res.category if res else None,
            "status": res.status if res else None,
            "has_defect": res.has_defect if res else None,
            "defect_fields": res.defect_fields if res else None,
            "review_reason": res.review_reason if res else None,
            "decided_by": res.decided_by if res else None,
        }
        if queue and item["category"] != queue:
            continue
        if status and item["status"] != status:
            continue
        if q and q.lower() not in (item["subject"] or "").lower() + (item["sender"] or "").lower():
            continue
        out.append(item)
    return out


@router.get("/emails/{email_id}")
async def get_email(email_id: str, s: AsyncSession = Depends(get_session)):
    email = (
        await s.execute(select(Email).where(Email.email_id == email_id))
    ).scalar_one_or_none()
    if email is None:
        raise HTTPException(404, f"no such email: {email_id}")
    res = (
        await s.execute(
            select(PipelineResult)
            .where(PipelineResult.email_id == email_id)
            .order_by(desc(PipelineResult.created_at))
            .limit(1)
        )
    ).scalar_one_or_none()
    return {
        "email_id": email.email_id,
        "sender": email.sender,
        "subject": email.subject,
        "body": email.body,
        "attachments": email.attachments or [],
        "result": (
            {
                "category": res.category,
                "decided_by": res.decided_by,
                "status": res.status,
                "review_reason": res.review_reason,
                "has_defect": res.has_defect,
                "defect_fields": res.defect_fields,
                "si_fields": res.si_fields,
                "bl_fields": res.bl_fields,
                "doc_types": res.doc_types,
                "evidence": res.evidence,
                "error": res.error,
            }
            if res
            else None
        ),
    }
