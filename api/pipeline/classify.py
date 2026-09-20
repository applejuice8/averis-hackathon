"""Stage 1 — email triage.

Learned spam gate first (pipeline/spam.py — no-op until the model artifact
exists), then deterministic rules (free, auditable, feeds decided_by='rule'),
LLM fallback only when rules are unconfident.
"""
import re

from .spam import predict_spam

CATEGORIES = ["BL_COMPARISON", "SI_REQUEST", "INVOICE_QUERY", "GENERAL", "SPAM"]

SI_TERM = r"\b(?:si|s\.i\.|shipping instruction)\b"
BL_TERM = r"\b(?:bl|b/l|bill of lading)\b"

BLC_SUBJ_RE = re.compile(r"(to confirm docs|request bl draft|draft bl|bl draft)", re.I)
SI_SUBJ_RE = re.compile(r"(request si|cust si|si needed|latest si|^si\b|\bsi\b\s*[-_])", re.I)
INV_RE = re.compile(
    r"(invoice|missing gr|\bgr\b|charges|d\s*&\s*d|detention|"
    r"telex release|local charges|total freight|\bfreight\b|cancel)",
    re.I,
)
# 'billing' alone is too weak — automation bots announce "Billing Process Completed"
INV_STRONG_RE = re.compile(r"(invoice|missing gr|d\s*&\s*d|detention|telex release|local charges|total freight)", re.I)
BOT_SENDER_RE = re.compile(r"(bot|no-?reply|donotreply|auto)@")

COMPARE_INTENT_RE = re.compile(
    rf"(?:compare|check|verify|confirm)[\s\S]{{0,80}}{SI_TERM}[\s\S]{{0,80}}{BL_TERM}|"
    rf"(?:compare|check|verify|confirm)[\s\S]{{0,80}}{BL_TERM}[\s\S]{{0,80}}{SI_TERM}|"
    rf"attached[\s\S]{{0,80}}{SI_TERM}[\s\S]{{0,80}}(?:and|&)[\s\S]{{0,80}}{BL_TERM}|"
    r"to confirm docs",
    re.I,
)
SEND_BL_INTENT_RE = re.compile(
    rf"(?:send|assist to send|please send)[\s\S]{{0,40}}(?:draft\s+)?{BL_TERM}", re.I
)
SI_BODY_RE = re.compile(
    r"please find shipping instruction|revert with (the )?draft bl|documents required",
    re.I,
)


def _att_kinds(attachments):
    kinds = set()
    for a in attachments or []:
        name = a.rsplit("/", 1)[-1].upper()
        if "_SI" in name:
            kinds.add("SI")
        elif "_BL" in name:
            kinds.add("BL")
    return kinds


def classify(email) -> tuple[str, str, str]:
    """Return (category, decided_by, rationale)."""
    sender = (email.get("from") or "").lower()
    subject = email.get("subject") or ""
    body = email.get("body") or ""
    hay = subject + "\n" + body
    att_kinds = _att_kinds(email.get("attachments"))

    # 1. spam — learned model; None when no artifact is loaded
    spam = predict_spam(email)
    if spam is not None and spam.spam:
        return "SPAM", "ml", f"spam model p={spam.score:.2f}"

    # 2. SI+BL attachments or explicit compare request -> doc-check queue
    if att_kinds == {"SI", "BL"} or COMPARE_INTENT_RE.search(hay):
        return "BL_COMPARISON", "rule", "SI+BL attachments or explicit compare request"

    # 3. SI request: subject cues, or the body itself IS a shipping instruction
    if SI_SUBJ_RE.search(subject) or (
        re.search(r"shipping instruction", hay, re.I) and SI_BODY_RE.search(hay)
    ):
        return "SI_REQUEST", "rule", "SI request cues"

    # 4. invoice/billing
    if INV_STRONG_RE.search(hay) or (INV_RE.search(subject) and not BOT_SENDER_RE.search(sender)):
        return "INVOICE_QUERY", "rule", "billing/invoice cues"

    # 5. "please send the draft BL" / doc-handling subjects -> still doc-check queue
    if SEND_BL_INTENT_RE.search(hay) or BLC_SUBJ_RE.search(subject):
        return "BL_COMPARISON", "rule", "BL-doc handling request"

    return "GENERAL", "rule", "no category cues matched"


CLASSIFY_SYS = """You triage a shipping-operations inbox into exactly one queue:
BL_COMPARISON  - asks to check a draft Bill of Lading against a Shipping Instruction
SI_REQUEST     - provides or requests a Shipping Instruction (no BL check yet)
INVOICE_QUERY  - billing/invoice/charges/detention questions
GENERAL        - ops updates, reports, reminders, bots, HR
SPAM           - marketing/phishing/junk
Reply with ONLY JSON: {"category": one of the above, "confidence": 0-1, "rationale": "short"}"""


def classify_llm(email) -> tuple[str, str, str] | None:
    """LLM fallback — used only when rules produce the no-cue GENERAL bucket."""
    try:
        from app.services.llm import llm_json

        r = llm_json(
            [
                {"role": "system", "content": CLASSIFY_SYS},
                {
                    "role": "user",
                    "content": (
                        f"From: {email.get('from','')}\n"
                        f"Subject: {email.get('subject','')}\n"
                        f"Attachments: {email.get('attachments') or []}\n\n"
                        f"{(email.get('body') or '')[:3000]}"
                    ),
                },
            ]
        )
        cat = r.get("category")
        if cat in CATEGORIES and cat != "GENERAL" and float(r.get("confidence", 0)) >= 0.7:
            return cat, "llm", r.get("rationale", "llm fallback")
    except Exception:
        pass
    return None
