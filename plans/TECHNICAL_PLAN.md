# Technical Plan — Shipping Document Verification

Companion to `REQUIREMENTS_PLAN.md` (business requirements). This document covers **how** we build it.

**Stack (fixed):** Next.js (frontend) · FastAPI (backend + pipeline) · Neon serverless Postgres (state) · OpenAI SDK → **OpenRouter** (all LLM inference) · **uv** (Python deps) · **pnpm** (JS deps) · **Docker + docker-compose** (runtime; Kubernetes later)

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         USERS / JUDGES                          │
└──────────────┬──────────────────────────────────┬───────────────┘
               │                                  │
        docker-compose (now)  ──►  kubernetes (later stage)
┌──────────────▼───────────────┐   ┌──────────────▼───────────────┐
│  web  (Next.js container)    │   │  api  (FastAPI container)    │
│  ─────────────────────────   │   │  ─────────────────────────   │
│  • Inbox work-queue UI       │──▶│  • REST API for UI           │
│  • SI-vs-BL diff view        │   │  • Pipeline orchestrator     │
│  • Human-review screen       │   │  • Document readers          │
│  • Scoreboard/metrics        │   │  • OpenAI SDK → OpenRouter   │
└──────────────────────────────┘   │  • submission.json export    │
                                   └───────┬───────────────┬──────┘
                                           │               │
                            ┌──────────────▼───┐   ┌───────▼────────┐
                            │  Neon Postgres   │   │  OpenRouter    │
                            │  (managed cloud) │   │  nemotron-3-   │
                            │  NEON_DB_URI     │   │  ultra (text)  │
                            │                  │   │  nemotron-nano │
                            │                  │   │  -vl (vision)  │
                            └──────────────────┘   └────────────────┘

            ┌───────────────────────────────────────────┐
            │  scorer  (provided server, :8080)         │  compose service, dev only
            │  POST /submit → scoreboard                │
            └───────────────────────────────────────────┘
```

**Design principle: LLMs read, code decides.** Use the LLM for perception tasks
(classification, field extraction, OCR) where inputs are fuzzy — then do the actual
*comparison* and *verdict logic* in deterministic Python. This is what gets exact-field
precision on the 50%-weighted end-to-end metric and makes results auditable/reproducible.

**Everything runs in Docker.** Both `web` and `api` are containers on one
`docker-compose` network; the provided scoring server is an optional third service for
dev. Kubernetes is a later-stage migration path (same images, k8s manifests/Helm) — not
needed for prelim.

---

## 2. Repository Layout

uv project already exists at repo root (`pyproject.toml`, `.python-version` = 3.13,
`uv.lock`). Python code lives under `api/`; the web app under `web/` is a **pnpm**
project (`package.json` + `pnpm-lock.yaml`).

```
averis-hackathon/
├── pyproject.toml              # uv-managed deps (single project, root level)
├── uv.lock
├── .python-version             # 3.13
├── .env                        # NEON_DB_URI, OPENROUTER_API_KEY  (gitignored)
├── .env.example                # key names only
├── docker-compose.yml          # web + api + scorer (dev)
├── api/
│   ├── Dockerfile              # uv-based image (see §9)
│   ├── app/
│   │   ├── main.py             # routes: /api/emails, /api/runs, /api/review...
│   │   ├── db.py               # async engine/session (asyncpg + SQLAlchemy)
│   │   ├── models.py           # SQLAlchemy tables
│   │   ├── schemas.py          # Pydantic DTOs
│   │   ├── llm.py              # OpenAI client → OpenRouter + JSON-parse helpers
│   │   └── routers/            # emails.py, pipeline.py, review.py, exports.py
│   ├── pipeline/
│   │   ├── ingest.py           # load bundle inbox/attachments → DB
│   │   ├── classify.py         # rules → LLM fallback → category + decided_by
│   │   ├── readers/            # txt.py, pdf.py, docx.py, xlsx.py, ocr.py
│   │   ├── extract.py          # LLM structured extraction → 7 fields
│   │   ├── compare.py          # normalization + field diff (deterministic)
│   │   ├── escalate.py         # NEEDS_REVIEW reason detection
│   │   ├── verdict.py          # assemble per-email result
│   │   └── submission.py       # build submission.json, POST /submit
│   ├── tests/                  # pytest: normalization, extraction fixtures, e2e
│   └── alembic/                # migrations
├── web/                        # Next.js 15 (App Router, TS, Tailwind + shadcn/ui)
│   ├── Dockerfile
│   ├── app/
│   │   ├── page.tsx            # dashboard: queue counts + verdict summary
│   │   ├── inbox/page.tsx      # filterable email list (by queue/verdict)
│   │   ├── emails/[id]/page.tsx# detail: email + extracted fields + diff table
│   │   ├── review/page.tsx     # NEEDS_REVIEW queue with confirm/correct
│   │   └── runs/page.tsx       # submission runs + scoreboard history
│   └── lib/api.ts              # typed fetch client → FastAPI
├── data/                       # copy/mount of sdoc-hackathon-bundle (gitignored)
└── plans/
```

**uv workflow:** `uv add fastapi uvicorn sqlalchemy[asyncio] asyncpg alembic openai
pydantic pypdf python-docx openpyxl pypdfium2 tenacity httpx` and
`uv add --dev pytest ruff mypy`. All Python commands run via `uv run` (e.g.
`uv run pytest`, `uv run uvicorn app.main:app`). `uv sync --frozen` inside the Dockerfile
reproduces the lockfile exactly — no `requirements.txt` needed.

---

## 3. Data Model (Neon Postgres)

Serverless Postgres over `NEON_DB_URI` (pooled connection string, already in `.env`).
SQLAlchemy 2.x async + asyncpg; Alembic for migrations (`uv run alembic upgrade head`
on api container start).

```sql
emails                -- raw inbox records (source of truth = provided JSON)
  email_id        text PK          -- 'email_004'
  sender          text
  subject         text
  body            text
  attachments     jsonb            -- ['attachments/email_004_SI.txt', ...]
  ingested_at     timestamptz

