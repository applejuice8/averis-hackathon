"""Batch runner: process emails through the pipeline and persist results.

    uv run python -m pipeline.run                 # all emails
    uv run python -m pipeline.run email_004 ...   # subset
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core.config import settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.repositories import emails as emails_repo  # noqa: E402
from app.repositories import results as results_repo  # noqa: E402
from app.repositories import runs as runs_repo  # noqa: E402

from .verdict import process_email  # noqa: E402


async def run_pipeline(email_ids: list[str] | None = None, label: str | None = None,
                       run_id: str | None = None) -> str:
    async with SessionLocal() as s:
        run = await runs_repo.get(s, run_id) if run_id else await runs_repo.create(s, label or "manual")
        await s.commit()
        emails = await emails_repo.list_all(s, email_ids)

        for email in emails:
            rec = {
                "email_id": email.email_id,
                "from": email.sender,
                "subject": email.subject,
                "body": email.body,
                "attachments": email.attachments,
            }
            try:
                r = await asyncio.to_thread(process_email, rec, settings.data_dir_for(email.email_id))
            except Exception as e:
                r = {
                    "email_id": email.email_id, "category": "GENERAL",
                    "decided_by": "rule", "status": "FAILED", "review_reason": None,
                    "has_defect": False, "defect_fields": [], "si_fields": None,
                    "bl_fields": None, "doc_types": None,
                    "evidence": None, "error": f"{type(e).__name__}: {e}",
                }
            await results_repo.add(s, run.id, r)
            await s.flush()
            run.stats = await results_repo.stats_by_category_status(s, run.id)
            await s.commit()

        stats = await results_repo.stats_by_category_status(s, run.id)
        await runs_repo.finish(s, run, stats)
        await s.commit()
    return str(run.id)


if __name__ == "__main__":
    ids = [a for a in sys.argv[1:] if a.startswith("email_")]
    rid = asyncio.run(run_pipeline(email_ids=ids or None))
    print(f"run {rid} complete")
