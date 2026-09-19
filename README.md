# SDOC Verifier

AI copilot for shipping-document operations (hackathon prototype).

It triages a shipping-operations inbox into five queues and, for
Bill-of-Lading check requests, compares the Shipping Instruction against the
draft BL across seven fields — flagging exact mismatches or escalating
untrustworthy documents to human review.

---

## 1. System architecture

```
                            docker compose network
 ┌───────────────────────────────────────────────────────────────────────┐
 │                                                                       │
 │   browser                                                             │
 │     │  http://localhost:3000                                          │
 │     ▼                                                                 │
 │  ┌─────────────┐   server-side fetch (compose DNS)                    │
 │  │     web     │ ──────────────────────────────┐                      │
 │  │  Next.js 15 │                               ▼                      │
 │  │  pnpm       │                        ┌─────────────┐               │
 │  └──────┬──────┘                        │     api     │               │
 │         │ browser calls                │  FastAPI    │               │
 │         │ NEXT_PUBLIC_API_URL          │  uv / py3.13│               │
 │         └─────────────────────────────►│  :8000      │               │
 │              http://localhost:8000     └──────┬──────┘               │
 │                                             │    │                   │
 └─────────────────────────────────────────────┼────┼───────────────────┘
                                               │    │
              ┌────────────────────────────────┘    └───────────────┐
              ▼                                                     ▼
     ┌─────────────────┐   TLS    ┌──────────────┐   HTTPS   ┌──────────────┐
     │     scorer      │          │  Neon        │           │  OpenRouter  │
     │ provided eval   │          │  Postgres    │           │  nemotron    │
     │ server :8000    │          │  (managed)   │           │  models      │
     │ (dev only)      │          └──────────────┘           └──────────────┘
     └─────────────────┘
      api reaches it as
      http://scorer:8000
```

| Service | Image base | Port | Purpose |
|---|---|---|---|
| `web` | node:22-alpine + corepack pnpm | 3000 | Dashboard, inbox, diff view, review queue, runs |
| `api` | astral-sh/uv python3.13 | 8000 | Pipeline, REST API, Neon access |
| `scorer` | python:3.12-slim (provided) | 8080→8000 | Evaluation against private ground truth |
| Neon | managed | — | `emails`, `runs`, `pipeline_results`, `reviews` |
| OpenRouter | managed | — | text model + vision model |

The compose `api` service mounts `docs-provided/.../sdoc-hackathon-bundle`
read-only at `/data` (inbox JSON + attachments) and reads secrets from
`.env` (`NEON_DB_URI`, `OPENROUTER_API_KEY`).

---

## 2. Pipeline — "LLMs read, code decides"

```
 inbox/*.json                 attachments/*
      │                            │
      ▼                            │
 ┌─────────┐                        │
 │ INGEST  │  Email rows ──────────►│ Neon
 └────┬────┘                        │
      │ per email                   │
      ▼                             │
 ┌───────────┐  cues: subject/body/  │
 │ CLASSIFY  │  attachment names     │
 │ rules 1st │───────────────────────┤
 └────┬──────┘                       │
      │ BL_COMPARISON?               │ GENERAL / SI_REQUEST /
      │                              │ INVOICE_QUERY / SPAM → done
      ▼                              │
 ┌───────────┐   ┌─────────────┐     │
 │   READ    │──►│  readers/   │     │
 │ *_SI,*_BL │   │ txt pdf     │     │
 └────┬──────┘   │ docx xlsx   │     │
      │          │ ocr(vision) │     │
      │          └─────────────┘     │
      ▼ DocText(text, readable)      │
 ┌───────────┐                       │
 │ DETECT    │ title first, body     │
 │ DOC TYPE  │ fallback              │
 └────┬──────┘                       │
      ▼                             │
 ┌───────────┐  label synonyms →     │
 │ EXTRACT   │  7 canonical fields   │
 │ regex+LLM │  (block + inline)     │
 └────┬──────┘                       │
      ▼ si_fields / bl_fields        │
 ┌───────────┐                       │
 │ ESCALATE? │── NEEDS_REVIEW ──────►│
 └────┬──────┘  (4 reasons)          │
      │ all clear                    │
      ▼                              │
 ┌───────────┐  normalized exact     │
 │ COMPARE   │  match per field      │
 └────┬──────┘                       │
      ▼                              │
   OK | MISMATCH + defect_fields ──► │
                                     ▼
                            pipeline_results →
                            submission JSON → scorer
```

