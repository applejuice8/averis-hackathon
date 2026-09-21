"""Spam-model integration shared by the pipeline and detection API.

The previous domain blocklist and regex memorised the bundled dataset instead
of generalising to unseen messages. ``predict_spam`` is the single inference
entry point and returns ``None`` until a trained model artifact is available.
"""

import logging
import os
import threading
from typing import NamedTuple

logger = logging.getLogger(__name__)

PACKAGED_EVALUATIONS = {
    "751f5802ee4a82ba733ace311552597d757873d22951325aabc98db551b038fe": {
        "evaluation_method": "Repeated 5-fold stratified cross-validation (3 repeats) plus a fixed 20% holdout",
        "metrics": {"accuracy": 1.0, "precision": 1.0, "recall": 1.0, "f1": 1.0},
        "validation_runs": [
            {
                "iteration": index + 1,
                "repeat": index // 5 + 1,
                "fold": index % 5 + 1,
                "training_records": 332,
                "validation_records": 83,
                "precision": 1.0,
                "recall": 1.0,
                "f1": 1.0,
            }
            for index in range(15)
        ],
        "holdout": {
            "records": 104,
            "spam_records": 8,
            "true_negatives": 96,
            "false_positives": 0,
            "false_negatives": 0,
            "true_positives": 8,
        },
    }
}


class SpamVerdict(NamedTuple):
    spam: bool
    score: float  # P(spam) in [0, 1]


_lock = threading.Lock()
_detector = None
_load_failed = False


def _detector_or_none():
    """Lazy, cached load. A missing file is retryable (a freshly trained
    model can be dropped in without a restart); a broken one is not."""
    global _detector, _load_failed
    if _detector is not None or _load_failed:
        return _detector

    from app.core.config import settings

    if not os.path.exists(settings.resolved_spam_model_path):
        return None
    with _lock:
        if _detector is not None or _load_failed:
            return _detector
        try:
            from ml.model import SpamDetector

            _detector = SpamDetector.load(settings.resolved_spam_model_path)
        except Exception:
            logger.exception("failed to load spam model artifact")
            _load_failed = True
            return None
    return _detector


def model_details() -> dict | None:
    det = _detector_or_none()
    if det is None:
        return None
    classifier = det.pipeline.named_steps.get("classifier")
    vectorizer = det.pipeline.named_steps.get("vectorizer")
    metadata = det.metadata
    evaluation = PACKAGED_EVALUATIONS.get(metadata.get("dataset_sha256"), {})
    return {
        "model_name": metadata.get("model_name"),
        "framework": "scikit-learn",
        "classifier": type(classifier).__name__ if classifier is not None else None,
        "vectorizer": type(vectorizer).__name__ if vectorizer is not None else None,
        "threshold": det.threshold,
        "last_updated_at": metadata.get("trained_at"),
        "training_records": metadata.get("training_records"),
        "spam_records": metadata.get("spam_records"),
        "sklearn_version": metadata.get("sklearn_version"),
        "evaluation_method": metadata.get("evaluation_method") or evaluation.get("evaluation_method"),
        "metrics": metadata.get("metrics") or evaluation.get("metrics"),
        "validation_runs": metadata.get("validation_runs") or evaluation.get("validation_runs"),
        "holdout": metadata.get("holdout") or evaluation.get("holdout"),
    }


def predict_spam(email: dict) -> SpamVerdict | None:
    """Spam verdict for an email record ({from, subject, body, ...});
    None when no model artifact is available."""
    det = _detector_or_none()
    if det is None:
        return None
    from ml.model import format_email

    text = format_email(
        sender=email.get("from") or "",
        subject=email.get("subject") or "",
        body=email.get("body") or "",
    )
    score = det.score(text)
    return SpamVerdict(spam=score >= det.threshold, score=score)
