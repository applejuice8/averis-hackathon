"""Spam detection seam — the learned model replaces the old domain/regex
rules. These tests pin the contract without torch or a trained artifact.

    uv run pytest api/tests/test_spam.py -v
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_DIR))

from app import main  # noqa: E402
from app.core.config import settings  # noqa: E402
from pipeline import spam  # noqa: E402
from pipeline.classify import classify  # noqa: E402
from pipeline.spam import predict_spam  # noqa: E402

SPAMMY = {
    "email_id": "t",
    # a bundled-dataset junk domain + classic spam phrasing: the removed
    # blocklist/regex rules used to flag this instantly
    "from": "info@crypto-invest.net",
    "subject": "Increase your shipping revenue with this ONE weird trick",
    "body": "Congratulations! You have won. Claim now.",
    "attachments": [],
}


@pytest.fixture
def no_model(monkeypatch, tmp_path):
    """Point the model path at nothing and reset the loader cache."""
    monkeypatch.setattr(settings, "spam_model_path", str(tmp_path / "missing.pt"))
    monkeypatch.setattr(spam, "_detector", None)
    monkeypatch.setattr(spam, "_load_failed", False)


@pytest.fixture
def client():
    # no context manager: skips the lifespan, so no database is touched
    return TestClient(main.app)


class _FakeDetector:
    threshold = 0.5

    def __init__(self, score):
        self._score = score

    def score(self, _text):
        return self._score


def test_no_artifact_means_no_verdict(no_model):
    assert predict_spam(SPAMMY) is None


def test_old_rules_no_longer_flag_spam(no_model):
    """With the blocklist/regex gone, a spammy email falls through the
    remaining rules to GENERAL until the model artifact exists."""
    cat, decided_by, _ = classify(SPAMMY)
    assert cat == "GENERAL" and decided_by == "rule"


def test_model_verdict_decides_spam_first(no_model, monkeypatch):
    monkeypatch.setattr(spam, "_detector", _FakeDetector(0.99))
    v = predict_spam(SPAMMY)
    assert v is not None and v.spam and v.score == 0.99
    cat, decided_by, _ = classify(SPAMMY)
    assert cat == "SPAM" and decided_by == "ml"


def test_model_ham_falls_through_to_rules(no_model, monkeypatch):
    monkeypatch.setattr(spam, "_detector", _FakeDetector(0.01))
    assert predict_spam(SPAMMY).spam is False
    cat, _, _ = classify(SPAMMY)
    assert cat == "GENERAL"


def test_detect_route_503_without_model(no_model, client):
    r = client.post(
        "/api/spam/detect",
        json={"sender": "a@b.co", "subject": "hi", "body": "x"},
    )
    assert r.status_code == 503


def test_detect_route_returns_verdict(no_model, monkeypatch, client):
    monkeypatch.setattr(spam, "_detector", _FakeDetector(0.9))
    r = client.post(
        "/api/spam/detect",
        json={"sender": "a@b.co", "subject": "prize", "body": "you won"},
    )
    assert r.status_code == 200
    assert r.json() == {"spam": True, "score": 0.9}
