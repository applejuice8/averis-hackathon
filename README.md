# SDOC Verifier

AI copilot for shipping-document operations — Averis x Monash Hackathon 2026.

Triages a shipping ops inbox into 5 queues, and for Bill-of-Lading check
requests compares the Shipping Instruction against the draft BL across 7
fields — flagging exact mismatches or escalating untrustworthy documents to
human review.

## Architecture

```
web (Next.js, pnpm)  -->  api (FastAPI, uv/Python 3.13)  -->  Neon Postgres
                        |                                -->  OpenRouter LLMs
                        +-->  scorer (provided eval service, dev-only)
```

Design principle: **LLMs read, code decides.** Models handle fuzzy
perception (classification fallback, field extraction, vision OCR);
normalization, comparison, and verdicts are deterministic Python — which is
what the 50%-weighted end-to-end defect score rewards.

- `api/pipeline/` — ingest -> classify -> read -> extract -> escalate ->
  compare -> submit
- `api/app/` — FastAPI + SQLAlchemy (emails, runs, results, reviews)
- `web/app/` — dashboard, inbox, per-email diff view, review queue, runs
- `plans/` — business requirements + technical plan

## Quick start (Docker Compose)

```bash
# .env must contain NEON_DB_URI and OPENROUTER_API_KEY
docker compose up --build
```

- web → http://localhost:3000
- api → http://localhost:8000 (`/health`, `/docs`)
- scorer → http://localhost:8080 (the provided eval server)

The compose `api` mounts `docs-provided/.../sdoc-hackathon-bundle` at `/data`
and reaches the scorer at `http://scorer:8000`.

## Local dev (no Docker)

```bash
uv sync                        # Python deps (pyproject.toml + uv.lock)
cd web && pnpm install         # web deps

uv run uvicorn app.main:app --app-dir api --reload
cd web && pnpm dev
```

## Pipeline commands

```bash
cd api
uv run python -m pipeline.ingest            # load inbox -> Neon (520 emails)
uv run python -m pipeline.run               # process all -> pipeline_results
uv run python -c "import asyncio; from pipeline.submission import submit; \
    print(asyncio.run(submit('<run_id>')))" # score a run
```

Or via HTTP: `POST /api/pipeline/run`, `POST /api/export/submit?run_id=...`.

Current score on the provided dataset: **1.0 final** (46/46 defects caught
end-to-end, escalation precision/recall 1.0).

## LLM assists (opt-in)

Free-tier OpenRouter models; all off by default so scoring runs are
deterministic:

| Flag | Effect |
|---|---|
| `ENABLE_LLM_CLASSIFY` | nemotron-3-ultra re-checks no-cue GENERAL emails |
| `ENABLE_LLM_FILL` | LLM fills individually blank extracted fields |
| `ENABLE_VISION_OCR` | nemotron-3-nano-omni renders+reads scanned PDFs |

`GET /api/pipeline/llm-assist/{email_id}` runs the AI view on demand —
classification, extraction, and OCR — without persisting (demo endpoint).

## Tests

```bash
uv run pytest api/tests -v     # 14 golden-fixture cases, no DB/network
```

## Plans

- `plans/REQUIREMENTS_PLAN.md` — business features with real examples
- `plans/TECHNICAL_PLAN.md` — stack, schema, pipeline stages, scoring
