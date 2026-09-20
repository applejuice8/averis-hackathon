"""Spam-detection payloads — separate from ORM so the wire shape is explicit."""
from pydantic import BaseModel


class SpamDetectRequest(BaseModel):
    """Same fields the pipeline sees — sender, subject and body carry the
    spam signal; attachment names are optional context."""
    sender: str = ""
    subject: str = ""
    body: str = ""
    attachments: list[str] = []


class SpamDetectResponse(BaseModel):
    spam: bool
    score: float  # P(spam) in [0, 1]
