"""Gmail OAuth connect + inbox sync — a new ingest source for the emails table."""
import sys
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from pipeline.gmail_ingest import ingest as gmail_ingest  # noqa: E402

from ...core.config import settings  # noqa: E402
from ...repositories import gmail_accounts as accounts_repo  # noqa: E402
from ...schemas.gmail import GmailAccountView, GmailSyncResult  # noqa: E402
from ...services import gmail as gmail_client  # noqa: E402
from ..deps import get_db  # noqa: E402

router = APIRouter()


@router.get("/auth/google/start")
async def google_start():
    if not settings.google_client_id:
        raise HTTPException(500, "Google OAuth is not configured")
    state = uuid.uuid4().hex
    return RedirectResponse(gmail_client.authorization_url(state))


@router.get("/auth/google/callback")
async def google_callback(code: str | None = None, error: str | None = None,
                          s: AsyncSession = Depends(get_db)):
    if error or not code:
        return RedirectResponse(f"{settings.web_app_url}/inbox?gmail=error")
    creds = gmail_client.exchange_code(code)
    service = gmail_client.build_service(creds)
    email = gmail_client.profile_email(service)
    await accounts_repo.upsert(s, email, creds.refresh_token, creds.expiry)
    return RedirectResponse(f"{settings.web_app_url}/inbox?gmail=connected")


@router.post("/gmail/sync", response_model=GmailSyncResult)
async def gmail_sync(query: str | None = None, s: AsyncSession = Depends(get_db)):
    account = await accounts_repo.get_primary(s)
    if account is None:
        raise HTTPException(400, "No Gmail account connected")
    try:
        n = await gmail_ingest(query=query)
    except Exception as e:
        raise HTTPException(400, str(e))
    return GmailSyncResult(synced=n)


@router.get("/gmail/accounts", response_model=list[GmailAccountView])
async def list_accounts(s: AsyncSession = Depends(get_db)):
    return [GmailAccountView.from_orm_row(a) for a in await accounts_repo.list_all(s)]


@router.delete("/gmail/accounts/{account_id}")
async def delete_account(account_id: uuid.UUID, s: AsyncSession = Depends(get_db)):
    if not await accounts_repo.delete(s, account_id):
        raise HTTPException(404, "no such account")
    return {"deleted": True}
