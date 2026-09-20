"""One-off processing outside batch runs: live intake and reprocess.

Every attempt stores a result — a crash or timeout becomes a visible FAILED
row that a reviewer can retry, never a silent loss.
"""
import asyncio
import contextlib

from pipeline.verdict import failed_result, process_email
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from ..repositories import results as results_repo
from ..repositories import runs as runs_repo

ADHOC_RUN_LABEL = "Uploads & retries"
PROCESS_TIMEOUT_S = 90

_in_flight: dict[str, asyncio.Lock] = {}


class AlreadyProcessing(RuntimeError):
    """Another attempt for this email is still running."""


@contextlib.asynccontextmanager
async def _single_attempt(email_id: str):
    """One attempt per email at a time. A timeout abandons the wait but not the
    work, so a retry must not start a second paid attempt in parallel."""
    lock = _in_flight.setdefault(email_id, asyncio.Lock())
    if lock.locked():
        raise AlreadyProcessing(email_id)
    try:
        async with lock:
            yield
    finally:
        if not lock.locked():
            _in_flight.pop(email_id, None)


async def process_one(s: AsyncSession, record: dict, data_dir: str) -> dict:
    async with _single_attempt(record["email_id"]):
        try:
            result = await asyncio.wait_for(
                run_in_threadpool(process_email, record, data_dir), timeout=PROCESS_TIMEOUT_S
            )
        except TimeoutError:
            result = failed_result(
                record["email_id"],
                TimeoutError(f"processing exceeded {PROCESS_TIMEOUT_S} s and was abandoned"),
            )
        except Exception as e:
            result = failed_result(record["email_id"], e)
        run = await runs_repo.get_or_create(s, ADHOC_RUN_LABEL)
        await results_repo.add(s, run.id, result)
        await s.flush()
        run.stats = await results_repo.stats_by_category_status(s, run.id)
        await s.commit()
        return result
