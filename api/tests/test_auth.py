"""Reviewer passcode: reads stay open, every write needs the passcode.

    uv run pytest api/tests/test_auth.py -v
"""
import sys
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import main  # noqa: E402
from app.api.deps import require_reviewer  # noqa: E402
from app.core.config import settings  # noqa: E402

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@pytest.fixture
def client():
    return TestClient(main.app)


def test_open_when_no_passcode_is_configured(client):
    assert client.get("/api/auth/check").status_code == 204


@pytest.mark.parametrize("headers", [{}, {"X-Demo-Passcode": "wrong"}, {"X-Demo-Passcode": ""}])
def test_rejects_a_missing_or_wrong_passcode(client, monkeypatch, headers):
    monkeypatch.setattr(settings, "demo_passcode", "harbour-42")
    r = client.get("/api/auth/check", headers=headers)

    assert r.status_code == 401
    assert "passcode" in r.json()["detail"].lower()


def test_accepts_the_right_passcode(client, monkeypatch):
    monkeypatch.setattr(settings, "demo_passcode", "harbour-42")
    assert client.get("/api/auth/check", headers={"X-Demo-Passcode": "harbour-42"}).status_code == 204


def _guarded(route: APIRoute) -> bool:
    return any(d.call is require_reviewer for d in route.dependant.dependencies)


def _flatten_routes(app, prefix=""):
    """Recursively flatten all routes in the app, including included routers."""
    for route in app.routes:
        if isinstance(route, APIRoute):
            yield route, prefix
        elif hasattr(route, 'original_router'):  # _IncludedRouter
            # Find the actual prefix by examining the router setup
            # The api_router has prefix="/api"
            yield from _flatten_routes(route.original_router, prefix="/api")


def test_every_write_route_requires_the_passcode(client):
    routes_with_prefix = list(_flatten_routes(main.app))
    writes = [r for r, prefix in routes_with_prefix
              if (prefix + r.path).startswith("/api") and r.methods & WRITE_METHODS]
    assert writes, "expected write routes under /api"
    unguarded = [prefix + r.path for r, prefix in routes_with_prefix
                 if (prefix + r.path).startswith("/api") and r.methods & WRITE_METHODS and not _guarded(r)]
    assert unguarded == [], f"write routes without require_reviewer: {unguarded}"


def test_model_assist_is_a_post(client):
    routes_with_prefix = list(_flatten_routes(main.app))
    routes = {(prefix + r.path, m) for r, prefix in routes_with_prefix for m in r.methods}
    assert ("/api/pipeline/llm-assist/{email_id}", "POST") in routes, f"POST route not found in {sorted(routes)}"
    assert ("/api/pipeline/llm-assist/{email_id}", "GET") not in routes


def test_a_write_without_the_passcode_is_refused_before_any_work(client, monkeypatch):
    monkeypatch.setattr(settings, "demo_passcode", "harbour-42")
    assert client.post("/api/pipeline/run").status_code == 401
