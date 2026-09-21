"""Where pipeline runs execute: in-process locally, a Cloud Run Job in the cloud."""
import json
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import main  # noqa: E402
from app.api.deps import get_db  # noqa: E402
from app.api.routes import pipeline as pipeline_routes  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.services import executor  # noqa: E402


@pytest.fixture
def cloud(monkeypatch):
    monkeypatch.setattr(settings, "run_executor", "cloudrun-job")
    monkeypatch.setattr(settings, "gcp_project_id", "sdoc-verifier-abc123")
    monkeypatch.setattr(settings, "gcp_region", "asia-southeast1")
    monkeypatch.setattr(settings, "worker_job", "sdoc-worker")


def _metadata_then(run_response):
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.host == "metadata.google.internal":
            return httpx.Response(200, json={"access_token": "ya29.test"})
        return run_response

    return calls, httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_inline_runs_in_a_background_task():
    background = MagicMock()
    await executor.start_run("run-1", ["email_004"], background)

    background.add_task.assert_called_once()
    assert background.add_task.call_args.kwargs == {"email_ids": ["email_004"], "run_id": "run-1"}


@pytest.mark.asyncio
async def test_cloud_hands_the_run_to_the_worker_job(cloud, monkeypatch):
    trigger = AsyncMock()
    monkeypatch.setattr(executor, "trigger_worker_job", trigger)
    background = MagicMock()

    await executor.start_run("run-1", None, background)

    trigger.assert_awaited_once_with("run-1", None)
    background.add_task.assert_not_called()


@pytest.mark.asyncio
async def test_unknown_executor_is_an_error(monkeypatch):
    monkeypatch.setattr(settings, "run_executor", "carrier-pigeon")
    with pytest.raises(executor.ExecutorError, match="carrier-pigeon"):
        await executor.start_run("run-1", None, MagicMock())


@pytest.mark.asyncio
async def test_job_request_shape(cloud):
    calls, transport = _metadata_then(httpx.Response(200, json={"name": "operations/1"}))
    await executor.trigger_worker_job("run-1", ["email_004"], transport=transport)

    run_call = calls[-1]
    assert run_call.method == "POST"
    assert str(run_call.url) == ("https://run.googleapis.com/v2/projects/sdoc-verifier-abc123"
                                 "/locations/asia-southeast1/jobs/sdoc-worker:run")
    assert run_call.headers["Authorization"] == "Bearer ya29.test"
    assert json.loads(run_call.content) == {"overrides": {"containerOverrides": [
        {"args": ["-m", "pipeline.worker", "run", "--run-id", "run-1", "email_004"]}]}}


@pytest.mark.asyncio
async def test_job_refusal_becomes_an_executor_error(cloud):
    _, transport = _metadata_then(httpx.Response(403, json={"error": "denied"}))
    with pytest.raises(executor.ExecutorError, match="403"):
        await executor.trigger_worker_job("run-1", None, transport=transport)


@pytest.mark.asyncio
async def test_unreachable_metadata_becomes_an_executor_error(cloud):
    def boom(request):
        raise httpx.ConnectError("no metadata server here")

    with pytest.raises(executor.ExecutorError, match="unreachable"):
        await executor.trigger_worker_job("run-1", None, transport=httpx.MockTransport(boom))


@pytest.mark.asyncio
async def test_missing_cloud_settings_are_reported(monkeypatch):
    monkeypatch.setattr(settings, "gcp_project_id", "")
    with pytest.raises(executor.ExecutorError, match="GCP_PROJECT_ID"):
        await executor.trigger_worker_job("run-1", None)


def test_failed_hand_off_deletes_the_run_and_returns_502(monkeypatch):
    session = SimpleNamespace(commit=AsyncMock())

    async def fake_db():
        yield session

    main.app.dependency_overrides[get_db] = fake_db
    try:
        run_id = uuid.uuid4()
        monkeypatch.setattr(pipeline_routes.runs_repo, "count_active", AsyncMock(return_value=0))
        monkeypatch.setattr(pipeline_routes.runs_repo, "count_started_since", AsyncMock(return_value=0))
        monkeypatch.setattr(pipeline_routes.runs_repo, "create", AsyncMock(return_value=SimpleNamespace(id=run_id)))
        delete = AsyncMock()
        monkeypatch.setattr(pipeline_routes.runs_repo, "delete", delete)
        monkeypatch.setattr(pipeline_routes.executor, "start_run",
                            AsyncMock(side_effect=executor.ExecutorError("worker job refused the run (403)")))

        r = TestClient(main.app).post("/api/pipeline/run")

        assert r.status_code == 502
        assert "403" in r.json()["detail"]
        delete.assert_awaited_once_with(session, run_id)
    finally:
        main.app.dependency_overrides.clear()


def test_a_second_concurrent_run_is_refused(monkeypatch):
    session = SimpleNamespace(commit=AsyncMock())

    async def fake_db():
        yield session

    main.app.dependency_overrides[get_db] = fake_db
    try:
        monkeypatch.setattr(pipeline_routes.runs_repo, "count_active", AsyncMock(return_value=1))
        create = AsyncMock()
        monkeypatch.setattr(pipeline_routes.runs_repo, "create", create)

        r = TestClient(main.app).post("/api/pipeline/run")

        assert r.status_code == 409
        create.assert_not_awaited()
    finally:
        main.app.dependency_overrides.clear()


def test_the_daily_run_allowance_is_enforced(monkeypatch):
    session = SimpleNamespace(commit=AsyncMock())

    async def fake_db():
        yield session

    main.app.dependency_overrides[get_db] = fake_db
    try:
        monkeypatch.setattr(pipeline_routes.runs_repo, "count_active", AsyncMock(return_value=0))
        monkeypatch.setattr(pipeline_routes.runs_repo, "count_started_since", AsyncMock(return_value=20))
        create = AsyncMock()
        monkeypatch.setattr(pipeline_routes.runs_repo, "create", create)

        r = TestClient(main.app).post("/api/pipeline/run")

        assert r.status_code == 429
        create.assert_not_awaited()
    finally:
        main.app.dependency_overrides.clear()