pipeline_results      -- one row per email per pipeline run
  id              uuid PK
  run_id          uuid FK → runs.id
  email_id        text FK → emails.email_id
  category        text             -- 5 queues
  decided_by      text             -- 'rule' | 'llm' (feeds rule_pct cost metric)
  si_fields       jsonb            -- {shipper, consignee, ...} extracted from SI
  bl_fields       jsonb            -- same shape from BL
  doc_types       jsonb            -- detected type per attachment
  status          text             -- OK | MISMATCH | NEEDS_REVIEW | PENDING | FAILED
  review_reason   text             -- wrong_doc_type|missing_attachment|unreadable|missing_value
  has_defect      boolean
  defect_fields   text[]           -- canonical field names
  evidence        jsonb            -- snippets shown to human reviewer
  error           text             -- processing failure detail (for retries)
  created_at      timestamptz

reviews               -- human-in-the-loop actions
  id              uuid PK
  result_id       uuid FK → pipeline_results.id
  action          text             -- confirm | override_status | override_fields
  payload         jsonb            -- corrected values
  reviewer        text
  created_at      timestamptz

runs                  -- each full/partial pipeline execution
  id              uuid PK
  label           text
  started_at      timestamptz
  finished_at     timestamptz
  stats           jsonb            -- counts by category/status
  score           jsonb            -- last /submit scoreboard response
```

Why Postgres over flat files: the UI needs filterable state (queues, review status, run
history), human overrides must persist, and Neon satisfies the "meaningful cloud
infrastructure" rubric cleanly.

---

## 4. Pipeline Design

Single orchestrator `run_pipeline(email_ids=None)` executed as a FastAPI background task
(or `uv run python -m pipeline.run` CLI for batch). Per email, stages are **resumable** —
each stage writes to `pipeline_results`, so retries only redo what failed.

### 4.0 LLM client (`llm.py`) — OpenRouter via OpenAI SDK

```python
from openai import OpenAI

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ["OPENROUTER_API_KEY"],          # already in .env
    default_headers={                                 # optional but recommended
        "HTTP-Referer": "https://github.com/<team>/averis-hackathon",
        "X-Title": "SDOC Verifier",
    },
)

