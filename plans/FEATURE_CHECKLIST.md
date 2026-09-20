# Feature Checklist

Status of every planned feature. `[x]` = implemented and verified;
`[ ]` = planned / not yet built. Sources: `plans/REQUIREMENTS_PLAN.md`,
`plans/TECHNICAL_PLAN.md`, current code, and live verification.

Legend for verification: 🟢 verified live · 🧪 covered by tests ·
`path` = implementing code.

---

## 1. Ingestion & data layer

- [x] Inbox ingest: 520 email JSONs → Neon `emails` table
  `api/pipeline/ingest.py` · 🟢 (`POST` ingest verified, 520 rows)
- [x] Attachment metadata stored per email (`attachments` JSONB)
  `api/app/db/models.py`
- [x] Neon Postgres (async SQLAlchemy + asyncpg, sslmode handled)
  `api/app/db/session.py` · 🟢 `NEON OK: 1`
- [x] Runs recorded with per-run stats + scorer response
  `runs` table, `api/pipeline/submission.py:45-49` · 🟢
- [x] Pipeline results persisted per email per run (category, status,
  extracted fields, evidence, defect fields, decided_by)
  `pipeline_results` table · 🟢
- [x] Human review actions persisted (`reviews` table + result mutation)
  `api/app/services/review.py` · 🟢 POST verified
- [x] Manual email intake — dedicated `/inbox/new` page: field-by-field
  form or .txt/.json sample-format import, with real document uploads
  (files persist to `UPLOAD_DATA_DIR`, paired by content — no path/name
  conventions needed); ids assigned `manual_*` so uploads can't overwrite
  bundle records `POST /api/emails` + `web/app/inbox/new/` · 🧪
- [ ] Alembic migrations (currently `create_all` on startup)
- [ ] Multi-run comparison view (diff between two runs)

## 2. Email classification (5 queues)

- [x] Rules-first classifier → BL_COMPARISON / SI_REQUEST / INVOICE_QUERY /
  GENERAL `api/pipeline/classify.py` · 🧪
- [x] SPAM queue → measured word TF-IDF + logistic-regression model in
  `api/ml/`; the old domain-blocklist/regex rules were removed. Experiments,
  limitations, reproducible training, packaged artifact, API route, and model
  failure behavior are covered by tests · 🧪
- [x] `decided_by` marker (`rule` / `llm` / `ml`) for cost diagnostics
- [x] Attachment-name + coded-subject cues (e.g. `AFRT - LONG BEACH_US`,
  `*_SI.*` / `*_BL.*` names)
- [x] Filename-independent doc pairing — SI/BL identified by detected
  content type when names carry no signal `verdict._si_bl_by_content` · 🧪
- [x] "Send me the BL" intent detected separately — treated as awaiting
  docs, **not** an escalation `COMPARE_INTENT_RE` vs `SEND_BL_INTENT_RE` · 🧪
- [x] LLM classification fallback for the no-cue GENERAL bucket
  `classify_llm()` behind `ENABLE_LLM_CLASSIFY` · 🟢 (live-verified verdicts)
- [x] LLM response cache keyed by content hash — parsed replies stored
  under `.cache/llm`, so a rerun over the same document costs nothing
  `llm.cache_read/cache_write`, `ENABLE_LLM_CACHE` · 🧪
- [ ] Bounded-concurrency LLM batch (semaphore) — runs are sequential today

## 3. Document reading

- [x] `.txt` reader `api/pipeline/readers/__init__.py`
- [x] `.pdf` text-layer reader (`pypdf`)
- [x] `.docx` reader (`python-docx`, tables → `label: value` lines)
- [x] `.xlsx` reader (`openpyxl`)
- [x] `readable=False` contract — corrupt/empty/image-only feeds escalation
  instead of crashing · 🧪 (`email_511` unreadable)
