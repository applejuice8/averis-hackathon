import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.attachments import preview_attachment, save_attachments


def test_text_preview_and_truncation(tmp_path):
    (tmp_path / "si.txt").write_text("Shipper: ACME\n" * 5000)
    result = preview_attachment(str(tmp_path), ["si.txt"], 0)
    assert result["readable"] and result["truncated"]
    assert len(result["text"]) == 50000


@pytest.mark.parametrize("index", [-1, 1])
def test_unknown_attachment(tmp_path, index):
    with pytest.raises(HTTPException) as exc:
        preview_attachment(str(tmp_path), ["si.txt"], index)
    assert exc.value.status_code == 404


def test_path_escape_and_symlink_rejected(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("private")
    (root / "linked.txt").symlink_to(outside)
    for name in ("../secret.txt", str(outside), "linked.txt"):
        with pytest.raises(HTTPException) as exc:
            preview_attachment(str(root), [name], 0)
        assert exc.value.status_code == 404


def test_missing_document_is_unreadable(tmp_path):
    result = preview_attachment(str(tmp_path), ["missing.pdf"], 0)
    assert not result["readable"]
    assert result["error"] == "missing file"


def test_save_attachments_writes_and_sanitizes(tmp_path):
    rel = save_attachments(str(tmp_path), "manual_x", [("../my doc.pdf", b"data")])
    assert rel == ["attachments/manual_x_my_doc.pdf"]
    assert (tmp_path / rel[0]).read_bytes() == b"data"


def test_save_attachments_dedupes_same_names(tmp_path):
    files = [("si.txt", b"one"), ("si.txt", b"two")]
    rel = save_attachments(str(tmp_path), "manual_y", files)
    assert rel == ["attachments/manual_y_si.txt", "attachments/manual_y_si_2.txt"]
    assert (tmp_path / rel[1]).read_bytes() == b"two"


def test_save_attachments_rejects_oversize(tmp_path):
    with pytest.raises(HTTPException) as exc:
        save_attachments(str(tmp_path), "manual_z", [("big.pdf", b"x" * (10 * 1024 * 1024 + 1))])
    assert exc.value.status_code == 413


def test_saved_attachment_is_previewable(tmp_path):
    rel = save_attachments(str(tmp_path), "manual_p", [("note.txt", b"hello")])
    result = preview_attachment(str(tmp_path), rel, 0)
    assert result["readable"] and result["text"] == "hello"
