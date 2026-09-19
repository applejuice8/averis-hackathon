"""Anti-overfit tests: perturb dataset conventions and assert the pipeline
still works. If the system only knew *this* dataset (filenames, exact labels,
exact formats), these would all fail.

    uv run pytest api/tests/test_robustness.py -v
"""
import json
import shutil
import sys
from pathlib import Path

import pytest

API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_DIR))

from app.core.config import settings  # noqa: E402

DATA_DIR = settings.resolved_data_dir
from pipeline.compare import verdict as compare_verdict  # noqa: E402
from pipeline.extract import extract_fields  # noqa: E402
from pipeline.readers import load_email_record  # noqa: E402
from pipeline.verdict import process_email  # noqa: E402


def _stage(tmp_path: Path, email_id: str, rename: dict[str, str],
           text_edits: dict[str, tuple[str, str]] | None = None) -> dict:
    """Copy an email + attachments into tmp_path under new names, optionally
    rewriting attachment text. Returns the perturbed email record."""
    src = load_email_record(DATA_DIR, email_id)
    att_dir = tmp_path / "attachments"
    att_dir.mkdir(parents=True)
    new_atts = []
    for rel in src["attachments"]:
        name = rename.get(rel, rel.rsplit("/", 1)[-1])
        data = (Path(DATA_DIR) / rel).read_bytes()
        for old, new in (text_edits or {}).items():
            if old.encode() in data:
                data = data.replace(old.encode(), new.encode())
        (att_dir / name).write_bytes(data)
        new_atts.append(f"attachments/{name}")
    return {**src, "attachments": new_atts}


# ---- filenames are a convention, not a contract ----------------------------

def test_neutral_filenames_still_verdict(tmp_path):
    """doc_a/doc_b instead of *_SI/*_BL — content typing must find the pair."""
    e = _stage(tmp_path, "email_004", {
        "attachments/email_004_SI.txt": "first_document.txt",
        "attachments/email_004_BL.txt": "second_document.txt",
    })
    r = process_email(e, str(tmp_path))
    assert r["status"] == "MISMATCH"
    assert sorted(r["defect_fields"]) == ["consignee", "notify_party"]


def test_reversed_attachment_order(tmp_path):
    e = _stage(tmp_path, "email_004", {
        "attachments/email_004_SI.txt": "z_last.txt",
        "attachments/email_004_BL.txt": "a_first.txt",
    })
    e["attachments"] = list(reversed(e["attachments"]))
    r = process_email(e, str(tmp_path))
    assert r["status"] == "MISMATCH" and "consignee" in r["defect_fields"]


def test_extra_unrelated_attachment_ignored(tmp_path):
    e = _stage(tmp_path, "email_004", {
        "attachments/email_004_SI.txt": "one.txt",
        "attachments/email_004_BL.txt": "two.txt",
    })
    extra = tmp_path / "attachments" / "readme.txt"
    extra.write_text("NOTES\nThis shipment was booked under OC 5ALT-01226.\n")
    e["attachments"].append("attachments/readme.txt")
    r = process_email(e, str(tmp_path))
    assert r["status"] == "MISMATCH"


# ---- label synonyms: unseen-but-equivalent phrasing -------------------------

def test_synonym_label_swap(tmp_path):
    """Rewrite SI labels to other real-world variants; extraction holds."""
    e = _stage(tmp_path, "email_004", {
        "attachments/email_004_SI.txt": "si.txt",
        "attachments/email_004_BL.txt": "bl.txt",
    }, text_edits={
        "Port of Loading": "POL",
        "Port of Discharge": "Discharge Port",
        "Consignee": "To the Order of",
        "Notify Party": "Notify",
        "Gross Weight": "Gross Wt",
    })
    r = process_email(e, str(tmp_path))
    assert r["status"] == "MISMATCH"
    assert sorted(r["defect_fields"]) == ["consignee", "notify_party"]


# ---- formatting asymmetry that is NOT a defect ------------------------------

def test_port_country_suffix_asymmetry():
    si = {"shipper": "A", "consignee": "B", "notify_party": "C",
          "port_of_loading": "SHANGHAI, CHINA",
          "port_of_discharge": "ROTTERDAM, NETHERLANDS",
          "container_count": 3, "gross_weight_kg": 61234}
    bl = dict(si, port_of_loading="SHANGHAI")  # same port, country omitted
    assert compare_verdict(si, bl) == ("OK", [])


def test_port_code_suffix_asymmetry():
    si = {"shipper": "A", "consignee": "B", "notify_party": "C",
          "port_of_loading": "NANTONG, CHINA (CNNTG)",
          "port_of_discharge": "KARACHI, PAKISTAN",
          "container_count": 6, "gross_weight_kg": 131058}
    bl = dict(si, port_of_loading="NANTONG")
    assert compare_verdict(si, bl) == ("OK", [])


def test_real_port_difference_still_flagged():
    si = {"shipper": "A", "consignee": "B", "notify_party": "C",
          "port_of_loading": "SHANGHAI, CHINA",
          "port_of_discharge": "ROTTERDAM, NETHERLANDS",
          "container_count": 3, "gross_weight_kg": 61234}
    bl = dict(si, port_of_loading="NINGBO, CHINA")
    status, diffs = compare_verdict(si, bl)
    assert status == "MISMATCH" and diffs == ["port_of_loading"]


# ---- blank/missing conventions ----------------------------------------------

@pytest.mark.parametrize("blank", ["TBD", "TO BE ADVISED", "NIL", "—",
                                   "???", "_______"])
def test_blank_tokens(blank):
    fields = extract_fields(
        f"Shipper: ACME LTD\nConsignee: {blank}\nNotify Party: X CO\n"
        "Port of Loading: SHANGHAI\nPort of Discharge: ROTTERDAM\n"
        "No. of Containers: 2\nGross Weight (KG): 1000"
    )
    assert fields["fields"]["consignee"] is None
    assert "consignee" in fields["missing_fields"]


# ---- the escalation trap -----------------------------------------------------

def test_send_bl_request_is_not_escalation():
    """'Please send me the draft BL' — awaiting docs, not a review case."""
    e = {
        "email_id": "synthetic_001",
        "from": "ops@carrier.com",
        "subject": "Draft BL needed",
        "body": "Hi team, please send me the draft BL for OC 12345. Thanks.",
        "attachments": [],
    }
    r = process_email(e, DATA_DIR)
    assert r["status"] == "OK" and r["review_reason"] is None
