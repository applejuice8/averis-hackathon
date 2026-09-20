"""Spam-model integration shared by the pipeline and detection API.

The previous domain blocklist and regex memorised the bundled dataset instead
of generalising to unseen messages. ``predict_spam`` is the single inference
entry point and returns ``None`` until a trained model artifact is available.
"""
import os
import threading
from typing import NamedTuple


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
            from ml.predict import SpamDetector

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
