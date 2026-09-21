"""Spam-detection payloads — separate from ORM so the wire shape is explicit."""
from pydantic import BaseModel, Field, model_validator


class SpamDetectRequest(BaseModel):
    """Same fields the pipeline sees — sender, subject and body carry the
    spam signal; attachment names are optional context."""
    sender: str = Field(default="", max_length=320)
    subject: str = Field(default="", max_length=2_000)
    body: str = Field(default="", max_length=100_000)
    attachments: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def require_text(self):
        if not any(value.strip() for value in (self.sender, self.subject, self.body)):
            raise ValueError("sender, subject, or body is required")
        return self


class SpamDetectResponse(BaseModel):
    spam: bool
    score: float  # P(spam) in [0, 1]


class SpamModelMetrics(BaseModel):
    accuracy: float
    precision: float
    recall: float
    f1: float


class SpamValidationRun(BaseModel):
    iteration: int
    repeat: int
    fold: int
    training_records: int
    validation_records: int
    precision: float
    recall: float
    f1: float


class SpamHoldoutDetails(BaseModel):
    records: int
    spam_records: int
    true_negatives: int
    false_positives: int
    false_negatives: int
    true_positives: int


class SpamModelDetails(BaseModel):
    model_name: str | None
    framework: str
    classifier: str | None
    vectorizer: str | None
    threshold: float
    last_updated_at: str | None
    training_records: int | None
    spam_records: int | None
    sklearn_version: str | None
    evaluation_method: str | None
    metrics: SpamModelMetrics | None
    validation_runs: list[SpamValidationRun] | None
    holdout: SpamHoldoutDetails | None
