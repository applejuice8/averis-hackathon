"""Emails API payloads — separate from ORM so the wire shape is explicit."""
from pydantic import BaseModel

from ..db.models import Email, PipelineResult


class ResultSummary(BaseModel):
    category: str
    decided_by: str | None
    status: str
    review_reason: str | None
    has_defect: bool | None
    defect_fields: list[str] | None


class ResultDetail(ResultSummary):
    result_id: str
    si_fields: dict | None
    bl_fields: dict | None
    doc_types: dict | None
    evidence: dict | None
    error: str | None

    @classmethod
    def from_orm_row(cls, r: PipelineResult) -> "ResultDetail":
        return cls(
            result_id=str(r.id),
            category=r.category,
            decided_by=r.decided_by,
            status=r.status,
            review_reason=r.review_reason,
            has_defect=r.has_defect,
            defect_fields=r.defect_fields,
            si_fields=r.si_fields,
            bl_fields=r.bl_fields,
            doc_types=r.doc_types,
            evidence=r.evidence,
            error=r.error,
        )


class EmailListItem(BaseModel):
    email_id: str
    sender: str | None
    subject: str | None
    n_attachments: int
    category: str | None
    status: str | None
    has_defect: bool | None
    defect_fields: list[str] | None
    review_reason: str | None
    decided_by: str | None

    @classmethod
    def from_row(cls, e: Email, r: PipelineResult | None) -> "EmailListItem":
        return cls(
            email_id=e.email_id,
            sender=e.sender,
            subject=e.subject,
            n_attachments=len(e.attachments or []),
            category=r.category if r else None,
            status=r.status if r else None,
            has_defect=r.has_defect if r else None,
            defect_fields=r.defect_fields if r else None,
            review_reason=r.review_reason if r else None,
            decided_by=r.decided_by if r else None,
        )


class EmailDetail(BaseModel):
    email_id: str
    sender: str | None
    subject: str | None
    body: str | None
    attachments: list[str]
    result: ResultDetail | None
