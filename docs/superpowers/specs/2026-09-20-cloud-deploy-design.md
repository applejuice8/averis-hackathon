# Cloud deployment, demo access, and live intake — design

- **Date:** 2026-09-20
- **Branch:** `feat/cloud-deploy` (cut from `feat/reliability-and-ci` @ `9e8e81c`)
- **Status:** revised for Vercel and cost-control review. [Deployment amendment](../plans/2026-09-20-vercel-cost-control-amendment.md) is authoritative for conflicting details.
- **Deadline driver:** preliminary submission closes **2026-09-22 12:00 (MYT)**; the
  rules require a *publicly accessible, functional* prototype link during judging and
  *meaningful* use of cloud infrastructure.

## 1. Goals and non-goals

### Goals

1. A public demo URL on **Vercel**, backed by **Google Cloud Run** that runs the existing
   pipeline, UI, and human-review flow end to end.
2. **Spending target of US$5**, with scale-to-zero, workload admission, budget alerts,
   and a separately selected monthly billing-disconnect threshold. This is not an exact cap.
3. The same backend images run locally and in GCP; Vercel builds the web natively.
4. Public read access for judges; every write or quota-spending action requires a
   shared reviewer passcode.
5. The answer key (`ground_truth.json`) leaves the public repo; the self-evaluation
   scorer keeps working through an IAM-private Cloud Run service.
6. **Live intake:** a judge can submit their own email + SI/BL files and see the
   verdict immediately; processing failures are visible and retryable.
7. Operational basics: uptime checks + alerting, structured logs, one-command demo
   reset, deploy-on-merge from GitHub Actions without long-lived keys.

### Non-goals (explicitly deferred)

| Item | Where it goes |
|---|---|
| Hybrid ML triage (rules + local model + LLM adjudicator + triage review + scam signals) | **Separate sub-project spec, next** |
| Real mailbox connector (Gmail API / IMAP on Cloud Scheduler) | Finals roadmap |
| Terraform for the GCP resources | Finals roadmap (bootstrap script maps 1:1) |
| Alembic migrations | Out of scope; one idempotent `ALTER` is enough here |
| Rewriting git history to purge the answer key | Team decision, flagged in the PR |
| Changing which LLM assists are on by default | Unchanged: runs stay deterministic |

## 2. Current state (what this builds on)

- Pipeline (classify → read → extract → escalate → compare) scores 1.0 on the provided
  self-evaluation; txt/pdf/docx/xlsx readers; opt-in vision OCR; OpenRouter model
  fallback chain + response cache.
- FastAPI (layered: routes / repositories / services) on Neon Postgres; Next.js 15 UI
  (inbox, SI/BL diff, review queue with field corrections, attachment previews, run
  progress); CI runs ruff, pytest, `tsc`, `next build`.
- PRs #1 (`feat/review-workspace`) and #2 (`feat/reliability-and-ci`) are open and
  stacked. This branch builds on #2 and targets `main` after both merge.

### Defects this design fixes

| # | Defect | Evidence |
|---|---|---|
| D1 | Next.js resolves the `/api/*` rewrite destination at **build** time; the web image bakes `http://localhost:8000`, so every browser-side write (review actions, start run, AI assist) returns 500 under compose. | Throwaway build: `routes-manifest.json` destination is `http://localhost:8000/api/:path*`; `next start` with `API_URL=http://127.0.0.1:9999` still returned 500. |
| D2 | The api image contains no dataset; it depends on a bind mount of `docs-provided/`, which `.dockerignore` excludes. | `docker-compose.yml`, `.dockerignore` |
| D3 | Pipeline runs use in-process `BackgroundTasks`; on scale-to-zero, CPU is throttled after the response, so a 520-email run can stall. | `api/app/api/routes/pipeline.py` |
| D4 | No access control: anyone can start runs, overwrite reviews, and spend LLM quota. | all routes |
| D5 | Images run as root, no health endpoints suited to probes, unpinned `pnpm@latest`, ~700 MB web image. | `api/Dockerfile`, `web/Dockerfile` |
| D6 | The public repo contains the answer key. | `docs-provided/.../data_v2/ground_truth.json` |