**The AI/code boundary:** models only do *perception* — classification
fallback, extraction fallback, vision OCR. Comparison, normalization,
verdicts, and escalation are pure Python, because the score needs exact
defect-field sets, not vibes.

---

## 3. Verdict decision tree

```
category == BL_COMPARISON?
 ├── no  → status OK (triaged only)
 │
 └── yes → SI + BL attachments present?
           ├── no → body asks to COMPARE (not just "send me the BL")?
           │        ├── yes → NEEDS_REVIEW / missing_attachment
           │        └── no  → OK            (awaiting docs — not a defect)
           │
           └── yes → both files readable?
                     ├── no → OCR enabled & succeeds?
                     │        ├── yes → continue with OCR fields
                     │        └── no  → NEEDS_REVIEW / unreadable
                     │
                     └── yes → doc types == SI + BL?
                               ├── no → NEEDS_REVIEW / wrong_doc_type
                               │        (invoice/packing-list/CdO attached
                               │         where SI or BL expected)
                               └── yes → all 7 fields extracted?
                                         ├── no → NEEDS_REVIEW / missing_value
                                         └── yes → COMPARE
                                                   ├── all equal → OK
                                                   └── diffs → MISMATCH
                                                       + defect_fields[]
```

Escalation reasons cover the real-world failure modes: an invoice mislabeled
as `*_BL.pdf`, a pair that never arrived, a corrupted/scanned file, and a
document with blank fields. Nothing silently produces a wrong answer.

---

## 4. The 7 compared fields & label synonyms

| Canonical field | SI labels | BL labels |
|---|---|---|
| `shipper` | Shipper, Shipper/Exporter | Shipper (Principal or Seller) |
| `consignee` | Consignee | Consignee (Non-Negotiable), To the Order of |
| `notify_party` | Notify Party | Notify, Notify Party/Intermediate Consignee |
| `port_of_loading` | Port of Loading, POL | Load Port, Port of Shipment |
| `port_of_discharge` | Port of Discharge, POD | Discharge Port, Place of Delivery |
| `container_count` | No. of Containers | Total Containers, "3 x 40'HC" → 3 |
| `gross_weight_kg` | Gross Weight (KG) | Gross Wt (kgs), 毛重 bilingual labels |

**Normalization** (`pipeline/compare.py`): parties/ports → strip
punctuation+case → `BIGBUYERLLC`; numbers → drop comma grouping. A 0.5 kg
difference *is* a defect — formatting noise is not.

---

## 5. Scoring & submission flow

```
 POST /api/pipeline/run          POST /api/export/submit?run_id=…
        │                                    │
        ▼                                    ▼
   run_pipeline()                    build_submission()
   for each email:                   {email_id: {category, status,
     process_email() ──► pipeline_results     review_reason, has_defect,
                                              defect_fields, decided_by}}
                                              │
                                              ▼ POST /submit
                                          scorer service
                                              │
        ┌─────────────────────────────────────┤
        ▼                                     ▼
   run.stats (category:status      run.score =
   counts persisted on Run)        stage1 macro-F1 · stage3 defect-F1 ·
                                   end-to-end rate · escalation p/r
                                   → FINAL = .30·F1 + .20·defF1 + .50·e2e
```

Current score on the provided dataset: **final 1.0** — classification
macro-F1 1.0, defect F1 1.0, end-to-end 46/46, escalation precision and
recall 1.0 (20/20 review cases, all 4 reasons caught).

---

## 6. Data model

