"""All GmailAccount queries — single connected mailbox for the prototype."""
import uuid
from datetime import datetime

from sqlalchemy import desc, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from ..db.models import GmailAccount


async def upsert(
    s: AsyncSession,
    google_email: str,
    refresh_token: str,
    token_expiry: datetime | None,
) -> GmailAccount:
    """Store or refresh the connected account, keyed on google_email."""
    values = {
        "google_email": google_email,
        "refresh_token": refresh_token,
        "token_expiry": token_expiry,
    }
    base = insert(GmailAccount).values(**values)
    stmt = (
        base
        .on_conflict_do_update(
            index_elements=["google_email"],
            # keep any prior refresh_token when Google omits one on re-consent
            set_={
                "refresh_token": func.coalesce(
                    base.excluded.refresh_token, GmailAccount.refresh_token
                ),
                "token_expiry": token_expiry,
                "updated_at": func.now(),
            },
        )
        .returning(GmailAccount)
    )
    row = (await s.execute(stmt)).scalar_one()
    await s.commit()
    return row


async def get_primary(s: AsyncSession) -> GmailAccount | None:
    return (
        await s.execute(select(GmailAccount).order_by(desc(GmailAccount.created_at)).limit(1))
    ).scalar_one_or_none()


async def list_all(s: AsyncSession):
    return (
        await s.execute(select(GmailAccount).order_by(desc(GmailAccount.created_at)))
    ).scalars().all()


async def mark_synced(s: AsyncSession, account: GmailAccount, history_id: str | None) -> None:
    account.last_synced_at = func.now()
    if history_id:
        account.history_id = history_id
    await s.commit()


async def delete(s: AsyncSession, account_id: str | uuid.UUID) -> bool:
    if isinstance(account_id, str):
        account_id = uuid.UUID(account_id)
    account = await s.get(GmailAccount, account_id)
    if account is None:
        return False
    await s.delete(account)
    await s.commit()
    return True