TEXT_MODEL   = "nvidia/nemotron-3-ultra-550b-a55b:free"   # classification + extraction
VISION_MODEL = "nvidia/nemotron-nano-12b-v2-vl:free"      # cheapest image-capable on OR
```

**Two OpenRouter-specific caveats baked into `llm.py`:**

- **`:free` models are rate-limited** (~50–200 req/day depending on account) and single-
  provider (lower uptime SLA). So: aggressive caching by content hash, small semaphore
  (3–5 concurrent), `tenacity` backoff on 429/5xx, and rules-first logic to keep the call
  count down (see budget math in §7).
- **Structured outputs aren't guaranteed** on community-hosted models. Don't rely on
  `chat.completions.parse`; instead ask for a JSON object in the prompt and parse
  defensively:

```python
def llm_json(messages, model=TEXT_MODEL, schema=None):
    resp = client.chat.completions.create(model=model, messages=messages, temperature=0)
    raw = resp.choices[0].message.content
    return pydantic_validate(extract_json_block(raw), schema)   # strip ``` fences, retry once on parse fail
```

### 4.1 Ingest (`ingest.py`)

- Read bundle via `loader.Inbox("data")` (or `Inbox("http://scorer:8080")` inside compose —
  identical API, service name instead of localhost).
- Upsert all 520 records into `emails`; stash attachment bytes under `data/attachments/`
  mounted into the api container (S3 as the scale path).
- Create a `run` row; enqueue each email as `PENDING`.

### 4.2 Classification (`classify.py`) — *two tiers*

**Tier A — deterministic rules (free, instant, auditable):**

```python
# signals: sender domain, subject keywords, attachment count
if sender_domain in SPAM_DOMAINS or re.search(SPAM_PATTERNS, subject): -> SPAM
if re.search(r"(invoice|billing|charges|GR\b|D&D|freight)", subj+body, I) and no docs -> INVOICE_QUERY
if re.search(r"(request si|si needed|cust si|shipping instruction for)", subj, I) and no BL att -> SI_REQUEST
if has_SI_and_BL_attachments or re.search(r"(confirm docs|bl draft|check.*bl|compare)", subj+body, I) -> BL_COMPARISON
else -> GENERAL
```

Emit `decided_by="rule"` — the scorer reports `rule_pct`, a nice cost-efficiency talking
point (and it saves OpenRouter quota — see §7).

**Tier B — LLM fallback** for unconfident cases (ambiguous subjects, misleading subjects
like `email_011`):

```python
result = llm_json(
    model=TEXT_MODEL,
    messages=[{"role":"system","content":CLASSIFY_SYS},
              {"role":"user","content":f"From:{e.sender}\nSubject:{e.subject}\n\n{e.body[:3000]}"}],
    schema=Classification,   # category + confidence + rationale
)
```

- Guard: attachment presence is a hard signal — if 2 docs attached AND body asks to check,
  bias to BL_COMPARISON regardless of a weird subject.
- Store rationale in `evidence` for the UI ("why this queue").

### 4.3 Document readers (`readers/`)

Uniform interface: `read(path) -> DocText(text, doc_type_hint, readable: bool, meta)`.

| Format | Tool | Notes |
|---|---|---|
| `.txt` | stdlib read | trivial |
| `.pdf` | `pypdf`/`pdfplumber` text layer | if extracted text ≈ empty → image-only → OCR path |
| `.docx` | `python-docx` | tables → row-joined text (handles bilingual 中文 labels) |
| `.xlsx` | `openpyxl` | cells → `label: value` lines |
| scanned/empty/garbled | render page (`pypdfium2`) → **VISION_MODEL** (`nvidia/nemotron-nano-12b-v2-vl:free`) image input | or mark `unreadable` if OCR confidence low |

Every reader returns `readable=False` on corrupt/empty input → feeds `unreadable`
escalation rather than a crash.

### 4.4 Extraction (`extract.py`)

Per document (SI and BL separately), one LLM call requesting a JSON object:

```python
class ShipmentFields(BaseModel):
    doc_type: Literal["SI","BL","invoice","packing_list","coo","unknown"]
    shipper: str | None
    consignee: str | None
    notify_party: str | None
    port_of_loading: str | None
    port_of_discharge: str | None
    container_count: int | None        # just the number; ignore size suffix
    gross_weight_kg: float | None      # normalized to kg, separators stripped
    missing_fields: list[str]          # fields present-but-blank (???, TBA, N/A, ____)
