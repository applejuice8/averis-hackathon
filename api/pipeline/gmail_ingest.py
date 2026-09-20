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

# Mail within the chosen window is fetched (attachments optional) — never the
# whole mailbox — so we don't pull more of the user's inbox than requested.
DEFAULT_DAYS = 1
_TAG_RE = re.compile(r"<[^>]+>")
_UNSAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _window_query(days: int) -> str:
    return f"newer_than:{max(1, days)}d"


def _b64url(data: str) -> bytes:
    # Gmail base64url payloads often arrive without padding
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


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


def _attachment_names(payload: dict) -> list[str]:
    """Attachment filenames without downloading the bytes."""
    names = []
    for part in _walk(payload):
        filename = part.get("filename")
        body = part.get("body") or {}
        if filename and (body.get("attachmentId") or body.get("data")):
            names.append(filename)
    return names


def _service(account):
    creds = gmail_client.credentials_from_refresh_token(account.refresh_token)
    return gmail_client.build_service(creds)


def _list_ids(service, query: str, max_results: int) -> list[str]:
    listing = (
        service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
    )
    return [m["id"] for m in listing.get("messages", [])]


def preview_records(service, query: str, max_results: int) -> list[dict]:
    """Metadata for every message in the window; downloads nothing."""
    items = []
    ids = _list_ids(service, query, max_results)
    print(f"[gmail] pulled {len(ids)} message(s) for query: {query!r}")
    for msg_id in ids:
        msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
        payload = msg.get("payload", {})
        names = _attachment_names(payload)
        sender, subject, date = (
            _header(payload, "From"), _header(payload, "Subject"), _header(payload, "Date")
        )
        body = _extract_body(payload)
        # print every fetched email so we can see the full Gmail pull
        print(f"[gmail] {msg_id} | {date} | {sender} | {subject} | attachments={names}")
        print(f"[gmail]   body: {body[:500]!r}")
        items.append({
            "message_id": msg_id,
            "subject": subject,
            "sender": sender,
            "date": date,
            "attachments": names,
            "body": body[:4000],
        })
    return items


def fetch_records(service, message_ids: list[str]) -> list[dict]:
    """Download + map only the chosen messages into internal email records."""
    attach_dir = Path(settings.resolved_gmail_data_dir) / "attachments"
    records = []
    for msg_id in message_ids:
        msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
        payload = msg.get("payload", {})
        attachments = _save_attachments(service, msg_id, payload, attach_dir)
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


async def preview(days: int = DEFAULT_DAYS, query: str | None = None, max_results: int = 50) -> list[dict]:
    """List candidate emails for the user to pick from; writes nothing to the DB."""
    import asyncio

    async with SessionLocal() as s:
        account = await accounts_repo.get_primary(s)
        if account is None:
            raise RuntimeError("no Gmail account connected")

        def _run() -> list[dict]:
            return preview_records(_service(account), query or _window_query(days), max_results)

        return await asyncio.to_thread(_run)


async def ingest(message_ids: list[str]) -> int:
    """Import only the user-selected messages into Postgres; returns rows upserted."""
    import asyncio

    if not message_ids:
        return 0
    async with SessionLocal() as s:
        account = await accounts_repo.get_primary(s)
        if account is None:
            raise RuntimeError("no Gmail account connected")

        def _fetch() -> list[dict]:
            return fetch_records(_service(account), message_ids)

        records = await asyncio.to_thread(_fetch)
        n = await emails_repo.upsert_many(s, records)
        await accounts_repo.mark_synced(s, account, None)
        return n
