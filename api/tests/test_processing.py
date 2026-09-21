"""One-off processing (uploads, retries): results always land, failures show."""
import asyncio
import sys
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import main  # noqa: E402
from app.api.deps import get_db  # noqa: E402
from app.api.routes import emails as emails_routes  # noqa: E402
from app.services import processing  # noqa: E402

RECORD = {"email_id": "upload_20260920_a1b2c3", "from": "ops@example.com",
          "subject": "Check", "body": "", "attachments": []}


@pytest.fixture
def adhoc(monkeypatch):
    run = SimpleNamespace(id=uuid.uuid4(), stats=None)
    get_or_create = AsyncMock(return_value=run)
    monkeypatch.setattr(processing.runs_repo, "get_or_create", get_or_create)
    add = AsyncMock()
    monkeypatch.setattr(processing.results_repo, "add", add)
    monkeypatch.setattr(processing.results_repo, "stats_by_category_status",
                        AsyncMock(return_value={"BL_COMPARISON:OK": 1}))
    session = SimpleNamespace(commit=AsyncMock(), flush=AsyncMock())
    return SimpleNamespace(run=run, add=add, session=session, get_or_create=get_or_create)


@pytest.mark.asyncio
async def test_result_lands_in_the_uploads_run(monkeypatch, adhoc):
    monkeypatch.setattr(processing, "process_email", MagicMock(
        return_value={"email_id": RECORD["email_id"], "status": "OK", "category": "BL_COMPARISON"}))

    out = await processing.process_one(adhoc.session, RECORD, "/data")

    assert out["status"] == "OK"
    adhoc.get_or_create.assert_awaited_once_with(adhoc.session, "Uploads & retries")
    adhoc.add.assert_awaited_once_with(adhoc.session, adhoc.run.id, out)
    assert adhoc.run.stats == {"BL_COMPARISON:OK": 1}
    adhoc.session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_crash_is_stored_as_failed(monkeypatch, adhoc):
    monkeypatch.setattr(processing, "process_email", MagicMock(side_effect=ValueError("bad pdf")))

    out = await processing.process_one(adhoc.session, RECORD, "/data")

    assert (out["status"], out["error"]) == ("FAILED", "ValueError: bad pdf")
    adhoc.add.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_slow_email_times_out_as_failed(monkeypatch, adhoc):
    monkeypatch.setattr(processing, "PROCESS_TIMEOUT_S", 0.05)
    monkeypatch.setattr(processing, "process_email", lambda *args: time.sleep(0.3))

    out = await processing.process_one(adhoc.session, RECORD, "/data")

    assert out["status"] == "FAILED"
    assert out["error"].startswith("TimeoutError: processing exceeded")


@pytest.mark.asyncio
async def test_a_second_attempt_while_one_is_running_is_refused(monkeypatch, adhoc):
    started = asyncio.Event()
    release = asyncio.Event()

    def slow(*args):
        asyncio.run_coroutine_threadsafe(_set(started), loop).result()
        asyncio.run_coroutine_threadsafe(_wait(release), loop).result()
        return {"email_id": RECORD["email_id"], "status": "OK", "category": "BL_COMPARISON"}

    async def _set(event):
        event.set()

    async def _wait(event):
        await event.wait()

    loop = asyncio.get_running_loop()
    monkeypatch.setattr(processing, "process_email", slow)
    first = asyncio.create_task(processing.process_one(adhoc.session, RECORD, "/data"))
    await started.wait()

    with pytest.raises(processing.AlreadyProcessing):
        await processing.process_one(adhoc.session, RECORD, "/data")

    release.set()
    assert (await first)["status"] == "OK"


@pytest.mark.asyncio
async def test_the_guard_is_released_after_a_failure(monkeypatch, adhoc):
    monkeypatch.setattr(processing, "process_email", MagicMock(side_effect=ValueError("bad pdf")))

    assert (await processing.process_one(adhoc.session, RECORD, "/data"))["status"] == "FAILED"
    assert (await processing.process_one(adhoc.session, RECORD, "/data"))["status"] == "FAILED"
    assert RECORD["email_id"] not in processing._in_flight


@pytest.fixture
def api(monkeypatch):
    session = SimpleNamespace(commit=AsyncMock())

    async def fake_db():
        yield session

    main.app.dependency_overrides[get_db] = fake_db
    yield SimpleNamespace(client=TestClient(main.app), session=session)
    main.app.dependency_overrides.clear()


def test_reprocess_unknown_email_is_404(api, monkeypatch):
    monkeypatch.setattr(emails_routes.emails_repo, "get_by_id", AsyncMock(return_value=None))
    assert api.client.post("/api/emails/email_999/reprocess").status_code == 404


def test_reprocess_returns_the_new_verdict(api, monkeypatch):
    email = SimpleNamespace(email_id="email_004", sender="ops", subject="Check", body="", attachments=[])
    monkeypatch.setattr(emails_routes.emails_repo, "get_by_id", AsyncMock(return_value=email))
    process = AsyncMock(return_value={"status": "MISMATCH", "category": "BL_COMPARISON"})
    monkeypatch.setattr(emails_routes, "process_one", process)

    r = api.client.post("/api/emails/email_004/reprocess")

    assert r.status_code == 200
    assert r.json() == {"email_id": "email_004", "status": "MISMATCH", "category": "BL_COMPARISON"}
    assert process.await_args.args[1]["email_id"] == "email_004"


def test_reprocess_while_an_attempt_is_running_is_409(api, monkeypatch):
    email = SimpleNamespace(email_id="email_004", sender="ops", subject="Check", body="", attachments=[])
    monkeypatch.setattr(emails_routes.emails_repo, "get_by_id", AsyncMock(return_value=email))
    monkeypatch.setattr(emails_routes, "process_one",
                        AsyncMock(side_effect=emails_routes.AlreadyProcessing("email_004")))

    assert api.client.post("/api/emails/email_004/reprocess").status_code == 409
