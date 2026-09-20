"""Pipeline run + review payloads."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, model_validator

from ..db.models import Run


class RunView(BaseModel):
    id: str
    label: str | None
    started_at: datetime | None
    finished_at: datetime | None
    stats: dict | None
    score: dict | None
    error: str | None = None

    @classmethod
    def from_orm_row(cls, r: Run) -> "RunView":
        return cls(
            id=str(r.id),
            label=r.label,
            started_at=r.started_at,
            finished_at=r.finished_at,
            stats=r.stats,
            score=r.score,
            error=r.error,
        )


class RunDetail(RunView):
    results: int


class RunStarted(BaseModel):
    run_id: str
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

    @model_validator(mode="after")
    def validate_payload(self):
        payload = self.payload or {}
        if self.action == "override_fields":
            fields = payload.get("defect_fields")
            allowed = {"shipper", "consignee", "notify_party", "port_of_loading",
                       "port_of_discharge", "container_count", "gross_weight_kg"}
            if not isinstance(fields, list) or any(
                not isinstance(f, str) or f not in allowed for f in fields
            ) or len(fields) != len(set(fields)):
                raise ValueError("defect_fields must contain unique canonical field names")
        if self.action == "override_status":
            if payload.get("status") not in {"OK", "NEEDS_REVIEW"}:
                raise ValueError("Choose OK or NEEDS_REVIEW; use override_fields for mismatches")
            if payload["status"] == "NEEDS_REVIEW" and not (
                isinstance(payload.get("review_reason"), str) and payload["review_reason"].strip()
            ):
                raise ValueError("Escalation needs a review reason")
        return self


class ReviewOutcome(BaseModel):
    ok: bool
    status: str | None
