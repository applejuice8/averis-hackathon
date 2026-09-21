"""Batch runner: process emails through the pipeline and persist results.

Resumable: emails that already have a result in the run are skipped, so a
retried worker execution never duplicates rows.

    uv run python -m pipeline.run                 # all dataset emails
    uv run python -m pipeline.run email_004 ...   # subset
"""
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core.config import settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.repositories import emails as emails_repo  # noqa: E402
from app.repositories import results as results_repo  # noqa: E402
from app.repositories import runs as runs_repo  # noqa: E402

from .verdict import failed_result, process_email  # noqa: E402

log = logging.getLogger("sdoc.pipeline")


async def run_pipeline(email_ids: list[str] | None = None, label: str | None = None,
                       run_id: str | None = None) -> str:
    async with SessionLocal() as s:
        run = await runs_repo.get(s, run_id) if run_id else await runs_repo.create(s, label or "manual")
        await s.commit()
        done = await results_repo.email_ids_for_run(s, run.id)
        emails = await emails_repo.list_all(s, email_ids)

        for email in emails:
            if email.email_id in done:
                continue
            rec = emails_repo.to_record(email)
            try:
                r = await asyncio.to_thread(process_email, rec, settings.data_dir_for(email.email_id))
            except Exception as e:
                r = failed_result(email.email_id, e)
            await results_repo.add(s, run.id, r)
            await s.flush()
            run.stats = await results_repo.stats_by_category_status(s, run.id)
            await s.commit()
            log.info("processed %s -> %s", email.email_id, r["status"],
                     extra={"run_id": str(run.id), "email_id": email.email_id})

        stats = await results_repo.stats_by_category_status(s, run.id)
        await runs_repo.finish(s, run, stats)
        await s.commit()
    return str(run.id)


if __name__ == "__main__":
    ids = [a for a in sys.argv[1:] if a.startswith("email_")]
    rid = asyncio.run(run_pipeline(email_ids=ids or None))
    print(f"run {rid} complete")
