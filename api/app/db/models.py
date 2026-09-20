import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.sql import func

from .session import Base


class Email(Base):
    __tablename__ = "emails"

    email_id = Column(Text, primary_key=True)  # 'email_004'
    sender = Column(Text)
    subject = Column(Text)
    body = Column(Text)
    attachments = Column(JSONB)  # ['attachments/email_004_SI.txt', ...]
    ingested_at = Column(DateTime(timezone=True), server_default=func.now())


class Run(Base):
    __tablename__ = "runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    label = Column(Text)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    finished_at = Column(DateTime(timezone=True))
    stats = Column(JSONB)
    score = Column(JSONB)


class PipelineResult(Base):
    __tablename__ = "pipeline_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(UUID(as_uuid=True), ForeignKey("runs.id"))
    email_id = Column(Text, ForeignKey("emails.email_id"))
    category = Column(Text)  # BL_COMPARISON | SI_REQUEST | INVOICE_QUERY | GENERAL | SPAM
    decided_by = Column(Text)  # 'rule' | 'llm' | 'ml'
    si_fields = Column(JSONB)
    bl_fields = Column(JSONB)
    doc_types = Column(JSONB)
    status = Column(Text)  # OK | MISMATCH | NEEDS_REVIEW | PENDING | FAILED
    review_reason = Column(Text)
    has_defect = Column(Boolean)
    defect_fields = Column(ARRAY(Text))
    evidence = Column(JSONB)
    error = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Review(Base):
    __tablename__ = "reviews"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    result_id = Column(UUID(as_uuid=True), ForeignKey("pipeline_results.id"))
    action = Column(Text)  # confirm | override_status | override_fields
    payload = Column(JSONB)
    reviewer = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class GmailAccount(Base):
    __tablename__ = "gmail_accounts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    google_email = Column(Text, unique=True)
    refresh_token = Column(Text)  # plaintext (hackathon); encrypt for production
    token_expiry = Column(DateTime(timezone=True))
    history_id = Column(Text)
    last_synced_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
