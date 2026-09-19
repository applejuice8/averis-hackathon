FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

# deps first (lockfile-reproducible) for layer caching
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev

COPY api/ ./api/
WORKDIR /app/api

EXPOSE 8000
CMD ["uv", "run", "--no-dev", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