- [x] Vision OCR path: `pypdfium2` render → PNG → vision model
  `api/pipeline/readers/ocr.py` behind `ENABLE_VISION_OCR` ·
  🟢 (nemotron omni read all 7 fields off a rendered BL live)
- [ ] OCR confidence scoring / partial-page handling (currently all-or-none)

## 4. Document-type detection

- [x] Title-line-first detection (SI / BL / invoice / packing_list / coo)
  `detect_doc_type()` · 🧪 🟢
- [x] Mislabeled-attachment detection — `*_BL.pdf` containing an invoice
  detected as `invoice`, not BL (fixed: body scan no longer trusts
  "NOT A SHIPPING INSTRUCTION" text) · 🧪 🟢 `email_501`

## 5. Field extraction (7 canonical fields)

- [x] shipper · consignee · notify_party · port_of_loading ·
  port_of_discharge · container_count · gross_weight_kg
  `api/pipeline/extract.py` · 🧪 🟢
- [x] Label-synonym map (POL / Load Port / To the Order of / bilingual
  毛重 / Gross Wt (kgs) …) — normalized labels, not regex-on-raw · 🧪
- [x] Two layouts: inline `Label: value` and PDF block layout
  (label line → next non-empty line)
- [x] Blank-token detection (`???`, `_______`, `TBA`, `TBD`,
  `TO BE ADVISED`, `N/A`, `NIL`, punctuation-only values) →
  `missing_value` candidates · 🧪 `email_516` + parametrized tokens
- [x] Numeric parsing with comma grouping (`61,234.5` → 61234.5) · 🧪
- [x] Container-size suffixes (`3 x 40'HC` → 3) · 🧪
- [x] LLM extraction fallback — fires when deterministic parse finds zero
  fields (unknown layout); `ENABLE_LLM_FILL` fills individually blank
  fields · `extract_fields_llm()` 🟢
- [ ] Extraction provenance UI (which line each field came from —
  evidence is stored, not yet rendered per-field)

## 6. Comparison & verdict (deterministic)

- [x] Party normalization: strip case + punctuation → exact match · 🧪
- [x] Port normalization: compare port name proper — `SHANGHAI, CHINA (CNSHA)`
  ≡ `SHANGHAI`; real port differences still flag · 🧪 `api/pipeline/compare.py`
- [x] Numeric equality on container_count / gross_weight_kg · 🧪
  (real differences flagged — 0.5 kg is a defect)
- [x] Exact defect-field list output (no fuzzy "similar" verdicts) · 🧪
- [x] Verdicts: `OK` / `MISMATCH` / `NEEDS_REVIEW` · 🧪 🟢
- [x] Scorer-shaped submission incl. `decided_by`
  `to_submission_entry()` · 🟢

## 7. Escalation (4 review reasons)

- [x] `wrong_doc_type` — invoice/etc. where SI or BL expected · 🧪 🟢 (5/5)
- [x] `missing_attachment` — explicit compare request, pair absent · 🧪 🟢 (5/5)
- [x] `unreadable` — corrupt/garbled/empty file · 🧪 🟢 (5/5)
- [x] `missing_value` — required field blank on a readable doc · 🧪 🟢 (5/5)
- [x] Awaiting-docs false-positive guard (compare intent ≠ send-request) · 🧪
- [ ] Confidence-graded escalation (e.g. low-OCR-confidence vs. hard-fail)

## 8. Scoring & evaluation

- [x] Submission builder → scorer `POST /submit`
  `api/pipeline/submission.py` · 🟢
- [x] Score persisted on the run (`runs.score` JSONB) · 🟢
- [x] Local eval against provided ground truth:
  **final 1.0** — classification macro-F1 1.0, defect F1 1.0,
  end-to-end 46/46, escalation precision/recall 1.0 · 🟢
- [x] `GET /api/export/submission?run_id=` (download JSON) · 🟢
- [x] `POST /api/export/submit?run_id=` · 🟢
- [x] CI on every push — fixtures + web build `.github/workflows/ci.yml`
- [ ] CI regression against the scorer (needs a hosted scorer + ground truth)

