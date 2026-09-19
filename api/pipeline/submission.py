"""Build submission.json from a run's results and POST it to the scorer.

    uv run python -m pipeline.submission <run_id> [--submit]
"""
import asyncio
import json
import sys
from pathlib import Path

import httpx
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import SCORER_URL  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import Email, PipelineResult, Run  # noqa: E402

from .verdict import to_submission_entry  # noqa: E402


async def build_submission(run_id: str) -> dict:
    async with SessionLocal() as s:
        rows = (
            await s.execute(
                select(PipelineResult, Email)
                .join(Email, Email.email_id == PipelineResult.email_id)
                .where(PipelineResult.run_id == run_id)
            )
        ).all()
        sub = {}
        for res, _email in rows:
            e = to_submission_entry(
                {c.name: getattr(res, c.name) for c in PipelineResult.__table__.columns}
            )
            sub[res.email_id] = e
        return sub


async def submit(run_id: str) -> dict:
    sub = await build_submission(run_id)
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(f"{SCORER_URL}/submit", json=sub)
        r.raise_for_status()
        scoreboard = r.json()
    async with SessionLocal() as s:
        run = await s.get(Run, run_id)
        if run:
            run.score = scoreboard
            await s.commit()
    return scoreboard


if __name__ == "__main__":
    rid = sys.argv[1]
    if "--submit" in sys.argv:
        print(json.dumps(asyncio.run(submit(rid)), indent=2))
    else:
        out = asyncio.run(build_submission(rid))
        json.dump(out, open("submission.json", "w"), indent=2)
        print(f"wrote submission.json ({len(out)} entries)")
