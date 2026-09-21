"""Where a pipeline run executes.

inline        FastAPI BackgroundTasks inside the api process (compose, dev).
cloudrun-job  One Cloud Run Job execution per run. On Cloud Run the api
              scales to zero and throttles CPU after responding, so a
              520-email run must not live inside it.
"""
import httpx
from fastapi import BackgroundTasks

from ..core.config import settings
from . import gcp

RUN_API = "https://run.googleapis.com/v2"
WORKER_ARGS = ["-m", "pipeline.worker"]


class ExecutorError(RuntimeError):
    """The run could not be handed to its executor."""


def job_run_url() -> str:
    return (f"{RUN_API}/projects/{settings.gcp_project_id}/locations/{settings.gcp_region}"
            f"/jobs/{settings.worker_job}:run")


def job_run_body(run_id: str, email_ids: list[str] | None) -> dict:
    args = [*WORKER_ARGS, "run", "--run-id", run_id, *(email_ids or [])]
    return {"overrides": {"containerOverrides": [{"args": args}]}}


async def trigger_worker_job(run_id: str, email_ids: list[str] | None,
                             transport: httpx.AsyncBaseTransport | None = None) -> None:
    if not (settings.gcp_project_id and settings.gcp_region and settings.worker_job):
        raise ExecutorError("GCP_PROJECT_ID, GCP_REGION and WORKER_JOB must be set for RUN_EXECUTOR=cloudrun-job")
    try:
        token = await gcp.access_token(transport)
        async with httpx.AsyncClient(transport=transport, timeout=20) as c:
            r = await c.post(job_run_url(), json=job_run_body(run_id, email_ids),
                             headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError as e:
        raise ExecutorError(f"worker job unreachable ({type(e).__name__})") from e
    if r.status_code >= 300:
        raise ExecutorError(f"worker job refused the run ({r.status_code})")


async def start_run(run_id: str, email_ids: list[str] | None, background: BackgroundTasks) -> None:
    if settings.run_executor == "inline":
        from pipeline.run import run_pipeline

        background.add_task(run_pipeline, email_ids=email_ids, run_id=run_id)
    elif settings.run_executor == "cloudrun-job":
        await trigger_worker_job(run_id, email_ids)
    else:
        raise ExecutorError(f"unknown RUN_EXECUTOR {settings.run_executor!r}")
