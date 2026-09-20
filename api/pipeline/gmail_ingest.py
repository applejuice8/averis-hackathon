"""Scrape Gmail into the `emails` table + writable attachment dir.

Mirrors pipeline/ingest.py but sources records from the Gmail API instead of a
static inbox. Attachments keep their original names (SI/BL detection falls back
to content, so no _SI/_BL suffix is required) and land under GMAIL_DATA_DIR so
the existing pipeline reads them like any other email.
"""
import base64
import html
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core.config import settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.repositories import emails as emails_repo  # noqa: E402
from app.repositories import gmail_accounts as accounts_repo  # noqa: E402
from app.services import gmail as gmail_client  # noqa: E402

DEFAULT_QUERY = "has:attachment newer_than:30d"
_TAG_RE = re.compile(r"<[^>]+>")
_UNSAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _b64url(data: str) -> bytes:
    return base64.urlsafe_b64decode(data.encode("utf-8"))


def _header(payload: dict, name: str) -> str:
    for h in payload.get("headers", []):
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _strip_html(raw: str) -> str:
    return html.unescape(_TAG_RE.sub(" ", raw)).strip()


def _walk(payload: dict):
    """Depth-first over every MIME part, including the root."""
    yield payload
    for part in payload.get("parts", []) or []:
        yield from _walk(part)


def _extract_body(payload: dict) -> str:
    """Prefer text/plain; fall back to stripped text/html."""
    plain = html_body = ""
    for part in _walk(payload):
        mime = part.get("mimeType", "")
        data = (part.get("body") or {}).get("data")
        if not data:
            continue
        if mime == "text/plain" and not plain:
            plain = _b64url(data).decode("utf-8", "replace")
        elif mime == "text/html" and not html_body:
            html_body = _b64url(data).decode("utf-8", "replace")
    return plain.strip() or _strip_html(html_body)


def _safe_name(msg_id: str, filename: str) -> str:
    clean = _UNSAFE_RE.sub("_", filename) or "attachment"
    return f"gmail_{msg_id}_{clean}"


def _save_attachments(service, msg_id: str, payload: dict, attach_dir: Path) -> list[str]:
    """Download every real attachment; return repo-relative paths."""
    rels: list[str] = []
    for part in _walk(payload):
        filename = part.get("filename")
        body = part.get("body") or {}
        if not filename or not (body.get("attachmentId") or body.get("data")):
            continue
        data = body.get("data")
        if data is None:
            fetched = (
                service.users()
                .messages()
                .attachments()
                .get(userId="me", messageId=msg_id, id=body["attachmentId"])
                .execute()
            )
            data = fetched.get("data")
        if not data:
            continue
        name = _safe_name(msg_id, filename)
        attach_dir.mkdir(parents=True, exist_ok=True)
        (attach_dir / name).write_bytes(_b64url(data))
        rels.append(f"attachments/{name}")
    return rels


def fetch_records(service, query: str, max_results: int) -> list[dict]:
    """Gmail messages -> internal email records, writing attachments to disk."""
    attach_dir = Path(settings.resolved_gmail_data_dir) / "attachments"
    listing = (
        service.users()
        .messages()
        .list(userId="me", q=query, maxResults=max_results)
        .execute()
    )
    records = []
    for meta in listing.get("messages", []):
        msg_id = meta["id"]
        msg = (
            service.users()
            .messages()
            .get(userId="me", id=msg_id, format="full")
            .execute()
        )
        payload = msg.get("payload", {})
        attachments = _save_attachments(service, msg_id, payload, attach_dir)
        if not attachments:
            continue  # nothing to compare — skip bodies-only mail
        records.append(
            {
                "email_id": f"gmail_{msg_id}",
                "from": _header(payload, "From"),
                "subject": _header(payload, "Subject"),
                "body": _extract_body(payload),
                "attachments": attachments,
            }
        )
    return records


async def ingest(query: str | None = None, max_results: int = 50) -> int:
    """Sync the connected mailbox into Postgres; returns rows upserted."""
    import asyncio

    async with SessionLocal() as s:
        account = await accounts_repo.get_primary(s)
        if account is None:
            raise RuntimeError("no Gmail account connected")

        def _fetch() -> list[dict]:
            creds = gmail_client.credentials_from_refresh_token(account.refresh_token)
            service = gmail_client.build_service(creds)
            return fetch_records(service, query or DEFAULT_QUERY, max_results)

        records = await asyncio.to_thread(_fetch)
        n = await emails_repo.upsert_many(s, records)
        await accounts_repo.mark_synced(s, account, None)
        return n
