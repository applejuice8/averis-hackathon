from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import settings
from ...repositories import emails as emails_repo
from ...repositories import results as results_repo
from ...schemas.emails import EmailDetail, EmailListItem, ProcessOutcome, ResultDetail
from ...services.processing import AlreadyProcessing, process_one
from ..deps import get_db, require_reviewer

router = APIRouter()


@router.get("/emails", response_model=list[EmailListItem])
async def list_emails(
    queue: str | None = Query(default=None),
    status: str | None = Query(default=None),
    q: str | None = Query(default=None),
    s: AsyncSession = Depends(get_db),
):
    rows = await emails_repo.list_with_latest_results(s, queue=queue, status=status, q=q)
    return [EmailListItem.from_row(e, r) for e, r in rows]


@router.get("/emails/{email_id}", response_model=EmailDetail)
async def get_email(email_id: str, s: AsyncSession = Depends(get_db)):
    email = await emails_repo.get_by_id(s, email_id)
    if email is None:
        raise HTTPException(404, f"no such email: {email_id}")
    res = await results_repo.latest_for_email(s, email_id)
    return EmailDetail(
        email_id=email.email_id,
        sender=email.sender,
        subject=email.subject,
        body=email.body,
        attachments=email.attachments or [],
        result=ResultDetail.from_orm_row(res) if res else None,
    )


@router.get("/emails/{email_id}/attachments/{index}")
async def attachment_preview(email_id: str, index: int, s: AsyncSession = Depends(get_db)):
    from starlette.concurrency import run_in_threadpool

    from ...services.attachments import preview_attachment

    email = await emails_repo.get_by_id(s, email_id)
    if email is None:
        raise HTTPException(404, "No such email")
    return await run_in_threadpool(
        preview_attachment, settings.resolved_data_dir, email.attachments or [], index
    )


@router.post("/emails/{email_id}/reprocess", response_model=ProcessOutcome,
             dependencies=[Depends(require_reviewer)])
async def reprocess_email(email_id: str, s: AsyncSession = Depends(get_db)):
    """Retry one email; the new result becomes the latest everywhere."""
    email = await emails_repo.get_by_id(s, email_id)
    if email is None:
        raise HTTPException(404, f"no such email: {email_id}")
    try:
        result = await process_one(s, emails_repo.to_record(email), settings.resolved_data_dir)
    except AlreadyProcessing as e:
        raise HTTPException(409, "This email is already being processed. Wait for it to finish.") from e
    return ProcessOutcome(email_id=email_id, status=result["status"], category=result["category"])