## 3. Architecture

```
                 Judges / team (browser)
                          │ HTTPS (*.vercel.app)
                          ▼
   ┌───────────────────────────────────────────────┐
   │ sdoc-web   Vercel Next.js, public             │
   │  • SSR pages fetch API_URL at request time    │
   │  • /api/*  → route-handler proxy (runtime)    │
   │      cookie sdoc_reviewer → X-Demo-Passcode   │
   │  • /auth/reviewer  unlock / lock              │
   │  • /healthz                                   │
   └──────────────────────┬────────────────────────┘
                          ▼ HTTPS
   ┌───────────────────────────────────────────────┐   ID token   ┌─────────────────────┐
   │ sdoc-api   Cloud Run service, public URL      │─────────────►│ sdoc-scorer         │
   │  • reads open; writes need X-Demo-Passcode    │  (run.invoker)│ Cloud Run, IAM-only │
   │  • dataset baked at /data                     │              │ GROUND_TRUTH secret │
   │  • uploads: GCS bucket mounted /data/uploads  │              │ mounted as a file   │
   │  • full runs → Run Admin API → sdoc-worker    │              └─────────────────────┘
   └───┬──────────────┬───────────────┬────────────┘
       │ TLS          │ HTTPS         │ jobs.run (with overrides)
       ▼              ▼               ▼
   Neon Postgres   OpenRouter   ┌───────────────────────────────────┐
   (existing)      (existing)   │ sdoc-worker  Cloud Run Job        │
                                │  api image, `python -m pipeline.worker`
                                │  modes: run --run-id X | seed [--reset]
                                │  same secrets + uploads mount     │
                                └───────────────────────────────────┘

   Supporting: Artifact Registry (images) · Secret Manager · Cloud Storage (uploads)
               Cloud Monitoring (uptime + alert) · Cloud Logging · Billing budget
               GitHub Actions → Workload Identity Federation → deployer SA
```

### Region

Co-locate with Neon: every processed email makes several database round trips. The
operator runs `scripts/gcp/neon-region.sh`, which parses `NEON_DB_URI` from the local
`.env` and prints **only** the provider and region (e.g. `aws ap-southeast-1`) plus the
suggested GCP region. Neither the operator's terminal nor any log shows the host,
user, or password. Mapping:

| Neon region | GCP region |
|---|---|
| `aws-ap-southeast-1` (Singapore) | `asia-southeast1` |
| `aws-ap-southeast-2` (Sydney) | `australia-southeast1` |
| `aws-us-east-1` (Virginia) | `us-east4` |
| `aws-us-east-2` (Ohio) | `us-east5` |
| `aws-us-west-2` (Oregon) | `us-west1` |
| `aws-eu-central-1` (Frankfurt) | `europe-west3` |
| `aws-eu-west-2` (London) | `europe-west2` |
| `aws-sa-east-1` (São Paulo) | `southamerica-east1` |
| `azure-eastus2` | `us-east4` |
| anything else | `asia-southeast1` (closest to judges) |

### GCP project

Use existing `averis-email-system` (969206696114), region `asia-southeast1`. Pass the project explicitly on every command. Refuse a disabled or unexpected billing link; never automatically relink.

## 4. Cost controls and limits

Use the [deployment amendment](../plans/2026-09-20-vercel-cost-control-amendment.md) for the selected topology,
cost analysis and guard procedure. The under-US$1 estimate and guaranteed-US$5
ceiling are withdrawn. Scale-to-zero removes idle compute costs; maximum instance
counts do not cap spending over time or concurrent job executions.

Vercel hosts the web, subject to plan eligibility/limits. GCP hosts API (max 2),
private scorer (max 1), and worker (one task per execution, plus a separate global
admission limit). Keep minimum instances zero. Include storage, network, secrets,
function builds and external providers in the estimate.

Deploy/test/arm the project-scoped monthly budget function **before app deployment**.
The user selected **RM40 per month in MYR**; use Vercel Hobby for this noncommercial demo. Billing
notifications are delayed: disconnect can overshoot and can interrupt/delete
resources. Native Cloud Run spend caps are an optional additional preview control.
No ordinary deployment may reattach billing after a shutdown.

