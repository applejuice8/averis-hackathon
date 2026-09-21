"""EmailCreate schema validation for the manual-intake endpoint — no database.
Also covers POST /api/emails: it must share Task 16's live-intake hardening
(services/intake.py — file count, size and content limits) and write under
DATA_DIR/uploads, the path mounted in both docker compose and Cloud Run."""
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import main  # noqa: E402
from app.api.deps import get_db  # noqa: E402
from app.api.routes import emails as emails_routes  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.schemas.emails import EmailCreate  # noqa: E402


@pytest.mark.parametrize("payload", [
    {},
    {"sender": "", "subject": "", "body": ""},
    {"sender": "   ", "subject": "  ", "body": " \n "},
])
def test_empty_email_rejected(payload):
    with pytest.raises(ValidationError):
        EmailCreate(**payload)


def test_minimal_email_accepted():
    e = EmailCreate(subject="REQUEST BL DRAFT")
    assert e.sender == "" and e.body == ""


def test_full_email_accepted():
    e = EmailCreate(sender="docs@vitalsolutions.sg", subject="TO CONFIRM DOCS",
                    body="Please check.")
    assert e.sender == "docs@vitalsolutions.sg"


PDF = b"%PDF-1.4\n%fake\n"
FORM = {"sender": "ops@example.com", "subject": "TO CONFIRM DOCS"}


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    session = SimpleNamespace(commit=AsyncMock(), flush=AsyncMock())

    async def fake_db():
        yield session

    main.app.dependency_overrides[get_db] = fake_db
    upsert = AsyncMock()
    monkeypatch.setattr(emails_routes.emails_repo, "upsert_many", upsert)
    yield SimpleNamespace(client=TestClient(main.app), upsert=upsert, root=tmp_path)
    main.app.dependency_overrides.clear()


def _files(uploads):
    return [("files", (name, data, "application/octet-stream")) for name, data in uploads]


def test_create_email_stores_under_the_shared_uploads_root(api):
    r = api.client.post("/api/emails", data=FORM, files=_files([("SI.txt", b"Shipper: ACME"), ("BL.pdf", PDF)]))

    assert r.status_code == 201, r.text
    email_id = r.json()["email_id"]
    assert re.fullmatch(r"manual_[0-9a-f]{10}", email_id)
    record = api.upsert.await_args.args[1][0]
    assert record["attachments"] == [f"uploads/{email_id}/SI.txt", f"uploads/{email_id}/BL.pdf"]
    # settings.uploads_root == DATA_DIR/uploads — the path mounted in both
    # docker compose (the `uploads` volume) and Cloud Run (the GCS bucket).
    assert (api.root / record["attachments"][1]).read_bytes() == PDF
    assert settings.data_dir_for(email_id) == settings.resolved_data_dir


def test_create_email_enforces_the_max_file_count(api):
    uploads = [(f"f{i}.txt", b"x") for i in range(5)]
    r = api.client.post("/api/emails", data=FORM, files=_files(uploads))
    assert r.status_code == 422
    assert "at most 4" in r.json()["detail"]
    api.upsert.assert_not_awaited()


def test_create_email_enforces_the_max_file_size(api):
    r = api.client.post("/api/emails", data=FORM, files=_files([("big.txt", b"x" * (3 * 1024 * 1024 + 1))]))
    assert r.status_code == 422
    assert "larger than 3 MiB" in r.json()["detail"]
    api.upsert.assert_not_awaited()


def test_create_email_rejects_content_that_does_not_match_its_extension(api):
    r = api.client.post("/api/emails", data=FORM, files=_files([("fake.pdf", b"hello")]))
    assert r.status_code == 422
    assert "not a PDF" in r.json()["detail"]
    api.upsert.assert_not_awaited()
    assert not (api.root / "uploads").exists()


def test_create_email_rejects_a_disallowed_extension(api):
    r = api.client.post("/api/emails", data=FORM, files=_files([("a.exe", b"MZ")]))
    assert r.status_code == 422
    assert "not allowed" in r.json()["detail"]


def test_create_email_still_allows_subject_only_with_no_attachments(api):
    """The manual-intake form's own (looser than Task 16's) text-field rule
    is unaffected: only the attachment limits are shared."""
    r = api.client.post("/api/emails", data={"subject": "REQUEST BL DRAFT"})
    assert r.status_code == 201, r.text
    assert api.upsert.await_args.args[1][0]["attachments"] == []


def test_create_email_needs_the_passcode(api, monkeypatch):
    monkeypatch.setattr(settings, "demo_passcode", "harbour-42")
    assert api.client.post("/api/emails", data=FORM).status_code == 401


def test_load_mock_data_ingests_the_current_dataset(monkeypatch):
    ingest = AsyncMock(return_value=520)
    monkeypatch.setattr(emails_routes, "ingest", ingest)

    r = TestClient(main.app).post("/api/emails/mock")

    assert r.status_code == 200
    assert r.json() == {"loaded": 520}
    ingest.assert_awaited_once_with()


def test_load_mock_data_reports_ingest_errors(monkeypatch):
    monkeypatch.setattr(emails_routes, "ingest", AsyncMock(side_effect=OSError("dataset unavailable")))

    r = TestClient(main.app).post("/api/emails/mock")

    assert r.status_code == 400
    assert r.json()["detail"] == "dataset unavailable"
