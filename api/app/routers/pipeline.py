import json
import sys
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline.run import run_pipeline  # noqa: E402
from pipeline.submission import build_submission, submit  # noqa: E402

from ..db import SessionLocal  # noqa: E402
from ..models import PipelineResult, Run  # noqa: E402

router = APIRouter(prefix="/api")


async def get_session():
    async with SessionLocal() as s:
        yield s


@router.post("/pipeline/run")
async def start_run(
    background: BackgroundTasks,
    email_ids: list[str] | None = None,
    label: str | None = None,
):
    async def _run():
        await run_pipeline(email_ids=email_ids, label=label)

    background.add_task(_run)
    return {"started": True, "email_ids": email_ids or "all"}


@router.get("/runs")
async def list_runs(s: AsyncSession = Depends(get_session)):
    runs = (
        await s.execute(select(Run).order_by(desc(Run.started_at)).limit(50))
    ).scalars().all()
    return [
        {
            "id": str(r.id),
            "label": r.label,
            "started_at": r.started_at,
            "finished_at": r.finished_at,
            "stats": r.stats,
            "score": r.score,
        }
        for r in runs
    ]


@router.get("/runs/{run_id}")
async def get_run(run_id: str, s: AsyncSession = Depends(get_session)):
    run = await s.get(Run, uuid.UUID(run_id))
    if not run:
        raise HTTPException(404, "no such run")
    n = (
        await s.execute(
            select(PipelineResult.status)
            .where(PipelineResult.run_id == run.id)
        )
    ).scalars().all()
    return {
        "id": str(run.id),
        "label": run.label,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "stats": run.stats,
        "score": run.score,
        "results": len(n),
    }


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