## 5. Components

### 5.1 api image (`api/Dockerfile`)

- Stage `build`: `ghcr.io/astral-sh/uv:python3.13-bookworm-slim`,
  `uv sync --frozen --no-dev --no-install-project` into `/app/.venv`.
- Stage `runtime`: `python:3.13-slim-bookworm`; copy `/app/.venv`, `api/`, and the
  dataset (`docs-provided/problem-statement/sdoc-hackathon-bundle/{inbox,attachments}`
  → `/data`). `ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1
  PYTHONDONTWRITEBYTECODE=1 DATA_DIR=/data LLM_CACHE_DIR=/tmp/llm-cache`.
- Non-root user `app` (uid 10001). `/data/uploads` is created and owned by `app` so the
  compose volume and the Cloud Run mount are writable.
- `CMD ["uvicorn", "app.main:app", "--app-dir", "/app/api", "--host", "0.0.0.0",
  "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]`. Cloud Run is
  deployed with `--port 8000`.
- Docker `HEALTHCHECK` hits `/livez` (compose only; Cloud Run uses its default TCP
  startup probe).
- `.dockerignore` excludes `docs-provided/` except the bundle directory.

### 5.2 New api endpoints and settings

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /livez` | open | always 200 — liveness for container health |
| `GET /health` | open | existing report + `writes_protected` + `run_executor` |
| `GET /api/auth/check` | passcode | 204 if the passcode is valid (used by web unlock) |
| `POST /api/intake` | passcode | live intake (§5.6) |
| `POST /api/emails/{id}/reprocess` | passcode | retry one email (§5.6) |

New settings (`api/app/core/config.py`):

| Env | Default | Cloud value |
|---|---|---|
| `DEMO_PASSCODE` | `""` (writes open — local dev) | from Secret Manager |
| `CORS_ORIGINS` | `http://localhost:3000` | web URL |
| `RUN_EXECUTOR` | `inline` | `cloudrun-job` |
| `GCP_PROJECT_ID`, `GCP_REGION`, `WORKER_JOB` | `""` | set at deploy |
| `SCORER_AUTH` | `none` | `gcp-id-token` |
| `UPLOADS_SUBDIR` | `uploads` | `uploads` |
| `LOG_FORMAT` | `text` | `json` |

### 5.3 Reviewer passcode

- `api/app/api/deps.py` gains `require_reviewer(x_demo_passcode: str | None = Header(None))`.
  If `settings.demo_passcode` is empty it allows the call; otherwise it rejects a
  missing or wrong value with **401** using `hmac.compare_digest`.
- Applied to: `POST /api/pipeline/run`, `POST /api/review/{result_id}`,
  `POST /api/export/submit`, `POST /api/intake`, `POST /api/emails/{id}/reprocess`,
  `GET /api/auth/check`, and AI assist, which changes from
  `GET` to **`POST /api/pipeline/llm-assist/{email_id}`** because it spends quota.
  `web/app/emails/[id]/LlmAssist.tsx` is updated to match.
- Read routes (`GET /api/emails*`, `/api/runs*`, `/api/review`,
  `/api/export/submission`, attachment previews, `/docs`) stay open.
- Web: a "Reviewer mode" control in `Navigation.tsx` posts the passcode to
  `POST /auth/reviewer` (a Next route handler, outside the proxied `/api/*` space).
  The handler validates it through `GET /api/auth/check` and sets cookie
  `sdoc_reviewer` (httpOnly, Secure in production, SameSite=Lax, 12 h).
  `DELETE /auth/reviewer` clears it. While locked, write buttons render disabled with
  the label "Unlock reviewer mode".
- The passcode itself is the cookie value. Acceptable for a demo passcode that is
  published to judges; documented as a limitation.

### 5.4 Vercel web and runtime proxy (`web/`)

Native Next.js build, project root `web`, Singapore region, server-only `API_URL`.
The checked-in route handler reads API_URL at request time, forwards only selected
headers, adds the reviewer cookie as the API passcode, requires same-origin writes,
and returns bounded gateway errors. `/healthz` does not query the API or database.

