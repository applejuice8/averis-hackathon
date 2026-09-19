"""Batch runner: process emails through the pipeline and persist results.

    uv run python -m pipeline.run                 # all emails
    uv run python -m pipeline.run email_004 ...   # subset
"""
import asyncio
import sys
from collections import Counter
from pathlib import Path

from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import DATA_DIR  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import Email, PipelineResult, Run  # noqa: E402

from .verdict import process_email  # noqa: E402


async def run_pipeline(email_ids: list[str] | None = None, label: str | None = None) -> str:
    async with SessionLocal() as s:
        run = Run(label=label or "manual")
        s.add(run)
        await s.flush()
        run_id = str(run.id)

        stmt = select(Email).order_by(Email.email_id)
        if email_ids:
            stmt = stmt.where(Email.email_id.in_(email_ids))
        emails = (await s.execute(stmt)).scalars().all()

        for email in emails:
            rec = {
                "email_id": email.email_id,
                "from": email.sender,
                "subject": email.subject,
                "body": email.body,
                "attachments": email.attachments,
            }
            try:
                r = process_email(rec, DATA_DIR)
            except Exception as e:
                r = {
                    "email_id": email.email_id, "category": "GENERAL",
                    "decided_by": "rule", "status": "FAILED", "review_reason": None,
                    "has_defect": False, "defect_fields": [], "si_fields": None,
                    "bl_fields": None, "doc_types": None,
                    "evidence": None, "error": f"{type(e).__name__}: {e}",
                }
            s.add(PipelineResult(run_id=run.id, **r))

        cats = Counter()
        stats_q = await s.execute(
            select(PipelineResult.category, PipelineResult.status, func.count())
            .where(PipelineResult.run_id == run.id)
            .group_by(PipelineResult.category, PipelineResult.status)
        )
        for cat, status, n in stats_q:
            cats[f"{cat}:{status}"] = n
        run.stats = dict(cats)
        run.finished_at = func.now()
        await s.commit()
    return run_id


if __name__ == "__main__":
    ids = [a for a in sys.argv[1:] if a.startswith("email_")]
    rid = asyncio.run(run_pipeline(email_ids=ids or None))
    print(f"run {rid} complete")