```

- System prompt carries the **label-synonym table** (`To the Order of` → consignee,
  `Load Port`/`POL` → port_of_loading, `Gross Weight毛重(KGS)` → gross_weight_kg, …) plus
  doc-type cues ("BILL OF LADING (DRAFT)" vs "COMMERCIAL INVOICE").
- `doc_type` doubles as the `wrong_doc_type` detector (SI + Commercial Invoice pair → escalate).
- `missing_fields` drives `missing_value` escalation.
- Model: `TEXT_MODEL` for text docs; `VISION_MODEL` for scanned pages. Temperature 0.

### 4.5 Comparison (`compare.py`) — *deterministic*

```python
def norm_party(s):  # shipper/consignee/notify
    return re.sub(r"[^A-Z0-9]", "", s.upper())          # drop punctuation/spacing

def norm_port(s):   # 'NANTONG, CHINA (CNNTG)' → 'NANTONGCHINA'
    return norm_party(s)                                # codes appended are consistent

def verdict(si, bl):
    diffs = [f for f in COMPARE_FIELDS if norm(si[f]) != norm(bl[f])]
    return ("MISMATCH", diffs) if diffs else ("OK", [])
```

Never let the LLM judge equality — a near-miss normalization bug (trailing spaces,
`131,058` vs `131058`) is exactly what loses end-to-end points.

### 4.6 Escalation logic (`escalate.py`)

Checked **before** comparison, in order:

| Reason | Detection |
|---|---|
| `missing_attachment` | Body requests a *comparison* ("compare/check the SI and draft BL", "TO CONFIRM DOCS" style) **and** `len(attachments) < 2` — NB: body says *"send the draft BL for checking"* → **not** escalation, it's an awaiting-docs request (status OK) |
| `wrong_doc_type` | Either attachment's extracted `doc_type` ∉ {SI, BL} |
| `unreadable` | Any required attachment returns `readable=False` (empty file, corrupt PDF, image-only PDF with OCR disabled/low-confidence) |
| `missing_value` | Both docs readable, both correct types, but a compared field is blank/`???`/`TBA`/`N/A`/`____` |

Output → `status=NEEDS_REVIEW`, `review_reason`, `evidence` (file names, blank field names,
detected doc type) for the review UI.

### 4.7 Submission & scoring (`submission.py`)

```python
sub = {r.email_id: {"category": r.category, "status": r.status,
                    "review_reason": r.review_reason, "has_defect": r.has_defect,
                    "defect_fields": r.defect_fields, "decided_by": r.decided_by}
       for r in run.results}
assert set(sub) == {f"email_{i:03d}" for i in range(1, 521)}   # all 520 present
scoreboard = Inbox("http://scorer:8080").submit(sub)            # POST /submit (compose DNS)
runs.score = scoreboard                                         # persist history
```

Dev loop: run pipeline → submit → inspect `stage1.confusion` + `stage3` + `reliability` →
fix → resubmit (unlimited). The organizer kit also ships `data_v2/ground_truth.json` +
`score_cli.py`, enabling fully-offline eval during dev — use it for debugging/validation,
but never hardcode answers into the pipeline.

---

## 5. FastAPI Surface (consumed by the UI)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/emails?queue=&status=&q=` | paginated inbox list with verdict badges |
| GET | `/api/emails/{id}` | email + extracted SI/BL fields + diff + evidence |
| POST | `/api/pipeline/run` | start a run (`{email_ids?}` → background task) |
| GET | `/api/runs` / `/api/runs/{id}` | run status, stats, scoreboard history |
| GET | `/api/review` | NEEDS_REVIEW + FAILED queue |
| POST | `/api/review/{result_id}` | human confirm/override → recompute verdict |
| GET | `/api/export/submission?run_id=` | download submission.json |
| POST | `/api/export/submit?run_id=` | push to scoring server, store scoreboard |

