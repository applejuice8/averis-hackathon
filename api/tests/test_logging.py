"""JSON log lines that Cloud Logging understands, with request traces."""
import json
import logging
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.logging import (  # noqa: E402
    JsonFormatter,
    configure_logging,
    parse_trace_header,
    trace_id,
    trace_middleware,
)


def _record(msg="processed", **extra):
    record = logging.LogRecord("sdoc.pipeline", logging.INFO, __file__, 1, msg, None, None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_lines_carry_severity_and_run_context():
    line = json.loads(JsonFormatter("proj").format(_record(run_id="r1", email_id="email_004")))
    assert line == {"severity": "INFO", "message": "processed", "logger": "sdoc.pipeline",
                    "run_id": "r1", "email_id": "email_004"}


def test_trace_is_linked_when_the_request_had_one():
    token = trace_id.set("abc123")
    try:
        line = json.loads(JsonFormatter("proj").format(_record()))
    finally:
        trace_id.reset(token)
    assert line["logging.googleapis.com/trace"] == "projects/proj/traces/abc123"


def test_exceptions_are_included():
    try:
        raise ValueError("bad pdf")
    except ValueError:
        record = _record()
        record.exc_info = sys.exc_info()
    assert "ValueError: bad pdf" in json.loads(JsonFormatter().format(record))["exception"]


@pytest.mark.parametrize("header,expected", [
    ("105445aa7843bc8bf206b12000100000/1;o=1", "105445aa7843bc8bf206b12000100000"),
    ("", None),
    (None, None),
])
def test_parse_trace_header(header, expected):
    assert parse_trace_header(header) == expected


def test_middleware_exposes_the_trace_to_the_request():
    app = FastAPI()
    app.middleware("http")(trace_middleware)

    @app.get("/probe")
    async def probe():
        return {"trace": trace_id.get()}

    r = TestClient(app).get("/probe", headers={"X-Cloud-Trace-Context": "t-42/7;o=1"})
    assert r.json() == {"trace": "t-42"}


def test_json_mode_routes_uvicorn_through_the_formatter():
    root, access = logging.getLogger(), logging.getLogger("uvicorn.access")
    saved = (root.handlers[:], root.level, access.handlers[:], access.propagate)
    try:
        configure_logging("json", "proj")
        assert isinstance(access.handlers[0].formatter, JsonFormatter)
        assert isinstance(root.handlers[0].formatter, JsonFormatter)
    finally:
        root.handlers, access.handlers = saved[0], saved[2]
        root.setLevel(saved[1])
        access.propagate = saved[3]
