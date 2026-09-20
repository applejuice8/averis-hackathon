"""The downloadable sample kit used by the manual-intake flow must keep
producing the verdicts the app promises."""
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.verdict import process_email  # noqa: E402

PUBLIC = Path(__file__).resolve().parents[2] / "web" / "public"


def _email(prefix, si="txt", bl="txt"):
    return {"email_id": f"upload_{prefix}", "from": "docs@shipper.example",
            "subject": "TO CONFIRM DOCS - sample shipment",
            "body": "Please compare the attached SI and draft BL and confirm.",
            "attachments": [f"samples/{prefix}_SI.{si}", f"samples/{prefix}_BL.{bl}"]}


@pytest.mark.parametrize("prefix,si,bl,status,reason", [
    ("clean-txt", "txt", "txt", "OK", None),
    ("pdf-pair", "pdf", "pdf", "OK", None),
    ("excel-word", "xlsx", "docx", "OK", None),
    ("scanned", "pdf", "pdf", "NEEDS_REVIEW", "unreadable"),
    ("wrong-doc", "txt", "txt", "NEEDS_REVIEW", "wrong_doc_type"),
])
def test_sample_kit_verdicts(prefix, si, bl, status, reason):
    r = process_email(_email(prefix, si, bl), str(PUBLIC))
    assert (r["category"], r["status"], r["review_reason"]) == ("BL_COMPARISON", status, reason)


def test_editing_the_bl_weight_creates_exactly_one_mismatch(tmp_path):
    kit = tmp_path / "samples"
    kit.mkdir()
    shutil.copy(PUBLIC / "samples" / "clean-txt_SI.txt", kit)
    bl = (PUBLIC / "samples" / "clean-txt_BL.txt").read_text(encoding="utf-8")
    (kit / "clean-txt_BL.txt").write_text(bl.replace("21,577 KG", "22,577 KG"), encoding="utf-8")

    r = process_email(_email("clean-txt"), str(tmp_path))

    assert (r["status"], r["defect_fields"]) == ("MISMATCH", ["gross_weight_kg"])
