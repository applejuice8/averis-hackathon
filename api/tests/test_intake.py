"""Live intake: validation, safe storage, and the upload -> verdict round trip."""
import re
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import main  # noqa: E402
from app.api.deps import get_db  # noqa: E402
from app.api.routes import intake as intake_routes  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.services import intake  # noqa: E402

PDF = b"%PDF-1.4\n%fake\n"
OK_UPLOADS = [("clean_SI.txt", b"Shipper: ACME"), ("clean_BL.pdf", PDF)]
FORM = {"sender": "ops@example.com", "subject": "TO CONFIRM DOCS", "body": "Please compare the SI and BL."}


def test_ids_are_dated_and_random():
    assert intake.new_email_id(datetime(2026, 9, 20), "a1b2c3") == "upload_20260920_a1b2c3"
    assert re.fullmatch(r"upload_\d{8}_[0-9a-f]{6}", intake.new_email_id())


@pytest.mark.parametrize("raw,expected", [
    ("SI.txt", "SI.txt"),
    ("../../etc/passwd.txt", "passwd.txt"),
    ("C:\\Users\\ops\\Draft BL (v2).PDF", "Draft_BL_v2_.pdf"),
    ("...", "attachment"),
    ("a" * 200 + ".docx", "a" * 75 + ".docx"),
])
def test_filenames_are_reduced_to_a_safe_basename(raw, expected):
    assert intake.safe_filename(raw, set()) == expected


def test_duplicate_names_get_a_suffix():
    taken: set[str] = set()
    assert [intake.safe_filename("SI.txt", taken) for _ in range(3)] == ["SI.txt", "SI-2.txt", "SI-3.txt"]


def test_valid_submission_passes():
    files = intake.validate_submission("ops@example.com", "Check docs", "Please compare", OK_UPLOADS)
    assert [f.name for f in files] == ["clean_SI.txt", "clean_BL.pdf"]


@pytest.mark.parametrize("uploads,message", [
    ([("a.exe", b"MZ")], "not allowed"),
    ([("fake.pdf", b"hello")], "not a PDF"),
    ([("sheet.xlsx", b"hello")], "not a valid xlsx"),
    ([("notes.txt", b"\xff\xfe\xfa")], "not UTF-8"),
    ([("big.txt", b"x" * (intake.MAX_FILE_BYTES + 1))], "larger than 3 MiB"),
    ([(f"f{i}.txt", b"x") for i in range(intake.MAX_FILES + 1)], "at most 4"),
])
def test_bad_files_are_rejected_with_a_reason(uploads, message):
    with pytest.raises(intake.IntakeError, match=message):
        intake.validate_submission("ops@example.com", "Check", "", uploads)


def test_total_size_is_capped():
    chunk = b"x" * (2 * 1024 * 1024)
    with pytest.raises(intake.IntakeError, match="3 MiB in total"):
        intake.validate_submission("ops@example.com", "Check", "", [("a.txt", chunk), ("b.txt", chunk)])


@pytest.mark.parametrize("sender,subject,body,message", [
    ("", "Check", "", "sender"),
    ("ops@example.com", " ", "", "subject"),
    ("ops@example.com", "x" * 301, "", "subject"),
    ("ops@example.com", "Check", "x" * 20_001, "body"),
])
def test_text_fields_are_bounded(sender, subject, body, message):
    with pytest.raises(intake.IntakeError, match=message):
        intake.validate_submission(sender, subject, body, [])


def test_files_are_saved_under_the_email_folder(tmp_path):
    files = intake.validate_submission("ops@example.com", "Check", "", OK_UPLOADS)
    paths = intake.save_files(tmp_path, "uploads", "upload_20260920_a1b2c3", files)

    assert paths == ["uploads/upload_20260920_a1b2c3/clean_SI.txt", "uploads/upload_20260920_a1b2c3/clean_BL.pdf"]
    assert (tmp_path / paths[1]).read_bytes() == PDF


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    session = SimpleNamespace(commit=AsyncMock(), flush=AsyncMock())

    async def fake_db():
        yield session

    main.app.dependency_overrides[get_db] = fake_db
    create = AsyncMock()
    monkeypatch.setattr(intake_routes.emails_repo, "create_upload", create)
    process = AsyncMock(return_value={"status": "MISMATCH", "category": "BL_COMPARISON"})
    monkeypatch.setattr(intake_routes, "process_one", process)
    yield SimpleNamespace(client=TestClient(main.app), create=create, process=process, root=tmp_path)
    main.app.dependency_overrides.clear()


def _files(uploads):
    return [("files", (name, data, "application/octet-stream")) for name, data in uploads]


def test_upload_is_stored_processed_and_returned(api):
    r = api.client.post("/api/intake", data=FORM, files=_files(OK_UPLOADS))

    assert r.status_code == 201, r.text
    body = r.json()
    assert re.fullmatch(r"upload_\d{8}_[0-9a-f]{6}", body["email_id"])
    assert (body["status"], body["category"]) == ("MISMATCH", "BL_COMPARISON")
    record = api.create.await_args.args[1]
    assert record["attachments"] == [f"uploads/{body['email_id']}/clean_SI.txt",
                                     f"uploads/{body['email_id']}/clean_BL.pdf"]
    assert (api.root / record["attachments"][1]).read_bytes() == PDF
    assert api.process.await_args.args[1] is record


def test_a_processing_failure_is_still_created_and_visible(api):
    api.process.return_value = {"status": "FAILED", "category": "GENERAL"}
    r = api.client.post("/api/intake", data=FORM, files=_files(OK_UPLOADS))
    assert (r.status_code, r.json()["status"]) == (201, "FAILED")


def test_invalid_upload_is_a_422_and_nothing_is_stored(api):
    r = api.client.post("/api/intake", data=FORM, files=_files([("x.exe", b"MZ")]))

    assert r.status_code == 422
    assert "not allowed" in r.json()["detail"]
    api.create.assert_not_awaited()
    assert not (api.root / "uploads").exists()


def test_intake_needs_the_passcode(api, monkeypatch):
    monkeypatch.setattr(settings, "demo_passcode", "harbour-42")
    assert api.client.post("/api/intake", data=FORM).status_code == 401
