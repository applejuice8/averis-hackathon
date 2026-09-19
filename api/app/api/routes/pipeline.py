import sys
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from pipeline.run import run_pipeline  # noqa: E402
from pipeline.submission import build_submission, submit  # noqa: E402
from pipeline.verdict import llm_assist  # noqa: E402

from ...core.config import settings  # noqa: E402
from ...repositories import emails as emails_repo  # noqa: E402
from ...repositories import results as results_repo  # noqa: E402
from ...repositories import runs as runs_repo  # noqa: E402
from ...schemas.runs import RunDetail, RunStarted, RunView  # noqa: E402
from ..deps import get_db  # noqa: E402

router = APIRouter()


@router.post("/pipeline/run", response_model=RunStarted)
async def start_run(
    background: BackgroundTasks,
    email_ids: list[str] | None = None,
    label: str | None = None,
    s: AsyncSession = Depends(get_db),
):
    run = await runs_repo.create(s, label or "manual")
    await s.commit()
    background.add_task(run_pipeline, email_ids=email_ids, label=label, run_id=str(run.id))
    return RunStarted(run_id=str(run.id), started=True, email_ids=email_ids or "all")


@router.get("/runs", response_model=list[RunView])
async def list_runs(s: AsyncSession = Depends(get_db)):
    return [RunView.from_orm_row(r) for r in await runs_repo.list_recent(s)]


@router.get("/runs/{run_id}", response_model=RunDetail)
async def get_run(run_id: uuid.UUID, s: AsyncSession = Depends(get_db)):
    run = await runs_repo.get(s, run_id)
    if run is None:
        raise HTTPException(404, "no such run")
    n = await results_repo.count_for_run(s, run_id)
    detail = RunDetail(**RunView.from_orm_row(run).model_dump(), results=n)
    return detail


@router.get("/export/submission")
async def export_submission(run_id: str):
    try:
        sub = await build_submission(run_id)
    except Exception as e:
        raise HTTPException(400, str(e))
    return JSONResponse(sub)


@router.post("/export/submit")
async def submit_run(run_id: str):
    try:
        return await submit(run_id)
    except Exception as e:
        raise HTTPException(400, str(e))


@router.get("/pipeline/llm-assist/{email_id}")
async def llm_assist_email(email_id: str, s: AsyncSession = Depends(get_db)):
    """On-demand AI view of an email (classification + extraction/OCR).
    Demo endpoint — results are returned, never persisted."""
    email = await emails_repo.get_by_id(s, email_id)
    if email is None:
        raise HTTPException(404, "no such email")
    rec = {
        "email_id": email.email_id,
        "from": email.sender,
        "subject": email.subject,
        "body": email.body,
        "attachments": email.attachments,
    }
    from starlette.concurrency import run_in_threadpool

    return await run_in_threadpool(llm_assist, rec, settings.resolved_data_dir)
