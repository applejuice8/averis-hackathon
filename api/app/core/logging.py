"""Logging setup: plain text locally, Cloud Logging JSON in the cloud.

Cloud Run ships each stdout line to Cloud Logging; a JSON line with
`severity` and `logging.googleapis.com/trace` becomes a structured entry
grouped with its request.
"""
import json
import logging
import sys
from contextvars import ContextVar

trace_id: ContextVar[str | None] = ContextVar("trace_id", default=None)
_CONTEXT_FIELDS = ("run_id", "email_id")


class JsonFormatter(logging.Formatter):
    def __init__(self, project_id: str = ""):
        super().__init__()
        self.project_id = project_id

    def format(self, record: logging.LogRecord) -> str:
        entry = {"severity": record.levelname, "message": record.getMessage(), "logger": record.name}
        for field in _CONTEXT_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                entry[field] = value
        trace = trace_id.get()
        if trace and self.project_id:
            entry["logging.googleapis.com/trace"] = f"projects/{self.project_id}/traces/{trace}"
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def parse_trace_header(value: str | None) -> str | None:
    """X-Cloud-Trace-Context: TRACE_ID/SPAN_ID;o=1 -> TRACE_ID"""
    if not value:
        return None
    return value.split("/", 1)[0].strip() or None


async def trace_middleware(request, call_next):
    token = trace_id.set(parse_trace_header(request.headers.get("x-cloud-trace-context")))
    try:
        return await call_next(request)
    finally:
        trace_id.reset(token)


def configure_logging(fmt: str, project_id: str = "") -> None:
    if fmt != "json":
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(project_id))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers = [handler]
        logger.propagate = False
