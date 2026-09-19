"""Per-email orchestration: classify -> read -> extract -> escalate? -> compare.

Returns a dict shaped for pipeline_results columns.
"""
import re
from pathlib import Path

from .classify import COMPARE_INTENT_RE, SEND_BL_INTENT_RE, classify
from .compare import verdict as compare_verdict
from .extract import extract_fields, detect_doc_type, COMPARE_FIELDS
from .readers import read_attachment


def _si_bl_paths(email) -> tuple[str | None, str | None]:
    si = bl = None
    for a in email.get("attachments") or []:
        name = a.rsplit("/", 1)[-1].upper()
        if "_SI" in name:
            si = a
        elif "_BL" in name:
            bl = a
    return si, bl


def _base(email, category, decided_by, rationale):
    return {
        "email_id": email["email_id"],
        "category": category,
        "decided_by": decided_by,
        "status": "OK",
        "review_reason": None,
        "has_defect": False,
        "defect_fields": [],
        "si_fields": None,
        "bl_fields": None,
        "doc_types": None,
        "evidence": {"rationale": rationale},
        "error": None,
    }


def _needs_review(result, reason, evidence_extra):
    result["status"] = "NEEDS_REVIEW"
    result["review_reason"] = reason
    result["evidence"] = {**(result.get("evidence") or {}), **evidence_extra}
    return result


def process_email(email: dict, data_dir: str) -> dict:
    category, decided_by, rationale = classify(email)
    res = _base(email, category, decided_by, rationale)
    if category != "BL_COMPARISON":
        return res

    body = email.get("body") or ""
    si_path, bl_path = _si_bl_paths(email)
    attachments = email.get("attachments") or []

    # --- escalation: missing attachment -------------------------------
    # Explicit compare request but the pair isn't there. A "please send the
    # draft BL" request is normal awaiting-docs work, not an escalation.
    if not (si_path and bl_path):
        if COMPARE_INTENT_RE.search(body) and not SEND_BL_INTENT_RE.search(body):
            return _needs_review(res, "missing_attachment",
                                 {"attachments": attachments})
        return res  # awaiting docs -> nothing to compare -> OK

    si_doc = read_attachment(Path(data_dir) / si_path)
    bl_doc = read_attachment(Path(data_dir) / bl_path)
    res["evidence"]["attachments"] = [si_path, bl_path]

    # --- escalation: unreadable ---------------------------------------
    unreadable = [p for p, d in ((si_path, si_doc), (bl_path, bl_doc)) if not d.readable]
    if unreadable:
        return _needs_review(res, "unreadable", {
            "files": unreadable,
            "errors": {si_path: si_doc.meta.get("error"), bl_path: bl_doc.meta.get("error")},
        })

    # --- escalation: wrong doc type ------------------------------------
    si_type, bl_type = detect_doc_type(si_doc.text), detect_doc_type(bl_doc.text)
    res["doc_types"] = {si_path: si_type, bl_path: bl_type}
    if si_type != "SI" or bl_type != "BL":
        return _needs_review(res, "wrong_doc_type", {
            "detected": {"si": si_type, "bl": bl_type}})

    # --- extract -------------------------------------------------------
    si = extract_fields(si_doc.text)
    bl = extract_fields(bl_doc.text)
    res["si_fields"] = si["fields"]
    res["bl_fields"] = bl["fields"]

    # --- escalation: missing value -------------------------------------
    missing = [f for f in COMPARE_FIELDS
               if f in si["missing_fields"] or f in bl["missing_fields"]
               or si["fields"].get(f) is None or bl["fields"].get(f) is None]
    if missing:
        return _needs_review(res, "missing_value", {"blank_fields": missing})

    # --- compare --------------------------------------------------------
    status, diffs = compare_verdict(si["fields"], bl["fields"])
    res["status"] = status
    res["has_defect"] = status == "MISMATCH"
    res["defect_fields"] = diffs
    return res


def to_submission_entry(res: dict) -> dict:
    return {
        "category": res["category"],
        "status": res["status"],
        "review_reason": res["review_reason"],
        "has_defect": res["has_defect"],
        "defect_fields": res["defect_fields"],
        "decided_by": res["decided_by"],
    }
