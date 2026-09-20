"""Repository helpers and schema migrations, checked without a database."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db import session as db_session  # noqa: E402
from app.repositories import emails as emails_repo  # noqa: E402


def _sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def test_upload_cleanup_touches_only_uploaded_emails_in_fk_order():
    reviews, results, emails = (_sql(s) for s in emails_repo.upload_delete_statements())

    assert reviews.startswith("DELETE FROM reviews")
    assert results.startswith("DELETE FROM pipeline_results")
    assert emails.startswith("DELETE FROM emails")
    for sql in (reviews, results, emails):
        assert "emails.source = 'upload'" in sql


def test_full_runs_only_see_dataset_emails():
    sql = _sql(emails_repo.list_all_statement(["email_004"], "dataset"))
    assert "emails.source = 'dataset'" in sql
    assert "emails.email_id IN ('email_004')" in sql
    assert "WHERE" not in _sql(emails_repo.list_all_statement(None, None))


def test_to_record_matches_the_inbox_json_shape():
    row = SimpleNamespace(email_id="upload_20260920_a1b2c3", sender="ops@example.com",
                          subject="Check", body="Hi", attachments=None)
    assert emails_repo.to_record(row) == {
        "email_id": "upload_20260920_a1b2c3", "from": "ops@example.com",
        "subject": "Check", "body": "Hi", "attachments": [],
    }


@pytest.mark.asyncio
async def test_init_db_adds_new_columns_idempotently(monkeypatch):
    executed = []

    class Conn:
        async def run_sync(self, fn):
            executed.append("create_all")

        async def execute(self, stmt):
            executed.append(str(stmt))

    class Begin:
        async def __aenter__(self):
            return Conn()

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(db_session, "engine", SimpleNamespace(begin=lambda: Begin()))
    await db_session.init_db()

    assert executed[0] == "create_all"
    assert all("IF NOT EXISTS" in sql for sql in executed[1:])
    assert any("emails ADD COLUMN IF NOT EXISTS source" in sql for sql in executed)
    assert any("runs ADD COLUMN IF NOT EXISTS error" in sql for sql in executed)
