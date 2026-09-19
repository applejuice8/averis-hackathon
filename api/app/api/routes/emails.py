from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...repositories import emails as emails_repo
from ...repositories import results as results_repo
from ...schemas.emails import EmailDetail, EmailListItem, ResultDetail
from ..deps import get_db

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