```
 emails                          runs
 ├─ email_id PK ('email_004')    ├─ id UUID PK
 ├─ sender, subject, body        ├─ label, started_at, finished_at
 ├─ attachments JSONB            ├─ stats  JSONB  (category:status counts)
 └─ ingested_at                  └─ score  JSONB  (scorer response)
                                        │
 pipeline_results                       │ run_id FK
 ├─ id UUID PK              ────────────┘
 ├─ email_id FK ──► emails
 ├─ category, decided_by ('rule'|'llm')
 ├─ si_fields / bl_fields JSONB        reviews
 ├─ doc_types, evidence JSONB          ├─ id UUID PK
 ├─ status, review_reason              ├─ result_id FK ──► pipeline_results
 ├─ has_defect, defect_fields[]        ├─ action (confirm | override_status
 └─ error                              │            | override_fields)
                                        ├─ payload JSONB, reviewer
                                        └─ created_at
```

Latest-run joins power every screen; old runs are kept for the scoreboard
and audit trail. Human reviews write `reviews` rows and can override a
result's status/defect fields without re-running the pipeline.

---

## 7. LLM assists (opt-in)

Free-tier OpenRouter models via the OpenAI SDK. Off by default so scoring
runs stay deterministic and quota-safe.

| Flag | Trigger | Model |
|---|---|---|
| `ENABLE_LLM_CLASSIFY` | rules return no-cue GENERAL | `nvidia/nemotron-3-ultra-550b-a55b:free` |
| `ENABLE_LLM_FILL` | some fields blank after parse | same |
| `ENABLE_VISION_OCR` | PDF has no text layer | `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` |
| *(always on)* | parse found **zero** fields → unknown layout | text model rescues |

`llm_json` hardening: prompt-for-JSON → strip code fences → slice the
`{...}` block → pydantic-style validation → one repair retry → tenacity
backoff. Raw model output never decides a verdict.

**Demo without flags:** `GET /api/pipeline/llm-assist/{email_id}` runs the
models live on one email (classification + extraction + OCR) and returns
what the AI saw — the web UI exposes it as the "Run AI assist" panel.

---

## 8. Repository layout

```
.
├── docker-compose.yml          web + api + scorer
├── pyproject.toml / uv.lock    root Python project (uv)
├── api/
│   ├── Dockerfile              uv sync --frozen --no-dev
│   ├── app/
│   │   ├── main.py             lifespan + middleware + router mount
│   │   ├── core/config.py      pydantic-settings (env, models, flags)
│   │   ├── db/                 session.py (engine/Base) + models.py
│   │   ├── api/                deps + router + routes/ (thin HTTP layer)
│   │   ├── schemas/            pydantic request/response DTOs
│   │   ├── repositories/       all SQL — routes contain none
│   │   └── services/           llm.py (OpenRouter) + review.py (mutations)
│   ├── pipeline/               ingest → classify → readers → extract
│   │   └── readers/            → escalate → compare → submit
│   │       └── ocr.py          vision-model path (pypdfium2 render)
│   └── tests/                  28 fixtures — golden + anti-overfit, no DB/network
├── web/
│   ├── Dockerfile              pnpm install --frozen-lockfile + build
│   ├── app/                    / inbox emails/[id] review runs
│   └── lib/api.ts              typed fetch layer
└── plans/                      requirements + technical plan docs
```

---

## 9. Run it

```bash
# .env needs NEON_DB_URI + OPENROUTER_API_KEY
docker compose up --build
```

- web → http://localhost:3000 · api → http://localhost:8000 (`/docs`) ·
  scorer → http://localhost:8080

```bash
# first-time data load, then a full pipeline run + score
docker compose exec api uv run python -m pipeline.ingest
docker compose exec api uv run python -m pipeline.run
docker compose exec api uv run python -c \
  "import asyncio; from pipeline.submission import submit; \
   print(asyncio.run(submit('<run_id>')))"
```

Local dev without Docker: `uv sync` · `cd web && pnpm install` ·
`uv run uvicorn app.main:app --app-dir api --reload` · `cd web && pnpm dev`.

Tests: `uv run pytest api/tests -v`.
