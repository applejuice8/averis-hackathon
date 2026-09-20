"""EmailCreate schema validation for the manual-intake endpoint — no database."""
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.schemas.emails import EmailCreate


@pytest.mark.parametrize("payload", [
    {},
    {"sender": "", "subject": "", "body": ""},
    {"sender": "   ", "subject": "  ", "body": " \n "},
])
def test_empty_email_rejected(payload):
    with pytest.raises(ValidationError):
        EmailCreate(**payload)


def test_minimal_email_accepted():
    e = EmailCreate(subject="REQUEST BL DRAFT")
    assert e.sender == "" and e.attachments == []


def test_full_email_accepted():
    e = EmailCreate(sender="docs@vitalsolutions.sg", subject="TO CONFIRM DOCS",
                    body="Please check.", attachments=["attachments/x_SI.txt"])
    assert e.attachments == ["attachments/x_SI.txt"]
