"""Cloud Run Job entrypoint: run, seed, reset — without a database."""
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import settings  # noqa: E402
from pipeline import worker  # noqa: E402


def _session(monkeypatch):
    session = AsyncMock()
    session.__aenter__.return_value = session
    monkeypatch.setattr(worker, "SessionLocal", lambda: session)
    return session


def test_parse_run_and_seed_args():
    run = worker.parse_args(["run", "--run-id", "abc", "email_004", "email_005"])
    assert (run.command, run.run_id, run.email_ids) == ("run", "abc", ["email_004", "email_005"])
    seed = worker.parse_args(["seed", "--reset"])
    assert (seed.command, seed.reset) == ("seed", True)
    assert worker.parse_args(["seed"]).reset is False


@pytest.mark.asyncio
async def test_a_failed_run_is_marked_and_the_job_fails(monkeypatch):
    monkeypatch.setattr(worker, "run_pipeline", AsyncMock(side_effect=RuntimeError("db gone")))
    mark = AsyncMock()
    monkeypatch.setattr(worker, "mark_failed", mark)

    with pytest.raises(RuntimeError):
        await worker.run_command("rid", [])

    assert mark.await_args.args[0] == "rid"


@pytest.mark.asyncio
async def test_mark_failed_records_the_error(monkeypatch):
    session = _session(monkeypatch)
    row = SimpleNamespace(finished_at=None)
    monkeypatch.setattr(worker.runs_repo, "get", AsyncMock(return_value=row))
    fail = AsyncMock()
    monkeypatch.setattr(worker.runs_repo, "fail", fail)

    await worker.mark_failed("rid", RuntimeError("db gone"))

    fail.assert_awaited_once_with(session, row, "RuntimeError: db gone")
    session.commit.assert_awaited_once()


def test_upload_cleanup_never_leaves_the_uploads_folder(tmp_path):
    root = tmp_path / "uploads"
    (root / "upload_a").mkdir(parents=True)
    (root / "upload_a" / "si.txt").write_text("x")
    (root / "upload_keep").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    worker.remove_upload_files(root, ["upload_a", "../outside", ".", ""])

    assert not (root / "upload_a").exists()
    assert (root / "upload_keep").exists() and outside.exists() and root.exists()


@pytest.mark.asyncio
async def test_reset_removes_only_uploaded_emails(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    (tmp_path / "uploads" / "upload_a").mkdir(parents=True)
    (tmp_path / "uploads" / "upload_keep").mkdir()
    session = _session(monkeypatch)
    monkeypatch.setattr(worker.emails_repo, "delete_uploads", AsyncMock(return_value=["upload_a"]))

    assert await worker.reset_uploads() == ["upload_a"]

    assert not (tmp_path / "uploads" / "upload_a").exists()
    assert (tmp_path / "uploads" / "upload_keep").exists()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_seed_resets_runs_and_survives_a_scorer_outage(monkeypatch):
    _session(monkeypatch)
    monkeypatch.setattr(worker, "init_db", AsyncMock())
    monkeypatch.setattr(worker, "ingest", AsyncMock(return_value=520))
    run_id = uuid.uuid4()
    monkeypatch.setattr(worker.runs_repo, "create", AsyncMock(return_value=SimpleNamespace(id=run_id)))
    run_command = AsyncMock()
    monkeypatch.setattr(worker, "run_command", run_command)
    reset = AsyncMock()
    monkeypatch.setattr(worker, "reset_uploads", reset)

    assert await worker.seed(reset=True) == str(run_id)

    reset.assert_awaited_once()
    run_command.assert_awaited_once_with(str(run_id), [])


@pytest.mark.asyncio
async def test_a_full_run_is_scored(monkeypatch):
    monkeypatch.setattr(worker, "run_pipeline", AsyncMock(return_value="rid"))
    submit = AsyncMock(return_value={"final_score": 1.0})
    monkeypatch.setattr(worker, "submit", submit)

    assert await worker.run_command("rid", []) == "rid"

    submit.assert_awaited_once_with("rid")


@pytest.mark.asyncio
async def test_a_subset_run_is_not_scored(monkeypatch):
    monkeypatch.setattr(worker, "run_pipeline", AsyncMock(return_value="rid"))
    submit = AsyncMock()
    monkeypatch.setattr(worker, "submit", submit)

    await worker.run_command("rid", ["email_004"])

    submit.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_scorer_outage_does_not_fail_the_run(monkeypatch):
    monkeypatch.setattr(worker, "run_pipeline", AsyncMock(return_value="rid"))
    monkeypatch.setattr(worker, "submit", AsyncMock(side_effect=ConnectionError("scorer down")))

    assert await worker.run_command("rid", []) == "rid"