## 9. REST API

- [x] `GET /health` — Neon round-trip, model chain, assist switches and
  data dir; 503 when the database is unreachable, and never calls a model
  `api/app/main.py` · 🧪 🟢 (`emails_ingested: 520` live)
- [x] `GET /api/emails` — list joined to latest result; filters
  `queue` / `status` / `q` · 🟢
- [x] `POST /api/emails` — multipart intake: fields + document files,
  10 MB cap per file, assigns `manual_*` id · 🧪
- [x] `GET /api/emails/{id}` — detail + latest result (incl. `result_id`) · 🟢
- [x] `POST /api/pipeline/run` (background task; optional subset + label) · 🟢
- [x] `GET /api/runs`, `GET /api/runs/{id}` · 🟢
- [x] `GET /api/review` — NEEDS_REVIEW + FAILED queue · 🟢
- [x] `POST /api/review/{result_id}` — confirm / override_status /
  override_fields · 🟢
- [x] `GET /api/pipeline/llm-assist/{email_id}` — on-demand AI view
  (classify + extract + OCR; never persisted) · 🟢
- [x] `POST /api/spam/detect` — standalone spam check; 503 while no model
  artifact exists · 🧪
- [x] CORS for the web origin `api/app/main.py` · 🟢
- [ ] Auth / reviewer identity beyond a free-text field
- [ ] Rate limiting / request logging middleware

## 10. Web UI (Next.js + pnpm)

- [x] Dashboard `/` — queue counts, triage stats · 🟢
- [x] Inbox `/inbox` — full list, category/status/search filters · 🟢
- [x] Inbox pagination — 10 per page, numbered window + prev/next,
  filters/search preserved across pages · 🟢
- [x] "Add email" subpage `/inbox/new` — manual fields, document attach
  chips, sample-format file import · 🟢
