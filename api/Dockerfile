# syntax=docker/dockerfile:1
# --- build: resolve locked dependencies into a venv ---------------------------
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS build
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

# --- runtime: slim python, non-root, dataset baked in -------------------------
FROM python:3.13-slim-bookworm AS runtime
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/data \
    LLM_CACHE_DIR=/tmp/llm-cache
RUN useradd --uid 10001 --create-home app
WORKDIR /app/api
COPY --from=build /app/.venv /app/.venv
COPY api/ /app/api/
COPY docs-provided/problem-statement/sdoc-hackathon-bundle/inbox /data/inbox
COPY docs-provided/problem-statement/sdoc-hackathon-bundle/attachments /data/attachments
# compose mounts a volume here; Cloud Run mounts the uploads bucket here
RUN mkdir -p /data/uploads && chown app:app /data/uploads
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/livez').status == 200 else 1)"]
CMD ["uvicorn", "app.main:app", "--app-dir", "/app/api", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
