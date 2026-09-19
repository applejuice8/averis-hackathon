"""Per-email orchestration: classify -> read -> extract -> escalate? -> compare.

Returns a dict shaped for pipeline_results columns.
LLM assists are opt-in (config flags) so scoring runs stay deterministic;
the on-demand llm_assist endpoint exercises them for demos.
"""
import re
from pathlib import Path

from .classify import COMPARE_INTENT_RE, SEND_BL_INTENT_RE, classify, classify_llm
from .compare import verdict as compare_verdict
from .extract import (
    COMPARE_FIELDS,
    detect_doc_type,
    extract_fields,
    extract_fields_llm,
)
from .readers import read_attachment
from .readers.ocr import ocr_extract_fields


def _si_bl_paths(email) -> tuple[str | None, str | None]:
    si = bl = None
    for a in email.get("attachments") or []:
        name = a.rsplit("/", 1)[-1].upper()
        if "_SI" in name:
            si = a
        elif "_BL" in name:
            bl = a
    return si, bl


def _si_bl_by_content(email, data_dir) -> tuple[str | None, str | None]:
    """Filename-independent fallback: identify the SI/BL pair by detected
    document type. Handles neutrally-named or extra attachments."""
    si = bl = None
    for a in email.get("attachments") or []:
        doc = read_attachment(Path(data_dir) / a)
        if not doc.readable:
            continue
        t = detect_doc_type(doc.text)
        if t == "SI" and si is None:
            si = a
        elif t == "BL" and bl is None:
            bl = a
        if si and bl:
            break
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


def _extract_doc(doc, path: str):
    """-> (doc_type, extraction | None). extraction = {fields, missing_fields}.
    None means we could not read/extract anything -> unreadable."""
    from app import config

    if doc.readable:
        ext = extract_fields(doc.text)
        if all(v is None for v in ext["fields"].values()):
            # layout the deterministic parser doesn't know — ask the LLM
            llm = extract_fields_llm(doc.text)
            if llm and any(v is not None for v in llm.values()):
                ext = {
                    "fields": llm,
                    "missing_fields": [f for f in COMPARE_FIELDS if llm.get(f) is None],
                }
        elif config.ENABLE_LLM_FILL and ext["missing_fields"]:
            llm = extract_fields_llm(doc.text)
            if llm:
                for f in list(ext["missing_fields"]):
                    if llm.get(f) is not None:
                        ext["fields"][f] = llm[f]
                        ext["missing_fields"].remove(f)
        return detect_doc_type(doc.text), ext

    if config.ENABLE_VISION_OCR:
        r = ocr_extract_fields(path)
        if r:
            return r["doc_type"], {
                "fields": r["fields"],
                "missing_fields": [f for f in COMPARE_FIELDS if r["fields"].get(f) is None],
            }
    return None, None


def process_email(email: dict, data_dir: str) -> dict:
    from app import config

    category, decided_by, rationale = classify(email)
    if (
        config.ENABLE_LLM_CLASSIFY
        and category == "GENERAL"
        and "no category cues" in rationale
    ):
        llm = classify_llm(email)
        if llm:
            category, decided_by, rationale = llm

    res = _base(email, category, decided_by, rationale)
    if category != "BL_COMPARISON":
        return res

    body = email.get("body") or ""
    si_path, bl_path = _si_bl_paths(email)
    attachments = email.get("attachments") or []

    # filenames are only a convention — fall back to content typing
    if not (si_path and bl_path) and len(attachments) >= 2:
        si_path, bl_path = _si_bl_by_content(email, data_dir)

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

    # --- extract (text or OCR) ----------------------------------------
    si_type, si = _extract_doc(si_doc, str(Path(data_dir) / si_path))
    bl_type, bl = _extract_doc(bl_doc, str(Path(data_dir) / bl_path))

    # --- escalation: unreadable ---------------------------------------
    unreadable = [
        p
        for p, doc, ext in ((si_path, si_doc, si), (bl_path, bl_doc, bl))
        if not doc.readable and ext is None
    ]
    if unreadable:
        return _needs_review(res, "unreadable", {
            "files": unreadable,
            "errors": {si_path: si_doc.meta.get("error"), bl_path: bl_doc.meta.get("error")},
        })

    # --- escalation: wrong doc type ------------------------------------
    res["doc_types"] = {si_path: si_type, bl_path: bl_type}
    if si_type != "SI" or bl_type != "BL":
        return _needs_review(res, "wrong_doc_type", {
            "detected": {"si": si_type, "bl": bl_type}})

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


def llm_assist(email: dict, data_dir: str) -> dict:
    """On-demand AI inspection for the demo: what do the models see?
    Never persisted — the scoring path stays deterministic."""
    out = {"email_id": email["email_id"], "classification": None,
           "extraction": {}, "ocr": {}}
    try:
        c = classify_llm(email)
        if c:
            out["classification"] = {"category": c[0], "rationale": c[2]}
    except Exception as e:
        out["classification"] = {"error": str(e)}

    si_path, bl_path = _si_bl_paths(email)
    for tag, rel in (("si", si_path), ("bl", bl_path)):
        if not rel:
            continue
        doc = read_attachment(Path(data_dir) / rel)
        if doc.readable:
            out["extraction"][tag] = extract_fields_llm(doc.text)
        else:
            out["ocr"][tag] = ocr_extract_fields(str(Path(data_dir) / rel))
    return out
