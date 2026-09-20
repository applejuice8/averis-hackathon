"""Build submission.json from a run's results and POST it to the scorer.

    uv run python -m pipeline.submission <run_id> [--submit]
"""
import asyncio
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core.config import settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.repositories import results as results_repo  # noqa: E402
from app.repositories import runs as runs_repo  # noqa: E402
from app.services import gcp  # noqa: E402

from .verdict import to_submission_entry  # noqa: E402


async def build_submission(run_id: str) -> dict:
    async with SessionLocal() as s:
        rows = await results_repo.for_run(s, run_id)
        return {
            res.email_id: to_submission_entry(
                {c.name: getattr(res, c.name) for c in res.__table__.columns}
            )
            for res in rows
        }


async def scorer_headers() -> dict[str, str]:
    """Bearer ID token when the scorer is an IAM-private Cloud Run service."""
    if settings.scorer_auth != "gcp-id-token":
        return {}
    return {"Authorization": f"Bearer {await gcp.id_token(settings.scorer_url)}"}


async def submit(run_id: str) -> dict:
    sub = await build_submission(run_id)
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(f"{settings.scorer_url}/submit", json=sub, headers=await scorer_headers())
        r.raise_for_status()
        scoreboard = r.json()
    async with SessionLocal() as s:
        await runs_repo.save_score(s, run_id, scoreboard)
    return scoreboard


if __name__ == "__main__":
    rid = sys.argv[1]
    if "--submit" in sys.argv:
        print(json.dumps(asyncio.run(submit(rid)), indent=2))
    else:
        out = asyncio.run(build_submission(rid))
        with open("submission.json", "w") as f:
            json.dump(out, f, indent=2)
        print(f"wrote submission.json ({len(out)} entries)")
