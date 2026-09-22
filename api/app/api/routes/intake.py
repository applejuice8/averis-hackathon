"""Live intake: a person submits an email + attachments and gets a verdict."""
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from ...core.config import settings
from ...repositories import emails as emails_repo
from ...schemas.emails import ProcessOutcome
from ...services import intake
from ...services.processing import process_one
from ..deps import get_db

router = APIRouter()


@router.post("/intake", status_code=201, response_model=ProcessOutcome)
async def create_intake(
    sender: str = Form(""),
    subject: str = Form(""),
    body: str = Form(""),
    files: list[UploadFile] | None = File(None),
    s: AsyncSession = Depends(get_db),
):
    uploads = files or []
    if len(uploads) > intake.MAX_FILES:
        raise HTTPException(422, f"Attach at most {intake.MAX_FILES} files.")
    raw = [(f.filename or "attachment", await f.read(intake.MAX_FILE_BYTES + 1)) for f in uploads]
    try:
        clean = intake.validate_submission(sender, subject, body, raw)
    except intake.IntakeError as e:
        raise HTTPException(422, str(e)) from e
    email_id = intake.new_email_id()
    paths = await run_in_threadpool(
        intake.save_files, Path(settings.resolved_data_dir), settings.uploads_subdir, email_id, clean
    )
    record = intake.build_record(email_id, sender.strip(), subject.strip(), body, paths)
    await emails_repo.create_upload(s, record)
    result = await process_one(s, record, settings.resolved_data_dir)
    return ProcessOutcome(email_id=email_id, status=result["status"], category=result["category"])
