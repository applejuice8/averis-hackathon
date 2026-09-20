"""Spam detection — a learned PyTorch model, not rules.

The old domain blocklist + regex (SPAM_DOMAINS / SPAM_RE) memorised the
bundled dataset's junk domains — 1.0 here, useless on anything unseen.
The model lives in `api/ml/`; its artifact lands at
`settings.spam_model_path`. predict_spam() is the single entry point,
shared by the classify stage and POST /api/spam/detect.

Returns None when no usable model is present — the classifier falls
through to its other rules, so the pipeline keeps working before the
model is trained.
"""
import os
import threading
from typing import NamedTuple


class SpamVerdict(NamedTuple):
    spam: bool
    score: float  # P(spam) in [0, 1]


_lock = threading.Lock()
_detector = None      # ml.predict.SpamDetector, loaded on first use
_load_failed = False  # artifact existed but would not load — don't retry forever


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
            from ml.predict import SpamDetector  # api/ml — lands with the model

            _detector = SpamDetector.load(settings.resolved_spam_model_path)
        except Exception:
            _load_failed = True
            return None
    return _detector


def predict_spam(email: dict) -> SpamVerdict | None:
    """Spam verdict for an email record ({from, subject, body, ...});
    None when no model artifact is available."""
    det = _detector_or_none()
    if det is None:
        return None
    text = "\n".join(
        p for p in (email.get("from"), email.get("subject"), email.get("body")) if p
    )
    score = det.score(text)
    return SpamVerdict(spam=score >= det.threshold, score=score)
