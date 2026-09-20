import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from pipeline.submission import build_submission, submit  # noqa: E402
from pipeline.verdict import llm_assist  # noqa: E402

from ...core.config import settings  # noqa: E402
from ...repositories import emails as emails_repo  # noqa: E402
from ...repositories import results as results_repo  # noqa: E402
from ...repositories import runs as runs_repo  # noqa: E402
from ...schemas.runs import RunDetail, RunStarted, RunView  # noqa: E402
from ...services import executor  # noqa: E402
from ..deps import get_db, require_reviewer  # noqa: E402

router = APIRouter()


@router.post("/pipeline/run", response_model=RunStarted, dependencies=[Depends(require_reviewer)])
async def start_run(
    background: BackgroundTasks,
    email_ids: list[str] | None = None,
    label: str | None = None,
    s: AsyncSession = Depends(get_db),
):
    if await runs_repo.count_active(s) >= settings.max_active_runs:
        raise HTTPException(409, "A run is already in progress. Wait for it to finish before starting another.")
    since = datetime.now(UTC) - timedelta(days=1)
    if await runs_repo.count_started_since(s, since) >= settings.max_runs_per_day:
        raise HTTPException(429, "The daily run allowance is used up. Try again tomorrow.")
    run = await runs_repo.create(s, label or "manual")
    await s.commit()
    try:
        await executor.start_run(str(run.id), email_ids, background)
    except executor.ExecutorError as e:
        # no orphan "running forever" rows when the hand-off fails
        await runs_repo.delete(s, run.id)
        await s.commit()
        raise HTTPException(502, f"Could not start the run: {e}") from e
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
        raise HTTPException(400, str(e)) from e
    return JSONResponse(sub)


@router.post("/export/submit", dependencies=[Depends(require_reviewer)])
async def submit_run(run_id: str):
    try:
        return await submit(run_id)
    except Exception as e:
        raise HTTPException(400, str(e)) from e


@router.post("/pipeline/llm-assist/{email_id}", dependencies=[Depends(require_reviewer)])
async def llm_assist_email(email_id: str, s: AsyncSession = Depends(get_db)):
    """On-demand AI view of an email (classification + extraction/OCR).
    Demo endpoint — results are returned, never persisted."""
    email = await emails_repo.get_by_id(s, email_id)
    if email is None:
        raise HTTPException(404, "no such email")
    rec = emails_repo.to_record(email)
    from starlette.concurrency import run_in_threadpool

    return await run_in_threadpool(llm_assist, rec, settings.data_dir_for(email.email_id))
