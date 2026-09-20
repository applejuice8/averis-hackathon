import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.repositories.emails import latest_result_ids
from pipeline import run


def test_latest_results_are_selected_per_email():
    sql = str(latest_result_ids().compile(dialect=postgresql.dialect()))
    assert "DISTINCT ON (pipeline_results.email_id)" in sql
    assert "created_at DESC" in sql


@pytest.mark.asyncio
async def test_run_publishes_progress_and_survives_bad_email(monkeypatch):
    row = SimpleNamespace(id=uuid.uuid4(), stats=None)
    session = AsyncMock()
    session.__aenter__.return_value = session
    monkeypatch.setattr(run, "SessionLocal", lambda: session)
    monkeypatch.setattr(run.runs_repo, "get", AsyncMock(return_value=row))
    finish = AsyncMock()
    monkeypatch.setattr(run.runs_repo, "finish", finish)
    monkeypatch.setattr(run.results_repo, "email_ids_for_run", AsyncMock(return_value=set()))
    emails = [SimpleNamespace(email_id=f"email_{i}", sender="ops", subject="Check BL",
                              body="", attachments=[]) for i in range(2)]
    monkeypatch.setattr(run.emails_repo, "list_all", AsyncMock(return_value=emails))
    monkeypatch.setattr(run, "process_email", MagicMock(side_effect=[
        {"email_id": "email_0", "status": "OK"}, ValueError("bad file")]))
    add = AsyncMock()
    monkeypatch.setattr(run.results_repo, "add", add)
    monkeypatch.setattr(run.results_repo, "stats_by_category_status",
                        AsyncMock(return_value={"GENERAL:OK": 1, "GENERAL:FAILED": 1}))
    assert await run.run_pipeline(run_id=str(row.id)) == str(row.id)
    assert add.await_args_list[1].args[2]["status"] == "FAILED"
    assert session.commit.await_count == 4  # start, each result, finish
    finish.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_resumes_without_duplicating_results(monkeypatch):
    row = SimpleNamespace(id=uuid.uuid4(), stats=None)
    session = AsyncMock()
    session.__aenter__.return_value = session
    monkeypatch.setattr(run, "SessionLocal", lambda: session)
    monkeypatch.setattr(run.runs_repo, "get", AsyncMock(return_value=row))
    monkeypatch.setattr(run.runs_repo, "finish", AsyncMock())
    monkeypatch.setattr(run.results_repo, "email_ids_for_run", AsyncMock(return_value={"email_0"}))
    emails = [SimpleNamespace(email_id=f"email_{i}", sender="ops", subject="Check BL",
                              body="", attachments=[]) for i in range(2)]
    monkeypatch.setattr(run.emails_repo, "list_all", AsyncMock(return_value=emails))
    process = MagicMock(return_value={"email_id": "email_1", "status": "OK"})
    monkeypatch.setattr(run, "process_email", process)
    add = AsyncMock()
    monkeypatch.setattr(run.results_repo, "add", add)
    monkeypatch.setattr(run.results_repo, "stats_by_category_status", AsyncMock(return_value={}))

    await run.run_pipeline(run_id=str(row.id))

    assert process.call_count == 1
    assert process.call_args.args[0]["email_id"] == "email_1"
    add.assert_awaited_once()


def test_a_crash_becomes_a_visible_failed_result():
    from pipeline.verdict import failed_result

    r = failed_result("email_9", ValueError("bad pdf"))
    assert (r["status"], r["error"], r["defect_fields"]) == ("FAILED", "ValueError: bad pdf", [])