Processing: FastAPI `BackgroundTasks` is enough at 520 emails; parallelism via
`asyncio.gather` with a **small semaphore (3–5)** — deliberately conservative because the
free tier rate-limits — plus `tenacity` retries on 429/5xx. Failures land in
`status=FAILED` with `error` — retryable from the UI, satisfying "handle processing
failures visibly and allow retries".

---

## 6. Next.js UI (what judges see)

- **`/` dashboard** — queue counts (5 cards), verdict donut (OK/MISMATCH/NEEDS_REVIEW),
  latest run's scoreboard metrics. Business framing: "this morning's inbox, triaged".
- **`/inbox`** — table: sender, subject, queue badge, verdict badge, `decided_by` chip
  (rule=green "free", llm=blue). Filters per queue/status.
- **`/emails/[id]`** — the money screen: original email, detected doc types, and the
  **7-row diff table** (Field | SI value | BL value | ✓/✗), mismatched rows highlighted;
  verdict banner ("No mismatch detected" / "2 fields differ" / "Escalated: unreadable BL").
- **`/review`** — escalation inbox: reason chip, evidence (e.g. "attachment is a Commercial
  Invoice"), buttons **Confirm** / **Override**. Demonstrates human-in-the-loop end-to-end.
- **`/runs`** — pipeline runs with duration, per-category counts, and the `/submit`
  scoreboard; "Export submission.json" button.

The web container talks to `http://api:8000` server-side (compose network) and exposes
`NEXT_PUBLIC_API_URL` for any client-side fetches.

---

## 7. LLM Usage Map (OpenRouter)

| Task | Model | Pattern | Why |
|---|---|---|---|
| Email classification (fallback) | `nvidia/nemotron-3-ultra-550b-a55b:free` | JSON-mode prompt, temp 0 | free, strong reasoning |
| Doc-type detection + field extraction | `nvidia/nemotron-3-ultra-550b-a55b:free` | JSON object per doc | synonym labels need semantic mapping |
| Scanned PDF reading | `nvidia/nemotron-nano-12b-v2-vl:free` | image → same ShipmentFields JSON | cheapest image-capable model on OpenRouter; built for OCR/document intelligence |
| Comparison / verdict | **none** | pure Python | determinism = exact-field precision |

**Quota budget (free tier):** a full run needs roughly —
~100–300 classification fallbacks (most emails resolved by rules) + ~250 extractions
(124 doc pairs × 2) + a handful of vision calls. Cache every LLM response keyed by
content hash (`pipeline_results` + a `llm_cache` table or on-disk) so re-runs after code
changes don't re-spend quota; do dev iteration on small email subsets.

A `pipeline/config.py` flag set (`fast/cheap` vs `accurate`) plus the `decided_by` rule_pct
metric are good slide-deck talking points on cost engineering.

---

## 8. Testing & Evaluation

- **Unit (`uv run pytest`):** normalization (`norm_party`/`norm_port`/weight parsing),
  label-synonym fixtures (one per LABELS variant), compare() truth table, escalation
  detectors (fixture emails for all 4 reasons + the "send BL" negative case), and the
  `llm_json` parser (fenced/garbled/partial JSON).
- **Golden fixtures:** freeze `email_001` (OK), `email_004` (MISMATCH), `email_501/506/511/516`
  (all 4 reasons) as regression tests — they're the documented reference IDs.
- **Eval harness:** `uv run pytest tests/test_eval.py` → run pipeline on all 520 →
  POST /submit → assert `final_score` doesn't regress; store per-run scoreboard for the
  `/runs` page.
- **CI:** GitHub Actions — `uv sync --frozen`, `ruff check`, `mypy`, `pytest`; web:
  `pnpm install --frozen-lockfile` + `pnpm build`; `docker compose build` as the
  packaging check.

---

## 9. Deployment

**Now: docker-compose.** One file brings up the whole product locally or on a single VM:

```yaml
services:
  api:
    build: ./api                 # uv-based Dockerfile below
    env_file: .env               # NEON_DB_URI, OPENROUTER_API_KEY
    volumes: [./data:/data:ro]
    ports: ["8000:8000"]
  web:
    build: ./web                 # node:22-alpine + corepack pnpm → install → build → start
    environment: { NEXT_PUBLIC_API_URL: http://localhost:8000, API_URL: http://api:8000 }
    ports: ["3000:3000"]
    depends_on: [api]
  scorer:                        # dev-only; the provided server
    build: ./docs-provided/problem-statement/sdoc-hackathon-docker/server
    volumes:
      - ./docs-provided/problem-statement/sdoc-hackathon-docker/data_v2:/data:ro
      - ./docs-provided/problem-statement/sdoc-hackathon-docker/data_v2/ground_truth.json:/secrets/ground_truth.json:ro
    ports: ["8080:8000"]
```

`api/Dockerfile` (uv-native, reproducible from lockfile):

```dockerfile
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev
COPY api/ ./api/
WORKDIR /app/api
CMD ["uv", "run", "--no-dev", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

| Piece | Host | Notes |
|---|---|---|
| Next.js | container (compose) — Vercel optional later | talks to api over compose network |
| FastAPI | container (compose) — single VPS / Railway / Render | same image everywhere |
| Postgres | **Neon** (managed) | `NEON_DB_URI`, no db container needed |
| LLM | **OpenRouter** | `OPENROUTER_API_KEY` server-side only, never in the browser |
| Scoring server | compose service | dev/eval tool, not part of the product story |

**Later: Kubernetes.** Same two images → Deployment + Service per tier, `api` behind an
Ingress; secrets via k8s Secrets; a CronJob can run batch pipeline re-runs. Compose stays
the dev path — the migration is config, not code. Worth mentioning on the roadmap slide
(Architecture & Scalability points) without building it for prelim.

For the demo, pre-run the pipeline and persist results — live-reprocessing 520 emails on
stage is a demo risk (especially against a rate-limited free model); show incremental
re-runs on a handful of emails instead.

---

## 10. Build Order (maps to hackathon phases)

**Prelim (by 22 Sep 12:00) — "semi-working prototype":**
1. uv deps + Dockerfiles + compose up (api healthy, web shell, scorer reachable)
2. Ingest → DB; `.txt` reader
3. classify (rules + Nemotron fallback) → extract → compare → verdict for txt pairs
4. submission.json + `/submit` loop working; first real scoreboard
5. Minimal UI: inbox list + per-email diff view
6. Deploy compose to a VM (or api/web hosts), record ≤5-min video, slides

**Final (by 26 Sep) — "working prototype":**
7. pdf/docx/xlsx readers; all 4 escalation detectors + review UI
8. Vision-model OCR path via `nemotron-nano-12b-v2-vl` (show a scanned PDF being read —
   even if scoring prefers escalation, it's a strong differentiator demo)
9. Run history/scoreboard page, retries, audit trail
10. Harden: tests green in CI, error states, demo script rehearsed
11. (Stretch) k8s manifests for the two services — roadmap credibility

---

## 11. Key Technical Risks

| Risk | Mitigation |
|---|---|
| OpenRouter `:free` rate limits (~50–200 req/day) + single-provider uptime | rules-first classification, response caching by content hash, small semaphore, tenacity backoff, dev on subsets |
| Free/community model doesn't honor strict structured outputs | `llm_json` wrapper: prompt-for-JSON + fence-stripping + pydantic validation + one repair retry; never trust raw text |
| `:free` model IDs rotate/get deprecated | model names in `config.py`/env, not hardcoded; eval run flags regressions |
| LLM extracts slightly different spellings across SI/BL → false mismatch | normalize in code; still compare in Python, never by LLM judgment |
| False `missing_attachment` escalation on "send me the BL" emails | body-intent check is a rule, tested against `email_003`-style fixtures |
| Vision OCR latency on image PDFs | only on unreadable path; small n in dataset |
| Demo-day cold starts / quota exhaustion | pre-run pipeline, persisted results, warm-up ping; show re-runs on 1–3 emails |
