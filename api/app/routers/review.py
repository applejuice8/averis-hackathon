import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import SessionLocal
from ..models import PipelineResult, Review, Run

router = APIRouter(prefix="/api")


async def get_session():
    async with SessionLocal() as s:
        yield s


@router.get("/review")
async def review_queue(s: AsyncSession = Depends(get_session)):
    """NEEDS_REVIEW + FAILED results from the latest run."""
    latest_run = select(Run.id).order_by(desc(Run.started_at)).limit(1).scalar_subquery()
    rows = (
        await s.execute(
            select(PipelineResult)
            .where(PipelineResult.run_id == latest_run)
            .where(PipelineResult.status.in_(["NEEDS_REVIEW", "FAILED"]))
            .order_by(PipelineResult.email_id)
        )
    ).scalars().all()
    return [
        {
            "result_id": str(r.id),
            "email_id": r.email_id,
            "status": r.status,
            "review_reason": r.review_reason,
            "evidence": r.evidence,
            "error": r.error,
        }
        for r in rows
    ]


class ReviewAction(BaseModel):
    action: str  # confirm | override_status | override_fields
    payload: dict | None = None
    reviewer: str | None = None


@router.post("/review/{result_id}")
async def review_action(result_id: str, body: ReviewAction, s: AsyncSession = Depends(get_session)):
    res = await s.get(PipelineResult, uuid.UUID(result_id))
    if not res:
        raise HTTPException(404, "no such result")
    s.add(Review(result_id=res.id, action=body.action, payload=body.payload, reviewer=body.reviewer))
    if body.action == "confirm":
        pass  # verdict stands; record the confirmation only
    elif body.action == "override_status" and body.payload:
        res.status = body.payload.get("status", res.status)
        res.review_reason = body.payload.get("review_reason", res.review_reason)
    elif body.action == "override_fields" and body.payload:
        res.defect_fields = body.payload.get("defect_fields", res.defect_fields)
        res.has_defect = bool(res.defect_fields)
        res.status = "MISMATCH" if res.has_defect else "OK"
        res.review_reason = None
    await s.commit()
    return {"ok": True, "status": res.status}
