"""Review validation and verdict consistency, without a database."""
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.schemas.runs import ReviewActionIn
from app.services import review


@pytest.mark.parametrize("payload", [None, {}, {"defect_fields": ["typo"]},
    {"defect_fields": ["shipper", "shipper"]}, {"defect_fields": "shipper"},
    {"defect_fields": [{}]}])
def test_invalid_fields_rejected(payload):
    with pytest.raises(ValidationError):
        ReviewActionIn(action="override_fields", payload=payload)


@pytest.mark.parametrize("payload", [{"status": "MADE_UP"}, {"status": "MISMATCH"},
    {"status": "NEEDS_REVIEW"}, {"status": "NEEDS_REVIEW", "review_reason": " "}])
def test_invalid_status_rejected(payload):
    with pytest.raises(ValidationError):
        ReviewActionIn(action="override_status", payload=payload)


@pytest.mark.asyncio
@pytest.mark.parametrize("action,payload,status,fields,reason", [
    ("override_status", {"status": "OK"}, "OK", [], None),
    ("override_status", {"status": "NEEDS_REVIEW", "review_reason": "manual_flag"},
     "NEEDS_REVIEW", [], "manual_flag"),
    ("override_fields", {"defect_fields": ["consignee"]}, "MISMATCH", ["consignee"], None),
    ("override_fields", {"defect_fields": []}, "OK", [], None),
    ("confirm", None, "MISMATCH", ["shipper"], None),
])
async def test_review_keeps_verdict_consistent(monkeypatch, action, payload, status, fields, reason):
    row = SimpleNamespace(id=uuid.uuid4(), status="MISMATCH", defect_fields=["shipper"],
                          has_defect=True, review_reason=None)
    monkeypatch.setattr(review.results_repo, "get", AsyncMock(return_value=row))
    audit = AsyncMock()
    monkeypatch.setattr(review.reviews_repo, "add", audit)
    session = SimpleNamespace(commit=AsyncMock())
    await review.apply_action(session, row.id, ReviewActionIn(action=action, payload=payload))
    assert (row.status, row.defect_fields, row.has_defect, row.review_reason) == (
        status, fields, bool(fields), reason)
    audit.assert_awaited_once()
    session.commit.assert_awaited_once()
