"""Calendar feed built from dates found in email subjects or bodies."""
import re

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...repositories import emails as emails_repo
from ..deps import get_db

router = APIRouter()

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_DMY = re.compile(r"\b(\d{1,2})[_/\-](\d{1,2})[_/\-](20\d{2})\b")
_ISO = re.compile(r"\b(20\d{2})[_/\-](\d{1,2})[_/\-](\d{1,2})\b")
_MDY = re.compile(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(20\d{2})\b")
_DMY_NAME = re.compile(r"\b(\d{1,2})\s+([A-Za-z]{3,9})\.?\s+(20\d{2})\b")


def _valid(year: int, month: int, day: int) -> str | None:
    if 1 <= month <= 12 and 1 <= day <= 31:
        return f"{year:04d}-{month:02d}-{day:02d}"
    return None


def _parse(text: str) -> str | None:
    if match := _ISO.search(text):
        return _valid(int(match[1]), int(match[2]), int(match[3]))
    if match := _DMY.search(text):
        return _valid(int(match[3]), int(match[2]), int(match[1]))
    if match := _MDY.search(text):
        month = _MONTHS.get(match[1][:3].lower())
        return _valid(int(match[3]), month, int(match[2])) if month else None
    if match := _DMY_NAME.search(text):
        month = _MONTHS.get(match[2][:3].lower())
        return _valid(int(match[3]), month, int(match[1])) if month else None
    return None


def _extract_date(subject: str | None, body: str | None) -> tuple[str | None, str]:
    if date := _parse(subject or ""):
        return date, "subject"
    if date := _parse((body or "")[:2000]):
        return date, "body"
    return None, ""


@router.get("/calendar")
async def calendar_feed(s: AsyncSession = Depends(get_db)):
    rows = await emails_repo.list_with_latest_results(s)
    items = []
    for email, result in rows:
        date, source = _extract_date(email.subject, email.body)
        if not date:
            continue
        items.append({
            "email_id": email.email_id,
            "date": date,
            "source": source,
            "subject": email.subject,
            "sender": email.sender,
            "category": result.category if result else None,
            "status": result.status if result else None,
        })
    return items
