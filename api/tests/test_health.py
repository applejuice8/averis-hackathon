"""The health endpoint reports what the service can reach, without calling
a model or requiring a database.

    uv run pytest api/tests/test_health.py -v
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_DIR))

from app import main  # noqa: E402
from app.core.config import Settings, settings  # noqa: E402
from app.db import session as db_session  # noqa: E402


@pytest.fixture
def client():
    # no context manager: skips the lifespan, so no database is touched
    return TestClient(main.app)


def test_reports_degraded_without_a_database(client, monkeypatch):
    monkeypatch.setattr(db_session, "SessionLocal", None)
    r = client.get("/health")

    assert r.status_code == 503
    assert r.json()["status"] == "degraded"
    assert r.json()["database"] == {"ok": False, "detail": "NEON_DB_URI is not set"}


def test_reports_ok_when_the_database_answers(client, monkeypatch):
    async def reachable():
        return {"ok": True, "emails_ingested": 520}

    monkeypatch.setattr(main, "_database_health", reachable)
    r = client.get("/health")

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["database"]["emails_ingested"] == 520


def test_lists_the_model_chain_and_assist_switches(client, monkeypatch):
    async def reachable():
        return {"ok": True, "emails_ingested": 0}

    monkeypatch.setattr(main, "_database_health", reachable)
    monkeypatch.setattr(settings, "enable_vision_ocr", True)
    body = client.get("/health").json()

    assert body["llm"]["text_models"] == settings.text_model_chain
    assert body["llm"]["text_models"][0] == settings.text_model
    assert body["assists"] == {
        "classify": settings.enable_llm_classify,
        "field_fill": settings.enable_llm_fill,
        "vision_ocr": True,
    }


def test_never_leaks_the_connection_string(client, monkeypatch):
    async def broken():
        try:
            raise RuntimeError("postgresql://user:hunter2@host/db is unreachable")
        except Exception as e:
            return {"ok": False, "detail": type(e).__name__}

    monkeypatch.setattr(main, "_database_health", broken)
    assert "hunter2" not in client.get("/health").text


def test_livez_needs_nothing(client, monkeypatch):
    monkeypatch.setattr(db_session, "SessionLocal", None)
    r = client.get("/livez")

    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_reports_write_protection_and_run_executor(client, monkeypatch):
    async def reachable():
        return {"ok": True, "emails_ingested": 0}

    monkeypatch.setattr(main, "_database_health", reachable)
    monkeypatch.setattr(settings, "demo_passcode", "s3cret-pass")
    monkeypatch.setattr(settings, "run_executor", "cloudrun-job")
    r = client.get("/health")

    assert r.json()["writes_protected"] is True
    assert r.json()["run_executor"] == "cloudrun-job"
    assert "s3cret-pass" not in r.text


def test_writes_are_reported_open_without_a_passcode(client, monkeypatch):
    async def reachable():
        return {"ok": True, "emails_ingested": 0}

    monkeypatch.setattr(main, "_database_health", reachable)
    assert client.get("/health").json()["writes_protected"] is False


def test_cors_origins_and_uploads_root_come_from_settings(tmp_path):
    s = Settings(cors_origins="https://web.example, http://localhost:3000", data_dir=str(tmp_path))

    assert s.cors_origin_list == ["https://web.example", "http://localhost:3000"]
    assert s.uploads_root == tmp_path / "uploads"
