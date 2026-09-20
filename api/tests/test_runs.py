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
