"""Test isolation: a developer's .env must not change how the suite behaves."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import settings  # noqa: E402


@pytest.fixture(autouse=True)
def _baseline_settings(monkeypatch):
    monkeypatch.setattr(settings, "demo_passcode", "")
    monkeypatch.setattr(settings, "run_executor", "inline")
    monkeypatch.setattr(settings, "scorer_auth", "none")
    monkeypatch.setattr(settings, "log_format", "text")
    monkeypatch.setattr(settings, "enable_llm_classify", False)
    monkeypatch.setattr(settings, "enable_llm_fill", False)
    monkeypatch.setattr(settings, "enable_vision_ocr", False)
