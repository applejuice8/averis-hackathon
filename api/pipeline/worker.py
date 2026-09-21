"""Cloud Run Job entrypoint for batch pipeline work.

    python -m pipeline.worker run --run-id <uuid> [email_id ...]
    python -m pipeline.worker seed [--reset]

`run` finishes a run the api created (the api hands it over instead of
running it in-process). `seed` loads the dataset, runs every email and scores
the run; `--reset` first removes uploaded emails, their files and reviews.
"""
import argparse
import asyncio
import logging
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core.config import settings  # noqa: E402
from app.core.logging import configure_logging  # noqa: E402
from app.db.session import SessionLocal, init_db  # noqa: E402
from app.repositories import emails as emails_repo  # noqa: E402
from app.repositories import runs as runs_repo  # noqa: E402

from .ingest import ingest  # noqa: E402
from .run import run_pipeline  # noqa: E402
from .submission import submit  # noqa: E402

log = logging.getLogger("sdoc.worker")


async def mark_failed(run_id: str, error: BaseException) -> None:
    async with SessionLocal() as s:
        run = await runs_repo.get(s, run_id)
        if run is not None and run.finished_at is None:
            await runs_repo.fail(s, run, f"{type(error).__name__}: {error}")
            await s.commit()


async def score_run(run_id: str) -> None:
    """Benchmark scoring for a full dataset run. A subset run covers only part
    of the inbox, and uploads never enter a batch run, so neither is scored."""
    try:
        board = await submit(run_id)
        log.info("scored run: final_score=%s", board.get("final_score"), extra={"run_id": run_id})
    except Exception:
        # scoring is evaluation, not processing: a missing scorer never fails a run
        log.warning("scoring skipped", exc_info=True, extra={"run_id": run_id})


async def run_command(run_id: str, email_ids: list[str]) -> str:
    try:
        finished = await run_pipeline(run_id=run_id, email_ids=email_ids or None)
    except Exception as e:
        log.exception("run failed", extra={"run_id": run_id})
        await mark_failed(run_id, e)
        raise
    if not email_ids:
        await score_run(run_id)
    return finished


def remove_upload_files(uploads_root: Path, email_ids: list[str]) -> None:
    """Delete each upload folder; ids that would escape the root are ignored."""
    root = uploads_root.resolve()
    for email_id in email_ids:
        target = (root / email_id).resolve()
        if target.parent == root:
            shutil.rmtree(target, ignore_errors=True)


async def reset_uploads() -> list[str]:
    async with SessionLocal() as s:
        ids = await emails_repo.delete_uploads(s)
        await s.commit()
    remove_upload_files(settings.uploads_root, ids)
    log.info("reset removed %d uploaded emails", len(ids))
    return ids


async def seed(reset: bool) -> str:
    await init_db()
    if reset:
        await reset_uploads()
    count = await ingest()
    log.info("ingested %d dataset emails", count)
    async with SessionLocal() as s:
        run = await runs_repo.create(s, "seed")
        await s.commit()
        run_id = str(run.id)
    await run_command(run_id, [])
    return run_id


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m pipeline.worker")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="finish a run created by the api")
    run.add_argument("--run-id", required=True)
    run.add_argument("email_ids", nargs="*")
    seed_cmd = sub.add_parser("seed", help="ingest the dataset, run everything, score")
    seed_cmd.add_argument("--reset", action="store_true", help="remove uploaded emails first")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    configure_logging(settings.log_format, settings.gcp_project_id)
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.command == "run":
        asyncio.run(run_command(args.run_id, args.email_ids))
    else:
        asyncio.run(seed(args.reset))
    return 0


if __name__ == "__main__":
    sys.exit(main())
