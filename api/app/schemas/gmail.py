"""Gmail connection payloads."""
from datetime import datetime

from pydantic import BaseModel

from ..db.models import GmailAccount


class GmailAccountView(BaseModel):
    id: str
    google_email: str | None
    last_synced_at: datetime | None
    created_at: datetime | None

    @classmethod
    def from_orm_row(cls, a: GmailAccount) -> "GmailAccountView":
        return cls(
            id=str(a.id),
            google_email=a.google_email,
            last_synced_at=a.last_synced_at,
            created_at=a.created_at,
        )


class GmailSyncResult(BaseModel):
    synced: int


class GmailPreviewItem(BaseModel):
    message_id: str
    subject: str
    sender: str
    date: str
    attachments: list[str]
    body: str


class GmailSyncRequest(BaseModel):
    message_ids: list[str]