- [x] Email detail `/emails/[id]` — verdict card, sender, rationale · 🟢
- [x] SI-vs-BL diff table — 7 rows, mismatches highlighted with both
  values side by side · 🟢 (renders email_004's real mismatch)
- [x] Detected doc types + evidence + error display on detail page · 🟢
- [x] Review queue `/review` — escalated cases with reasons · 🟢
- [x] Review actions on detail page — Confirm / Override→OK / Escalate
  (client component, `router.refresh()`) `ReviewActions.tsx` · 🟢
- [x] "Run AI assist" panel — live model output on demand
  `LlmAssist.tsx` · 🟢
- [x] Runs/scoreboard `/runs` — history with stats + score JSON · 🟢
- [x] Server-side fetches via compose DNS (`API_URL=http://api:8000`);
  browser calls go same-origin and are rewritten to the API by Next, so the
  UI works behind any host `web/next.config.ts` · 🟢
- [x] Field-level defect override UI — per-field checkboxes posting
  `override_fields` `ReviewActions.tsx` · 🟢
- [x] Attachment preview — extracted document text beside the diff
  `Attachments.tsx` + `GET /api/emails/{id}/attachments/{i}` · 🧪 🟢
- [x] Live run progress — per-email updates while a run executes, with the
  page refreshing until it finishes `RunControls.tsx` · 🟢
- [x] Loading and error states on every route `loading.tsx` / `error.tsx`
- [ ] Dark mode

## 11. LLM integration (OpenRouter via OpenAI SDK)

- [x] OpenAI SDK client pointed at `openrouter.ai/api/v1`
  `api/app/services/llm.py` · 🟢
- [x] Text model `nvidia/nemotron-3-ultra-550b-a55b:free` — classification +
  extraction verified live (correct queue + all 7 fields incl. the real
  consignee mismatch) · 🟢
- [x] Vision model `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` —
  rendered-BL OCR verified live · 🟢
  (original pick `nemotron-nano-12b-v2-vl:free` 404s on OpenRouter — swapped)
- [x] `llm_json` hardening — fence-strip, `{...}` slice, parse, one repair
  retry on the same model, tenacity backoff · 🟢 🧪
- [x] Model fallback chain — primary then `*_MODEL_FALLBACKS`, a dead or
  rate-limited slug is skipped rather than fatal (we lost
  `nemotron-nano-12b-v2-vl:free` mid-build) · 🧪
- [x] Client built on first use — the deterministic pipeline runs with no
  `OPENROUTER_API_KEY` at all · 🧪
- [x] `vision_json` — base64 PNG image_url input · 🟢
- [x] Fail-safe design — every LLM path degrades to deterministic behavior,
  never to a wrong verdict
- [ ] LLM cost/quota telemetry per run (calls made, tokens, decided_by split)

## 12. Infrastructure

- [x] `api/Dockerfile` — uv base image, `uv sync --frozen --no-dev` · 🟢
- [x] `web/Dockerfile` — corepack pnpm, `--frozen-lockfile` · 🟢
- [x] `docker-compose.yml` — web + api + provided scorer; scorer internal
  :8000 mapped to host :8080; api→scorer via `http://scorer:8000` · 🟢
- [x] `.dockerignore` (root + web) — build context 395 MB → 8 KB · 🟢
- [x] Data bundle mounted read-only at `/data`; `.env` via `env_file` · 🟢
- [x] pnpm everywhere — no npm/`package-lock.json` in the tree · 🟢
- [ ] Cloud deploy (web → Vercel, api → Railway/Render, Neon already cloud)
- [ ] Kubernetes manifests (Deployments + Ingress) — stretch item
- [ ] Health checks in compose (`depends_on: condition: healthy`)
- [x] `.env.example` committed — every knob documented, secrets blank

## 13. Testing & quality

**73 tests, all green, none of them touching a database or the network.**

- [x] 14 golden-fixture tests: classification, all 4 escalation reasons,
  exact defect fields, doc-type detection, synonym extraction,
  normalization `api/tests/test_pipeline.py` · 🧪 all green
- [x] 15 anti-overfit tests: neutral/renamed/reordered attachments, extra
  unrelated files, synonym-label swaps, port-format asymmetry, blank-token
  variants, send-BL trap, assists staying off when the flags are off
  `api/tests/test_robustness.py` · 🧪 all green
- [x] 9 LLM-client tests — fallback chain, cache hit/miss, corrupt cache
  entry, repair retry, missing key `api/tests/test_llm.py` · 🧪
- [x] 4 health-endpoint tests via `TestClient`, no database needed · 🧪
- [x] 9 attachment preview/storage + 15 review-action tests · 🧪
- [x] 5 manual-intake schema tests `api/tests/test_emails.py` · 🧪
- [x] Tests need no DB or network (file fixtures only) — CI runs them with
  `NEON_DB_URI` and `OPENROUTER_API_KEY` unset to keep it that way
- [x] Web typecheck + build in CI (`tsc --noEmit`, `pnpm build`) · 🟢
- [x] Lint config — ruff pinned in `pyproject.toml`, clean across `api/`
- [ ] API-level tests against a throwaway database

## 14. Docs & submission

- [x] `plans/REQUIREMENTS_PLAN.md` — business features + real examples
- [x] `plans/TECHNICAL_PLAN.md` — stack, schema, stages, scoring
- [x] `README.md` — architecture/pipeline/decision-tree/data-model
  diagrams, run instructions, no organizer names
- [x] This checklist — kept in step with the code, not written once
- [ ] Demo video (≤ 5 min, live deployed prototype)
- [ ] Demo script / talking points for judging

---

## Scorecard snapshot (provided dataset, latest verified run)

| Metric | Result |
|---|---|
| Final score | **1.0** |
| Stage-1 classification macro-F1 | 1.0 (520/520 correct) |
| Stage-3 defect F1 | 1.0 |
| End-to-end defects caught | 46/46 |
| Escalation precision / recall | 1.0 / 1.0 (20/20) |