Vercel's 4.5 MB request/response limit requires the proxy's conservative 4 MB bound;
intake attachments are limited to 3 MiB combined. Optional local Docker builds may
set `WEB_STANDALONE=1`; no GCP web service/image is deployed. See the amendment for
Hobby eligibility, paid-plan spend controls, previews and CI-gated promotion.

### 5.5 Pipeline run execution

- New `api/app/services/executor.py`:
  - `InlineExecutor.start(run_id, email_ids)` — the current `BackgroundTasks` path
    (compose and local dev).
  - `CloudRunJobExecutor.start(run_id, email_ids)` — gets an access token from the
    metadata server
    (`/computeMetadata/v1/instance/service-accounts/default/token`) and calls
    `POST https://run.googleapis.com/v2/projects/{p}/locations/{r}/jobs/{WORKER_JOB}:run`
    with `overrides.containerOverrides[0].args = ["run", "--run-id", run_id, ...ids]`.
  - Chosen by `RUN_EXECUTOR`. If the trigger call fails, the route deletes the run it
    just created and returns **502** with the reason; no orphan "running" rows.
- New `api/pipeline/worker.py` CLI:
  - `run --run-id <id> [email_id ...]` → `run_pipeline(run_id=..., email_ids=...)`.
  - `seed [--reset]` → optional reset (§5.8), `ingest()`, create run labelled `seed`,
    `run_pipeline`, then `submit(run_id)` when the scorer is configured.
  - Top-level exceptions are logged, and the run gets `finished_at` + `stats.error`
    before the process exits non-zero.
- `run_pipeline` becomes **resumable**: it skips emails that already have a result in
  the run, so a retried job execution never duplicates results.
- Full runs only process `source = 'dataset'` emails (§5.6), so submissions contain
  exactly the 520 dataset IDs.
- Known limitation: if a job execution is killed (timeout), its run stays unfinished;
  the Runs page shows it as running. The 1800 s timeout is ~15× a normal run.

### 5.6 Live intake

- **Data model:** `emails.source VARCHAR(16) NOT NULL DEFAULT 'dataset'`
  (`dataset` | `upload`). `init_db()` runs `ALTER TABLE emails ADD COLUMN IF NOT
  EXISTS source ...` after `create_all`, because `create_all` does not alter existing
  tables.
- **`POST /api/intake`** (multipart: `sender`, `subject`, `body`, `files[]`):
  - Validation → **422** with a specific message: 0–4 files; ≤ 3 MiB each and ≤ 3 MiB
    total; extension in {`.txt`, `.pdf`, `.docx`, `.xlsx`}; content sniff (`%PDF-`
    for pdf, `PK\x03\x04` for docx/xlsx, valid UTF-8 for txt); filename reduced to
    `[A-Za-z0-9._-]`, max 80 chars, de-duplicated; subject ≤ 300 chars, body ≤ 20 000.
  - `email_id = upload_<YYYYMMDD>_<6 hex>`. Files are written to
    `/data/uploads/<email_id>/<name>`; attachment paths are stored as
    `uploads/<email_id>/<name>`, so the existing readers and previews resolve them via
    `Path(DATA_DIR) / rel` unchanged.
  - The email is processed inline (`process_email` in a thread, 90 s budget). The
    result goes into a get-or-create run labelled **`adhoc`**. Response:
    `201 {email_id, status, category}`; the UI navigates to `/emails/<email_id>`.
  - If processing raises, the result is stored as `FAILED` with the error string and
    the response is still 201: the failure is visible in the review queue.
- **Storage:** Cloud Run mounts bucket `gs://<project>-sdoc-uploads` at `/data/uploads`
  on the api service and the worker job (Cloud Storage volume, gen2). Compose mounts a
  named volume at the same path. The bucket has uniform access, public access
  prevention, and a 30-day delete lifecycle.
- **Retry:** `POST /api/emails/{id}/reprocess` re-runs `process_email` for any email
  (dataset or upload) and adds a new result to the `adhoc` run. The latest result wins
  in every screen. Review overrides stay attached to the older result, so a reprocess
  is a fresh machine attempt. The review queue shows a **Retry** button on `FAILED`
  items, and the email detail page shows **Reprocess** in reviewer mode.
