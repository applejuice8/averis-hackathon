"""Human-review business logic — the only place a verdict may be mutated."""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import PipelineResult
from ..repositories import results as results_repo
from ..repositories import reviews as reviews_repo
from ..schemas.runs import ReviewActionIn


class ReviewConflict(ValueError):
    pass


async def apply_action(
    s: AsyncSession, result_id: str | uuid.UUID, action: ReviewActionIn
) -> PipelineResult | None:
    """Record a review action and apply its effect on the result row.

    confirm          — verdict stands; only the audit row is written.
    override_status  — human sets status/reason directly.
    override_fields  — human sets the defect-field set; status derives from it.
    """
    res = await results_repo.get(s, result_id)
    if res is None:
        return None
    if action.action == "confirm" and res.status not in {"OK", "MISMATCH"}:
        raise ReviewConflict("Choose a final outcome before closing this review")

    audit_payload = {**(action.payload or {}), "note": action.note}
    await reviews_repo.add(s, res.id, action.action, audit_payload, action.reviewer)

    if action.action == "override_status" and action.payload:
        res.status = action.payload.get("status", res.status)
        res.review_reason = action.payload.get("review_reason") if res.status == "NEEDS_REVIEW" else None
        res.defect_fields = []
        res.has_defect = False
    elif action.action == "override_fields" and action.payload:
        res.defect_fields = action.payload.get("defect_fields", res.defect_fields)
        res.has_defect = bool(res.defect_fields)
        res.status = "MISMATCH" if res.has_defect else "OK"
        res.review_reason = None

    await s.commit()
    return res
