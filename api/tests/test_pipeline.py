"""Golden-fixture tests on the reference emails — run without DB or network.

    uv run pytest api/tests -v      (from repo root)
"""
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


def _run(email_id):
    return process_email(load_email_record(DATA_DIR, email_id), DATA_DIR)


# ---- classification -------------------------------------------------------

@pytest.mark.parametrize("email_id,expected", [
    ("email_001", "BL_COMPARISON"),
    ("email_004", "BL_COMPARISON"),
    ("email_501", "BL_COMPARISON"),
    ("email_506", "BL_COMPARISON"),
])
def test_classification(email_id, expected):
    assert _run(email_id)["category"] == expected


# ---- end-to-end verdicts --------------------------------------------------

def test_clean_pair_is_ok():
    r = _run("email_001")
    assert (r["status"], r["has_defect"], r["defect_fields"]) == ("OK", False, [])


def test_mismatch_flags_exact_fields():
    r = _run("email_004")
    assert r["status"] == "MISMATCH"
    assert r["has_defect"] is True
    assert sorted(r["defect_fields"]) == ["consignee", "notify_party"]
    # evidence: the two values must differ
    assert r["si_fields"]["consignee"] != r["bl_fields"]["consignee"]


@pytest.mark.parametrize("email_id,reason", [
    ("email_501", "wrong_doc_type"),
    ("email_506", "missing_attachment"),
    ("email_511", "unreadable"),
    ("email_516", "missing_value"),
])
def test_escalation_reasons(email_id, reason):
    r = _run(email_id)
    assert r["status"] == "NEEDS_REVIEW"
    assert r["review_reason"] == reason


# ---- extraction / normalization -------------------------------------------

def test_doc_type_detection():
    r = _run("email_501")
    # invoice mislabeled as *_BL must be detected as invoice, not SI
    types = r["doc_types"]
    assert types and "invoice" in types.values()


def test_label_synonyms_and_formats():
    fields = extract_fields(
        "SHIPPER\nACME PTE LTD\nConsignee (Non-Negotiable)\nBIG BUYER LLC\n"
        "Notify Party: SAME AS CONSIGNEE\nLoad Port: SHANGHAI, CHINA (CNSHA)\n"
        "Discharge Port: ROTTERDAM, NETHERLANDS (NLRTM)\n"
        "No. of Containers: 3 x 40'HC\nGross Wt (kgs): 61,234.5"
    )["fields"]
    assert fields["shipper"] == "ACME PTE LTD"
    assert fields["consignee"] == "BIG BUYER LLC"
    assert fields["port_of_loading"] == "SHANGHAI, CHINA"
    assert fields["container_count"] == 3
    assert fields["gross_weight_kg"] == 61234.5


def test_compare_normalizes_formatting():
    si = {"shipper": "ACME PTE LTD", "consignee": "BIG BUYER LLC",
          "notify_party": "SAME AS CONSIGNEE", "port_of_loading": "SHANGHAI, CHINA",
          "port_of_discharge": "ROTTERDAM, NETHERLANDS",
          "container_count": 3, "gross_weight_kg": 61234.5}
    # same values, different surface forms: punctuation, case, comma-grouping
    bl = dict(si, consignee="big buyer llc.", gross_weight_kg="61,234.5")
    status, diffs = compare_verdict(si, bl)
    assert status == "OK" and diffs == []


def test_compare_flags_real_difference():
    si = {"shipper": "ACME PTE LTD", "consignee": "BIG BUYER LLC",
          "notify_party": "SAME AS CONSIGNEE", "port_of_loading": "SHANGHAI, CHINA",
          "port_of_discharge": "ROTTERDAM, NETHERLANDS",
          "container_count": 3, "gross_weight_kg": 61234.5}
    bl = dict(si, gross_weight_kg=61234)
    status, diffs = compare_verdict(si, bl)
    assert status == "MISMATCH" and diffs == ["gross_weight_kg"]