- **Web `/intake` page:** form (From, Subject, Body, files) + a **sample kit** of
  static files in `web/public/samples/`, copied from the dataset: a matching `.txt`
  pair (editable to create a mismatch), a PDF pair, an xlsx/docx pair, an image-only
  PDF, and a wrong-document-type pair. A short note tells judges that the "Run AI
  assist" panel reads scanned uploads with the vision model.

### 5.7 Private scorer

- Built from the provided `docs-provided/.../server/Dockerfile`, unchanged.
- Cloud Run: `--no-allow-unauthenticated`,
  `--set-secrets=/secrets/ground_truth.json=GROUND_TRUTH:latest`. The minified answer
  key is 60 005 bytes, under Secret Manager's 64 KiB limit. `DATA_DIR` stays empty:
  `/submit` only reads the ground truth.
- `api/pipeline/submission.py`: when `SCORER_AUTH=gcp-id-token`, it fetches an ID token
  from the metadata server
  (`/computeMetadata/v1/instance/service-accounts/default/identity?audience=<SCORER_URL>`)
  and sends `Authorization: Bearer <token>`. No new dependency (httpx).
- Repo: `git rm` the answer key; `.gitignore` adds `secrets/`; compose mounts
  `./secrets/ground_truth.json`. The README explains how a teammate places the file
  locally. The file remains in git history (team decision, flagged in the PR).

### 5.8 Demo reset

`scripts/gcp/demo-reset.sh` → `gcloud run jobs execute sdoc-worker --args=seed,--reset
--wait`. Reset deletes review rows for upload results, upload results, upload emails,
and `/data/uploads/<id>/` directories. It then re-ingests, runs the full pipeline, and
scores. Earlier runs stay as scoreboard history. Operator-only; not exposed in the UI.

## 6. Security and identity

### Secrets (Secret Manager; never in images, repo, or CI)

| Secret | Consumer | How |
|---|---|---|
| `NEON_DB_URI` | api, worker | env var |
| `OPENROUTER_API_KEY` | api, worker | env var |
| `DEMO_PASSCODE` | api, worker | env var |
| `GROUND_TRUTH` | scorer | file `/secrets/ground_truth.json` |

`scripts/gcp/bootstrap.sh` creates the four secrets **empty**.
`scripts/gcp/set-secrets.sh` is **run by the operator only**. It reads values from the
operator's local `.env` (or prompts with hidden input for the passcode), minifies the
answer key, and pipes each value to `gcloud secrets versions add --data-file=-`. It
never echoes values. The assistant does not read `.env` or handle secret values.

### Service accounts (least privilege)

