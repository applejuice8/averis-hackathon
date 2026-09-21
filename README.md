# DockerOps

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
 │  browser                                                              │
 │    │  http://localhost:3000                                           │
 │    ▼                                                                  │
 │ ┌─────────────┐   server-side fetch (compose DNS)                     │
 │ │     web     │ ────────────────────────────┐                         │
 │ │  Next.js 15 │                             ▼                         │
 │ │  pnpm       │   /api/* rewritten   ┌─────────────┐                  │
 │ └──────┬──────┘   to API_URL         │     api     │                  │
 │        │                             │  FastAPI    │                  │
 │        └────────────────────────────►│  uv / py3.13│                  │
 │             same origin, any host    │  :8000      │                  │
 │                                      └──────┬──────┘                  │
 │                                             │                         │
 └─────────────────────────────────────────────┼─────────────────────────┘
                                               │
            ┌───────────────────────────┬──────┴───────────────────┐
            ▼                           ▼                          ▼
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
| `web` | node:22-alpine + corepack pnpm | 3000 | Dashboard, inbox, diff view, review queue, intake, runs. Locally: build-time rewrite. In the cloud: Vercel, with `web/app/api/[...path]/route.ts` proxying `/api/*` to the API at request time so the browser never calls it cross-origin |
| `api` | astral-sh/uv python3.13 | 8000 | Pipeline, REST API, Neon access. Same image also runs the worker job in the cloud (`python -m pipeline.worker`) |
| `scorer` | python:3.12-slim (provided) | 8080→8000 | Evaluation against private ground truth. Locally reachable at `http://scorer:8000`; in the cloud it's an IAM-private Cloud Run service only `sdoc-api`'s service account may invoke |
| Neon | managed | — | `emails`, `runs`, `pipeline_results`, `reviews` |
| OpenRouter | managed | — | text model + vision model |

In the cloud, `web` deploys to Vercel and `api`/`scorer` deploy to Cloud Run,
plus a Cloud Run Job (`sdoc-worker`, same `api` image) for full pipeline runs
so they don't run inside a request. See section 10.

The browser only ever talks to its own origin: Next rewrites `/api/*` to
`API_URL`, so the UI works unchanged on localhost, in compose, or behind a
deployed hostname.

`GET /health` reports what the service can actually reach — the Neon
round-trip, the configured model chain, which assists are switched on, and
whether the data directory is mounted. It answers 503 when the database is
down, and never calls a model.

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
| `ENABLE_LLM_FILL` | parse found **zero** fields → unknown layout | text model rescues |

`llm_json` hardening: prompt-for-JSON → strip code fences → slice the
`{...}` block → pydantic-style validation → one repair retry → tenacity
backoff. Raw model output never decides a verdict.

Two more things the free tier forced on us:

- **Fallback chain** — `TEXT_MODEL` then `TEXT_MODEL_FALLBACKS`, in order.
  A retired slug or a rate-limited model is skipped, and a call only fails
  once the whole chain has. We lost `nemotron-nano-12b-v2-vl:free` to a 404
  mid-build; the chain is why that stops being an incident.
- **Content-hash cache** — every parsed reply is stored under `.cache/llm`
  keyed by the hash of its request, so rerunning the same document is free.
  `ENABLE_LLM_CACHE=false` turns it off.

The client is built on first use, so the deterministic pipeline runs with no
`OPENROUTER_API_KEY` at all — pull the key mid-demo and verdicts keep
coming, which is the point of "LLMs read, code decides".

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
│   │   └── services/           llm.py (chain + cache), review.py, attachments.py
│   ├── pipeline/               ingest → classify → readers → extract
│   │   └── readers/            → escalate → compare → submit
│   │       └── ocr.py          vision-model path (pypdfium2 render)
│   └── tests/                  64 tests — golden, anti-overfit, LLM client,
│                               health, review; no DB, no network
├── web/
│   ├── Dockerfile              pnpm install --frozen-lockfile + build
│   ├── next.config.ts          standalone output; API proxy: app/api/[...path]
│   ├── app/                    / inbox emails/[id] review runs auth/reviewer
│   └── lib/                    api.ts typed fetch + labels.ts UI copy
├── scripts/gcp/                bootstrap · set-secrets · deploy · smoke ·
│                                demo-reset · monitoring · killswitch (RM40 guard)
├── docs/deploy.md              Cloud Run + Vercel runbook
├── secrets/                    git-ignored (local answer key; never committed)
├── .github/workflows/
│   ├── ci.yml                  ruff + pytest + tsc + next build + image smoke
│   └── deploy.yml              main, after CI passes → Cloud Run + Vercel
└── plans/                      requirements + technical plan docs
```

---

## 9. Run it

```bash
cp .env.example .env     # fill in NEON_DB_URI; the key is optional
docker compose up --build
```

- web → http://localhost:3000 · api → http://localhost:8000 (`/docs`) ·
  scorer → http://localhost:8080 · `curl localhost:8000/health` to see what
  the API can reach

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

Tests: `uv run pytest api/tests -v` · lint: `uv run ruff check api`.
Both run on every push, together with `tsc --noEmit` and `next build`,
and the API job runs with no database and no API key so we keep noticing
if something starts needing them.

The spam detector is a measured word TF-IDF + logistic-regression pipeline.
Its experiment history and limitations are in `api/ml/PERFORMANCE.md`; executed
notebooks stay in `api/ml/notebooks/`. Retrain the production artifact with:

```bash
uv run python -m api.ml.train
```

The command atomically writes `api/ml/models/spam.joblib`, including the
selected threshold and dataset fingerprint. Joblib artifacts can execute code
while loading, so deploy only the artifact produced from this repository and
never load an uploaded or otherwise untrusted model file.

---

## 10. Cloud deployment (Google Cloud Run + Vercel)

**Status: live.** Operator runbook: [docs/deploy.md](docs/deploy.md).

Both halves deploy themselves. A push to `main` runs CI (ruff, pytest,
`tsc`, `next build`, container smoke); only if every job passes does
`.github/workflows/deploy.yml` fire, pushing the API to Cloud Run
(Workload Identity Federation — no service-account key is stored in this
repo) and the web app to Vercel, then smoke-testing what it just shipped.

| | |
|---|---|
| Web | Vercel, https://dockerops.vercel.app |
| API | Cloud Run, https://sdoc-api-969206696114.asia-southeast1.run.app ([`/docs`](https://sdoc-api-969206696114.asia-southeast1.run.app/docs) for the OpenAPI UI) |

```
 browser ──► web (Vercel, public) ──/api/* server-side proxy──► sdoc-api (Cloud Run, public; writes need the reviewer passcode)
                                                                  │  ├─ Neon Postgres
                                                                  │  ├─ OpenRouter (optional)
                                                                  │  ├─ gs://…-sdoc-uploads (mounted /data/uploads)
                                                                  │  ├─ sdoc-scorer (Cloud Run, IAM-private)
                                                                  │  └─ sdoc-worker (Cloud Run Job, one execution per full run)
```

Reads (dashboard, inbox, review queue, runs) are open to anyone with the
link, on purpose, so judges can browse with no login. Writes — starting a
run, confirming a review, live intake, reprocessing — require unlocking
reviewer mode with a passcode (`X-Demo-Passcode` header, checked in
`api/app/api/deps.py::require_reviewer`); the web UI does this through
`web/app/auth/reviewer/route.ts`, which sets a 12-hour HttpOnly cookie after
the API confirms the passcode.

Spend is bounded two ways: `sdoc-api` runs with `--max-instances 1` (so its
in-process run guards — at most one active run, at most 20 started per
rolling day, see `api/app/core/config.py`) behave globally, and a Cloud
Function disconnects this GCP project's billing if reported monthly cost
passes a selected MYR cutoff (currently **RM40**; see
`docs/cost-guard-status.md`). That guard cannot bound Vercel, Neon or
OpenRouter spend, which are separate, independent billing relationships.

Full setup, day-to-day operations (unlocking reviewer mode, what a 409/429
run refusal means, resetting the demo, retrying a failed email, finding
logs for one run, recovering from the billing guard), rollback and teardown
are in [`docs/deploy.md`](docs/deploy.md).

---

## 11. Gmail integration (optional inbox source, local only)

> **Not part of the cloud deploy.** `scripts/gcp/deploy.sh` deliberately
> does not set `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` /
> `GOOGLE_REDIRECT_URI` on the deployed API. These settings are optional in
> `api/app/core/config.py` and the feature degrades cleanly when unset, so
> this is safe — it just means Gmail import only works when you run the
> stack yourself, as described below. Wiring it into the cloud deploy would
> be a separate, deliberate change.

Pull live shipping mail straight from Gmail instead of the static bundle.
Gmail is just another ingest source: messages land in the same `emails`
table and their attachments in a **writable** `GMAIL_DATA_DIR`, so the rest
of the pipeline runs unchanged. Read-only scope — the mailbox is never
modified. Emails are namespaced `gmail_<messageId>` so they never clash
with the `email_###` bundle fixtures.

**Flow:** Inbox → **Import from Gmail** → Google consent → **Sync Gmail** →
new `gmail_*` rows appear → **Run inbox checks** as usual.

### Google Cloud setup

1. **Project** — https://console.cloud.google.com → pick/create a project.
2. **Enable the Gmail API** — APIs & Services → Library → *Gmail API* → Enable.
3. **OAuth consent screen** (a.k.a. *Google Auth Platform*) — set User type
   **External**, fill app name + support email.
4. **Test users** — add your own Gmail address under **Audience → Test
   users**. `gmail.readonly` is a *sensitive* scope, so while the app is
   unverified only test users can consent.
5. **Scopes** — Data access → **Add or remove scopes** → add
   `https://www.googleapis.com/auth/gmail.readonly`
   (direct link: `https://console.cloud.google.com/auth/scopes`).
6. **OAuth client** — Credentials → Create Credentials → OAuth client ID →
   **Web application**. Add the redirect URI **exactly**:
   ```
   http://localhost:8000/api/auth/google/callback
   ```

### Configure `.env`

```env
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-secret
GOOGLE_REDIRECT_URI=http://localhost:8000/api/auth/google/callback
# WEB_APP_URL=http://localhost:3000     # where callback returns the user
# GMAIL_DATA_DIR=/data-gmail            # writable attachment store (compose volume)
```

### Use it

```bash
docker compose up --build
# open http://localhost:3000/inbox → Import from Gmail → consent → Sync Gmail
docker compose exec api uv run python -m pipeline.run   # then process them
```

Or sync from the API directly:

```bash
curl -X POST 'http://localhost:8000/api/gmail/sync'
# optional Gmail search filter:
curl -X POST 'http://localhost:8000/api/gmail/sync?query=has:attachment+newer_than:7d'
```

Endpoints: `GET /api/auth/google/start` · `GET /api/auth/google/callback` ·
`POST /api/gmail/sync` · `GET /api/gmail/accounts` ·
`DELETE /api/gmail/accounts/{id}`. Default sync query is
`has:attachment newer_than:30d`; re-syncing is idempotent (upsert on
`email_id`). The connected account + last-synced time show on the Inbox.

> Redirect URI must match byte-for-byte. For a deployment, add the
> production `https://…/api/auth/google/callback` URI and set
> `WEB_APP_URL` / `GOOGLE_REDIRECT_URI` to match. Refresh tokens are stored
> in `gmail_accounts` in plaintext (hackathon default) — encrypt at rest
> before pointing this at a real mailbox.

---

## 12. Challenges faced

**The dataset teaches you its own conventions, and you have to refuse to
learn them.** Attachments are named `email_004_SI.txt` / `email_004_BL.txt`,
labels are spelled one way, and a parser built around that scores perfectly
while understanding nothing. Every convention we leaned on got a deliberate
escape hatch: SI/BL are re-identified by detected document type when the
filenames say nothing, labels normalise through a synonym map (`POL`,
`Load Port`, `Gross Wt (kgs)`, `毛重`), ports compare on the port name proper
so `SHANGHAI, CHINA (CNSHA)` ≡ `SHANGHAI`, and blank tokens (`???`,
`_______`, `TBA`, `N/A`) resolve to *missing*, not to *mismatched* — a
different verdict with a different owner. Half the test suite exists to
perturb those conventions and prove the pipeline survives it.

**A perfect score is a claim you have to defend.** Final 1.0 on the provided
data is a weak signal on its own: 520 synthetic emails, 46 end-to-end cases.
We treated it as a starting point rather than a result, and wrote 15
anti-overfit tests — renamed and reordered attachments, unrelated extra
files, swapped label synonyms, asymmetric port formats, a mislabeled
`*_BL.pdf` that actually contains an invoice, and a "please send me the BL"
request that must read as *awaiting documents*, not as an escalation.

**Spam looked solved and wasn't.** A domain blocklist and a regex hit 100%,
which turned out to mean they had memorised the corpus. Replacing them
became a measurement exercise instead of an opinion: stratified holdout,
5-fold repeated cross-validation, threshold chosen from out-of-fold
predictions only. Six candidates tied at F1 1.0 — because the data is
trivially separable — so the tie broke on fit cost and word TF-IDF with
balanced logistic regression shipped over the reference MLP. The honest
finding is recorded in [`api/ml/PERFORMANCE.md`](api/ml/PERFORMANCE.md):
40 spam records, nine unique subjects, six unique bodies. None of this
generalises yet, and the document says so.

**Free-tier models disappear underneath you.** Our first vision model,
`nemotron-nano-12b-v2-vl:free`, started returning 404 from OpenRouter
mid-build. That turned a single model id into a fallback chain — primary,
then alternates, skipping anything dead or rate-limited and only failing
once the whole chain is exhausted — plus a content-hash response cache, so
re-reading the same document costs nothing against a shared quota.

**Pulling the key should not break the product.** Running the suite the way
CI does — no `NEON_DB_URI`, no `OPENROUTER_API_KEY` — broke at import,
because the OpenAI SDK refuses to construct a client without credentials.
The deterministic path never needs one, so the client became lazy. CI now
runs with both secrets deliberately unset, which is how we keep noticing if
something starts depending on them. The demo survives the key being revoked
live; that property *is* the architecture.

**Each half of the deploy needed the other half's URL first.** `deploy.sh`
sets `CORS_ORIGINS` on the API from the Vercel origin, and Vercel needs the
Cloud Run origin to build the web app. Neither exists before the other, so
the deploy runs twice: API first against a placeholder, create the Vercel
project against the real API URL, then re-run — idempotent, and it only
rewrites `CORS_ORIGINS` when the image tag is unchanged.

**The Vercel GitHub app was authorised on a personal fork**, not on this
repository, so importing from the dashboard kept cloning the wrong project —
and only the repo owner can change that. Rather than block on an
authorisation we didn't control, web deploys go through the Vercel CLI with
a scoped token, gated on the same green CI run as the Cloud Run job.

**A student-owned cloud account is a real constraint.** Spend is bounded
before it can happen, not after: `sdoc-api` runs at `--max-instances 1` so
the in-process run guards behave globally, full runs are handed to a Cloud
Run Job with a daily cap, the scorer is IAM-private and reachable only by
the API's service account, and a Cloud Function disconnects billing outright
if reported monthly cost passes a set MYR cutoff.

---

## 13. Future roadmap

**Next — finish the human-in-the-loop story.** Reviewer corrections already
persist in `reviews`, but nothing reads them back. Surfacing them as a
corrections feed turns human judgement into training signal: which fields
reviewers overrule most, which synonyms the parser keeps missing, which
escalation reasons are noise. That is the cheapest path from *tool* to
*system that improves*.

**Then — meet the mail where it lives.** Gmail OAuth works locally today and
is deliberately not wired into the cloud deploy. Making it production-real
means encrypted refresh tokens, a registered production redirect URI, and
IMAP / Microsoft Graph alongside it, so the product attaches to an existing
shipping-ops mailbox instead of asking anyone to change how they work.

**Beyond SI vs BL.** The comparison engine is document-pair agnostic — the
7-field contract and the synonym map are configuration, not logic. Packing
list vs commercial invoice, certificate of origin vs BL, and booking
confirmation vs SI are the same shape of problem. A self-serve synonym table
would let an ops team extend the vocabulary without a deploy.

**Confidence instead of a binary.** Escalation is currently all-or-nothing.
Grading it — low-OCR-confidence differs from a hard parse failure — lets
reviewers triage by risk rather than by queue position, and gives per-field
extraction provenance somewhere to live in the UI.

**Hardening for anything past a demo.** Named reviewer identities and SSO in
place of a shared passcode; Alembic migrations instead of `create_all` on
startup; rate limiting and request logging; per-run LLM cost and quota
telemetry; drift monitoring and periodic re-evaluation of the spam model
against independently labelled mail before anyone relies on it.

**And the boring one that pays off immediately:** authorise the Vercel
GitHub app on this repository and pull requests get preview deployments, so
changes get reviewed against a running site instead of a diff.
