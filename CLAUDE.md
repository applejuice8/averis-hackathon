# CLAUDE.md

## Attribution
Never add yourself as author, co-author, or contributor — no
`Co-Authored-By` trailers, no "Generated with Claude Code" lines, anywhere.

## What this is
Shipping-document verification. Emails carrying a Bill of Lading and Shipping
Instruction get classified, read, extracted, compared field by field, then
escalated to a human reviewer. Rules first, LLM as fallback, vision OCR for
image-only PDFs.

## Stack
FastAPI + async SQLAlchemy on Neon Postgres (`api/`); Next.js 15 on React 19
(`web/`). `uv` for Python, `pnpm` for web.

## Cloud
Cloud Run hosts the API and an IAM-private scorer; batch runs go to a Cloud
Run Job. Vercel hosts the web app and proxies `/api/*`, so the browser never
calls the API directly. Budget guard hard-stops at RM40/month.

## Rules
All routes are publicly accessible. Intake caps: 4 files, 3 MiB each and
total. Never commit credentials.

## Commands
- `uv run ruff check api scripts/gcp/killswitch`
- `cd web && pnpm build`
- `DATA_DIR=docs-provided/problem-statement/sdoc-hackathon-bundle uv run pytest api/tests -q -p no:cacheprovider --basetemp=.pytest-tmp`
