from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...repositories import results as results_repo
from ...schemas.runs import ReviewActionIn, ReviewItem, ReviewOutcome
from ...services import review as review_service
from ..deps import get_db, require_reviewer

router = APIRouter()


@router.get("/review", response_model=list[ReviewItem])
async def review_queue(s: AsyncSession = Depends(get_db)):
    rows = await results_repo.review_queue(s)
    return [
        ReviewItem(
            result_id=str(r.id),
            email_id=r.email_id,
            status=r.status,
            review_reason=r.review_reason,
            evidence=r.evidence,
            error=r.error,
        )
        for r in rows
    ]


@router.post("/review/{result_id}", response_model=ReviewOutcome, dependencies=[Depends(require_reviewer)])
async def review_action(
    result_id: UUID,
    body: ReviewActionIn,
    s: AsyncSession = Depends(get_db),
):
    try:
        res = await review_service.apply_action(s, result_id, body)
    except review_service.ReviewConflict as e:
        raise HTTPException(409, str(e)) from e
    if res is None:
        raise HTTPException(404, "no such result")
    return ReviewOutcome(ok=True, status=res.status)
