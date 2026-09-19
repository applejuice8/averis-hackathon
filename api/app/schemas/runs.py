"""Pipeline run + review payloads."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from ..db.models import Run


class RunView(BaseModel):
    id: str
    label: str | None
    started_at: datetime | None
    finished_at: datetime | None
    stats: dict | None
    score: dict | None

    @classmethod
    def from_orm_row(cls, r: Run) -> "RunView":
        return cls(
            id=str(r.id),
            label=r.label,
            started_at=r.started_at,
            finished_at=r.finished_at,
            stats=r.stats,
            score=r.score,
        )


class RunDetail(RunView):
    results: int


class RunStarted(BaseModel):
    started: bool
    email_ids: list[str] | str


# --- review -----------------------------------------------------------------

ReviewActionKind = Literal["confirm", "override_status", "override_fields"]


class ReviewItem(BaseModel):
    result_id: str
    email_id: str
    status: str | None
    review_reason: str | None
    evidence: dict | None
    error: str | None


class ReviewActionIn(BaseModel):
    action: ReviewActionKind
    payload: dict | None = None
    reviewer: str | None = None


class ReviewOutcome(BaseModel):
    ok: bool
    status: str | None
