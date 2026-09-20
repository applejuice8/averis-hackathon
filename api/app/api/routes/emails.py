import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from ...repositories import emails as emails_repo
from ...repositories import results as results_repo
from ...schemas.emails import (
    EmailCreate,
    EmailCreated,
    EmailDetail,
    EmailListItem,
    ResultDetail,
)
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


@router.post("/emails", response_model=EmailCreated, status_code=201)
async def create_email(
    sender: Annotated[str, Form()] = "",
    subject: Annotated[str, Form()] = "",
    body: Annotated[str, Form()] = "",
    files: Annotated[list[UploadFile] | None, File()] = None,
    s: AsyncSession = Depends(get_db),
):
    """Manual intake — a hand-entered email plus any documents the user
    attaches directly. Ids are always assigned (`manual_*`) so an upload can
    never overwrite a bundle record; files persist in the writable upload dir
    and the email is picked up by the next pipeline run."""
    try:
        EmailCreate(sender=sender, subject=subject, body=body)
    except ValidationError as e:
        raise HTTPException(422, "sender, subject or body must be non-empty") from e

    from ...core.config import settings
    from ...services.attachments import save_attachments

    email_id = f"manual_{uuid.uuid4().hex[:10]}"
    uploads = [(f.filename or "file", await f.read()) for f in files or [] if f.filename]
    attachments = save_attachments(settings.resolved_upload_data_dir, email_id, uploads)
    await emails_repo.upsert_many(s, [{
        "email_id": email_id,
        "from": sender.strip(),
        "subject": subject.strip(),
        "body": body,
        "attachments": attachments,
    }])
    return EmailCreated(email_id=email_id)


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

    from ...core.config import settings
    from ...services.attachments import preview_attachment

    email = await emails_repo.get_by_id(s, email_id)
    if email is None:
        raise HTTPException(404, "No such email")
    return await run_in_threadpool(
        preview_attachment, settings.data_dir_for(email_id), email.attachments or [], index
    )