| SA | Roles (scoped) |
|---|---|
| `sdoc-api` (also the worker job's identity) | `secretmanager.secretAccessor` on its 3 secrets; `run.invoker` on `sdoc-scorer`; `run.jobsExecutorWithOverrides` on `sdoc-worker`; `storage.objectUser` on the uploads bucket; `logging.logWriter` |
| `sdoc-scorer` | `secretmanager.secretAccessor` on `GROUND_TRUTH` |
| `sdoc-deployer` | `artifactregistry.writer` on the repo; `run.developer` (project); `iam.serviceAccountUser` on the three runtime SAs |

### GitHub → GCP

Workload Identity Federation: pool `github`, OIDC provider `github-actions` with
condition `assertion.repository == 'applejuice8/secret-hack' && assertion.ref ==
'refs/heads/main'`; `roles/iam.workloadIdentityUser` on `sdoc-deployer` for that
principal set. No JSON keys exist. The workflow reads non-secret repo **variables**
`GCP_PROJECT_ID`, `GCP_REGION`, `GCP_WIF_PROVIDER`, `GCP_DEPLOYER_SA` (setting them
needs repo admin).

### Other hardening

Non-root containers; CORS from `CORS_ORIGINS`; `/health` never includes connection
strings (existing behaviour kept); upload validation (§5.6); max-instance caps limit
abuse cost.

## 7. Operations

- **Uptime checks** (`gcloud monitoring uptime create`): `https://<web>/healthz` and
  `https://<api>/livez`, period 5 min, regions `ASIA_PACIFIC`, `EUROPE`,
  `USA_VIRGINIA`.
- **Alerting:** email notification channel (address passed to bootstrap as
  `ALERT_EMAIL`); policy fires when either check fails 2 consecutive periods.
- **Structured logs:** `api/app/core/logging.py` configures a JSON formatter when
  `LOG_FORMAT=json`: `severity`, `message`, `run_id`, `email_id`, and
  `logging.googleapis.com/trace` derived from `X-Cloud-Trace-Context`. The worker
  logs one line per email and a summary per run.
- **Budget:** created by bootstrap (§4).
- **Runbook** `docs/deploy.md`: bootstrap, secrets, first deploy, seed, reset,
  rollback (`gcloud run services update-traffic <svc> --to-revisions=<rev>=100`),
  costs, and teardown (`gcloud projects delete`).

## 8. Scripts (all idempotent, bash, `set -euo pipefail`)

| Script | Does |
|---|---|
| `scripts/gcp/neon-region.sh` | prints Neon provider/region + suggested GCP region only |
| `scripts/gcp/bootstrap.sh` | validate existing project/billing (never relink), enable APIs (run, artifactregistry, secretmanager, iamcredentials, storage, monitoring, billingbudgets), Artifact Registry repo `sdoc` + cleanup policy, uploads bucket + lifecycle, SAs + IAM, empty secrets, WIF pool/provider, budget, notification channel, uptime checks + alert policy |
| `scripts/gcp/set-secrets.sh` | operator-only secret population (§6) |
| `scripts/gcp/deploy.sh` | build + push images tagged with the git SHA, deploy scorer → worker → api; Vercel web is a separate native build after backend readiness, create/update `sdoc-worker` with the same secrets, uploads mount, and `SCORER_URL`/`SCORER_AUTH` as the api, set `CORS_ORIGINS`. Used by humans and CI |
| `scripts/gcp/smoke.sh` | web `/` 200; `/health` → `writes_protected: true`; `POST /api/pipeline/run` without passcode → 401; `/api/emails` returns 520+ rows |
| `scripts/gcp/demo-reset.sh` | §5.8 |

## 9. CI/CD

**Amended:** native web build/proxy tests and API/guard/image checks all gate deployment. Vercel promotion is separate from GCP WIF. See [the amendment](../plans/2026-09-20-vercel-cost-control-amendment.md); historical container-only workflow details below do not define Vercel deployment.

- **`ci.yml`** (existing, every push/PR) gains job `images`: build api and web images
  (no push), then container smoke:
  - api container with no env: `/livez` 200; `/health` returns JSON with
    `data_dir.present == true` (status 503 expected without a database).
  - web container: `/healthz` 200.
- **New `deploy.yml`** (push to `main`; `concurrency: deploy-production`;
  `permissions: id-token: write, contents: read`): run the test job →
  `google-github-actions/auth@v2` (WIF) → `setup-gcloud@v2` →
  `scripts/gcp/deploy.sh` → `scripts/gcp/smoke.sh`. A failed smoke test fails the
  workflow; rollback is the documented traffic command.
- The first deploy runs `scripts/gcp/deploy.sh` locally, so the live link does not wait
  on repo-admin setup.

## 10. Testing

New unit tests (same convention as today: no database, no network):

| Test file | Covers |
|---|---|
| `api/tests/test_auth.py` | `require_reviewer`: open when unset; 401 missing/wrong; pass on correct; applied to every write route (route-table assertion) |
| `api/tests/test_intake.py` | count/size/extension limits, content sniffing, filename sanitising + de-dup, path traversal (`../`, absolute paths), id format; `process_email` raising → `FAILED` result with the error string |
| `api/tests/test_executor.py` | executor selection; Run Admin request shape and URL (httpx mocked); trigger failure → error |
| `api/tests/test_worker.py` | resume skips emails already in the run; `seed --reset` deletes only upload data (repositories stubbed) |
| `api/tests/test_scorer_auth.py` | ID-token header added only when `SCORER_AUTH=gcp-id-token` (metadata server mocked) |

The existing suite (28+ tests) must stay green; ruff clean; `tsc` + `next build` green.
CI container smoke covers D1, D2, and D5. `smoke.sh` covers the deployed system.

**Acceptance on the live URL before submitting:**

1. Open the web URL in a private window: dashboard loads, 520 emails listed.
2. `email_004` shows the consignee mismatch side by side.
3. Review queue lists 20 escalations with reasons.
4. A write while locked is refused; unlock with the passcode; confirm one case.
5. Intake with the edited sample `.txt` pair → `MISMATCH` on the edited field.
6. Intake with the image-only PDF → `NEEDS_REVIEW / unreadable`; AI assist reads it.
7. Start a full run from the Runs page → it completes; explicitly invoke/verify benchmark scoring. Unscored runs must be labelled correctly.
8. Intake of a `.txt` file renamed to `.pdf` is rejected with a 422 message; Reprocess
   on `email_004` adds a new result with the same verdict. (A `FAILED` result cannot be
   produced from valid UI input; the FAILED → 201 → Retry path is covered by
   `test_intake.py`.)
9. `demo-reset.sh` restores the clean state.
10. Verify the selected monthly guard amount/currency/project, armed function, retry/trigger/IAM, and service caps. Record the actual Vercel/GCP deployment URLs.

## 11. Rollout order

The live link is the critical path. Install, test and arm the selected billing guard before the first app deploy; do not postpone it until after launch.

1. Team merges PR #1 and PR #2 into `main`; this branch rebases onto `main`.
2. Answer key out of the repo; compose reads `./secrets/`.
3. Docker hardening + proxy route handler + `/livez` + `/healthz` + dataset baked in;
   verify with `docker compose up --build`.
4. Reviewer passcode (api dependency + web unlock).
5. Executor abstraction, worker CLI with resume, scorer ID token.
6. Operator runs `neon-region.sh` → `bootstrap.sh` → `set-secrets.sh`; first
   `deploy.sh`; `sdoc-worker seed`; Vercel native deploy → **live URL** (target 2026-09-21 midday).
7. Live intake + `source` column + reprocess/Retry + sample kit.
8. Structured logging; uptime checks and alert (bootstrap re-run).
9. `ci.yml` image smoke + `deploy.yml`; repo admin sets the four variables.
10. `docs/deploy.md` + README "Deploy" section + acceptance checklist on the live URL.

## 12. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Neon is far from every GCP region | region mapping (§3); worst case accept slower full runs (job runs off the request path) |
| Cold start on a judge's first click | uptime-check keep-warm; startup CPU boost; small images |
| OpenRouter free tier (20 req/min, 50/day without credits) exhausted during judging | assists stay opt-in and passcode-gated; response cache; runs are deterministic without the model |
| Cloud Storage FUSE semantics (no atomic rename, eventual listing) | intake writes each file once, then reads it; no renames, no listing-dependent logic |
| Passcode leaks beyond judges | rotate via `set-secrets.sh` + redeploy; admission limits, quotas and cost controls reduce exposure |
| Proxy change conflicts with teammates' web work | small, isolated files; PR description calls out the replaced `rewrites()` |
| Repo-admin access for Actions variables not available in time | `deploy.sh` works from a laptop; CI deploy is additive |
| Budget alert arrives after spend | overshoot remains possible; use admission limits, delayed billing disconnect and an optional native service cap. No exact cost guarantee |

## 13. Follow-up: ML triage sub-project (next spec)

A separate spec will cover hybrid email triage, independent of this deployment:

- rules and a local scikit-learn model (TF-IDF + logistic regression, calibrated) vote
  on every email;
- the LLM adjudicates only disagreements or low-confidence cases (cached);
- still-uncertain emails go to a new *triage review* queue;
- explainable scam signals (display-name/domain mismatch, look-alike domains,
  credential requests, urgency language, link counts);
- training data is team-generated, **never** the answer key; validation goes through the
  scorer as a held-out check;
- the hard-coded spam domain list and template phrases that mirror the organizers'
  generator are replaced.

The interface to this design is `pipeline.classify.classify()` and the api image's
dependencies; nothing in this deployment spec changes for it.
