# Deploying SDOC Verifier

Operator runbook for the Cloud Run + Vercel deployment. Design and cost
rationale: [`docs/superpowers/plans/2026-09-20-vercel-cost-control-amendment.md`](superpowers/plans/2026-09-20-vercel-cost-control-amendment.md).
Verified deploy sequence this runbook follows:
[`.superpowers/sdd/2026-09-20-cloud-deploy/task-14-runbook.md`](../.superpowers/sdd/2026-09-20-cloud-deploy/task-14-runbook.md).

**Status: not yet deployed.** No live URLs exist. Every `<...>` placeholder
below is filled in after the first real deploy (Task 14) — do not treat any
URL-shaped text in this file as real.

## What runs where

| Piece | Where | Access |
|---|---|---|
| `web` | Vercel (Next.js, project root `web`, region `sin1`) | public |
| `sdoc-api` | Cloud Run service | public; writes need the reviewer passcode |
| `sdoc-scorer` | Cloud Run service | IAM-private — only the `sdoc-api` service account may invoke it |
| `sdoc-worker` | Cloud Run Job (same image as `sdoc-api`) | started by `sdoc-api` per run, or by an operator |

Pinned project: `averis-email-system` (`969206696114`), region
`asia-southeast1`, billing account `015CE1-381F1A-582702`. Every script in
`scripts/gcp/` passes `--project` explicitly and refuses if billing is
absent, disabled, or linked to a different account (`require_billing` in
`scripts/gcp/common.sh`).

Also created: Artifact Registry `sdoc` (keeps the 3 newest images),
Secret Manager (`NEON_DB_URI`, `OPENROUTER_API_KEY`, `DEMO_PASSCODE`,
`GROUND_TRUTH`), bucket `<project>-sdoc-uploads` mounted at
`/data/uploads` (30-day lifecycle), and the billing kill switch described
below.

The browser never calls the API cross-origin: `web/app/api/[...path]/route.ts`
proxies every `/api/*` call server-side to `API_URL`. CORS on the API
(`CORS_ORIGINS`, set from `WEB_URL` by `deploy.sh`) is defence in depth, not
load-bearing for the demo UI.

## The ordering problem

`deploy.sh` requires `WEB_URL` (the Vercel origin) to set `CORS_ORIGINS` on
the API. Vercel requires `API_URL` (the Cloud Run API origin) to build the
web app. Neither exists before the other, so the deploy happens twice:
deploy the API first with a placeholder `WEB_URL`, create the Vercel project
against the real API URL, then re-run `deploy.sh` with the real `WEB_URL`.
Re-running is cheap and idempotent — it only rewrites `CORS_ORIGINS` if the
image tag is unchanged.

## Prerequisites

- `gcloud auth login`, then
  `gcloud auth configure-docker asia-southeast1-docker.pkg.dev`
- Docker running locally (images are built locally and pushed — there is no
  Cloud Build step)
- `.env` at the repo root with `NEON_DB_URI` and `OPENROUTER_API_KEY`
- `secrets/ground_truth.json` (see `secrets/README.md`) — only used by the
  private scorer
- The billing guard (below) armed **before** the first billable deploy step

## Deploy sequence

1. **Bootstrap** (operator or Claude; idempotent, near-zero cost)

   ```bash
   ALERT_EMAIL=you@example.com bash scripts/gcp/bootstrap.sh
   ```

   Enables APIs, creates the Artifact Registry repo with a cleanup policy,
   the uploads bucket, secret containers (no values), scoped service
   accounts, and GitHub OIDC for deploy-on-merge. Creates no secret values
   and never links billing — it refuses instead if billing isn't already
   correctly attached.

2. **Secrets — operator only, never Claude**

   ```bash
   PROJECT_ID=averis-email-system REGION=asia-southeast1 bash scripts/gcp/set-secrets.sh
   ```

   Reads `NEON_DB_URI` and `OPENROUTER_API_KEY` from `.env` and pushes them
   into Secret Manager without printing them. Prompts (hidden) for the
   reviewer passcode; leaving it blank generates one and prints it **once**
   — that printed line is the value to hand judges. Also uploads the answer
   key from `secrets/`. Credential handling stays with the operator by
   design; this step is never run on Claude's behalf.

3. **First deploy, placeholder CORS (billable)**

   ```bash
   PROJECT_ID=averis-email-system REGION=asia-southeast1 \
     WEB_URL=https://placeholder.vercel.app bash scripts/gcp/deploy.sh
   ```

   Builds and pushes `api` and `scorer` images, deploys `sdoc-scorer`
   (IAM-private, only `sdoc-api`'s service account may invoke it), deploys
   the `sdoc-worker` job, then deploys `sdoc-api` with
   `RUN_EXECUTOR=cloudrun-job` and **`--max-instances 1`**. That cap is
   load-bearing, not a cost trim: the duplicate-attempt guard
   (`api/app/services/processing.py`, a per-email `asyncio.Lock`) and the
   active-run/daily-run limits (`settings.max_active_runs`,
   `settings.max_runs_per_day` — see below) are per-process state. Pinning
   the API to one instance is what makes them behave globally for this
   demo; do not raise it without first making those guards cross-instance.
   Capture the printed API URL.

4. **Vercel project — operator, free tier**

   Root directory `web`, framework Next.js, region `sin1`, Node 22, the
   committed pnpm lockfile. Set the **server-side** env var `API_URL` to the
   Cloud Run API URL from step 3. Never set `NEXT_PUBLIC_API_URL`, database
   credentials, the scorer key, or the OpenRouter key on the web project —
   reviewer authorization and all secrets stay in the API. Keep the
   production `API_URL` out of default preview deployments. Capture the
   production Vercel URL.

5. **Re-deploy with the real origin**

   ```bash
   PROJECT_ID=averis-email-system REGION=asia-southeast1 \
     WEB_URL=https://<real>.vercel.app bash scripts/gcp/deploy.sh
   ```

   Only rewrites `CORS_ORIGINS` on the API; images are unchanged if the
   commit is unchanged.

6. **Seed and benchmark (billable — this is the full run)**

   ```bash
   PROJECT_ID=averis-email-system REGION=asia-southeast1 bash scripts/gcp/demo-reset.sh
   ```

   Runs `python -m pipeline.worker seed --reset` on the worker job: removes
   any uploaded/demo emails and their reviews, ingests the dataset fresh,
   runs every email, and scores the run. This is also how you reset the
   demo to a clean state later (see below) — it is the same command. This
   is the most expensive single step; expect it to take a while.

7. **Smoke test, on the real public URL**

   ```bash
   PROJECT_ID=averis-email-system REGION=asia-southeast1 \
     WEB_URL=https://<real>.vercel.app bash scripts/gcp/smoke.sh
   ```

   Confirms: `/health` reports `writes_protected: true` and
   `run_executor: "cloudrun-job"`; an unauthenticated `POST
   /api/pipeline/run` is refused with 401; `GET /api/emails` returns at
   least 520 rows; and, if `WEB_URL` is set, the web app's `/` is 200 and
   its `/api/*` proxy reaches the API (also 401 unauthenticated).

8. **Record**

   Write the API URL, the Vercel URL, the deployed commit SHA, and the
   guard state into this file once the deploy is real. Until then the
   placeholders below stay as-is.

## Live URLs

| | URL |
|---|---|
| Web (Vercel) | `<vercel-url>` — filled in after the first deploy |
| API (Cloud Run) | `<api-url>` — filled in after the first deploy |
| API docs | `<api-url>/docs` |
| Deployed commit | `<commit-sha>` |

## Everyday operations

### Unlocking reviewer mode

Reads (dashboard, inbox, review queue, runs) are open to anyone with the
link — that's deliberate, so judges can browse without a password. Every
*write* (starting a run, confirming/overriding a review, submitting a score,
live intake, reprocessing an email) is gated by `require_reviewer`
(`api/app/api/deps.py`): the request must carry header `X-Demo-Passcode`
matching the `DEMO_PASSCODE` secret, compared with `hmac.compare_digest`. A
route-table test fails CI if any write route is left unguarded.

In the web UI, unlocking goes through `web/app/auth/reviewer/route.ts`:
`POST /auth/reviewer` with `{"passcode": "..."}` validates against
`GET /api/auth/check` on the API, then sets an `HttpOnly`, `SameSite=Lax`
cookie (`secure` when served over HTTPS) for 12 hours. `DELETE
/auth/reviewer` clears it (lock again). The passcode itself never reaches
client-side JS — the cookie carries it server-side on the proxy's calls to
the API. If `DEMO_PASSCODE` is empty (local dev only), `require_reviewer`
lets every write through with no passcode — this must never be true in the
cloud deploy; `smoke.sh` fails loudly (`writes are NOT protected`) if it is.

### A run is refused with 409 or 429

`POST /api/pipeline/run` (`api/app/api/routes/pipeline.py`) enforces two
spend guards from `api/app/core/config.py` before starting anything:

- **409** `"A run is already in progress..."` — `settings.max_active_runs`
  (default `1`) is already reached (`runs_repo.count_active`). Wait for the
  in-flight run to finish (check the Runs page or `GET /api/runs`), then
  retry.
- **429** `"The daily run allowance is used up..."` — `settings.max_runs_per_day`
  (default `20`) runs have already been *started* in the trailing 24 hours
  (`runs_repo.count_started_since`). This is a rolling window, not a
  calendar day, so it clears on its own — there is no manual reset. If you
  genuinely need more headroom for a demo, that requires a code/env change
  (`MAX_RUNS_PER_DAY`), not an operator action.

Both guards are per-process state, which is why `sdoc-api` is pinned to
`--max-instances 1` in `deploy.sh` — see step 3 above.

### Resetting the demo to a clean state

```bash
PROJECT_ID=averis-email-system REGION=asia-southeast1 bash scripts/gcp/demo-reset.sh
```

Executes the worker job with `python -m pipeline.worker seed --reset`. This
**destroys**:

- every uploaded/manually-added email (`manual_*`, `upload_*` rows) and its
  files under the uploads bucket
- every review (`reviews` table row) attached to those emails

It then re-ingests the static dataset from scratch, runs the full pipeline
over every email, and scores that run. Emails ingested from the read-only
dataset bundle are unaffected (they're re-ingested, not deleted) but any
runs/results tied to them from before the reset are superseded by the fresh
run. Gmail-synced emails (`gmail_*`) are not touched by this command's
delete step — `emails_repo.delete_uploads` only removes uploaded/manual
rows.

### Retrying a single failed email

`POST /api/emails/{email_id}/reprocess` (`api/app/api/routes/emails.py`,
reviewer-gated) reruns the pipeline for exactly one email; the new result
becomes the latest result for that email everywhere in the UI. If that
email is already mid-processing, the endpoint returns 409 ("This email is
already being processed. Wait for it to finish.") instead of queuing a
second attempt — `AlreadyProcessing`, the same per-email lock that backs the
active-run guard. The Retry action in the web UI calls this endpoint.

### Score lifecycle

`pipeline/worker.py`'s `run_command` only scores a run when it was started
with **no** `email_ids` filter (`if not email_ids: await score_run(run_id)`)
— i.e. a full-dataset run, whether via `seed` or via the API's "Run inbox
checks" with no filter. A subset run (specific `email_ids`) or a single
`reprocess` call is never scored, and uploaded/manual intake documents are
never scored against the organizers' answer key — only full runs over the
static dataset are. Scoring failures never fail the run itself (`score_run`
catches and logs a warning; see `pipeline/worker.py`).

### Logs

`configure_logging` (`api/app/core/logging.py`) switches to structured JSON
when `LOG_FORMAT=json` (set by `deploy.sh` on both the API service and the
worker job). Each line is `{"severity", "message", "logger", ...}`; the API
also stamps `run_id`/`email_id` on relevant log lines and, when a request
carries `X-Cloud-Trace-Context`, adds
`logging.googleapis.com/trace` so Cloud Logging groups every line from one
request. Cloud Run ships stdout straight to Cloud Logging, so:

- **Find one run**: Cloud Logging → filter
  `resource.type="cloud_run_job" AND jsonPayload.run_id="<uuid>"` for
  worker output, or
  `resource.type="cloud_run_revision" AND jsonPayload.run_id="<uuid>"` for
  API-side lines (run creation, the 409/429 guard messages).
- **Recent API errors**:
  `gcloud logging read 'resource.type="cloud_run_revision" AND severity>=WARNING' --limit 50 --project averis-email-system`
- **Worker output**:
  `gcloud logging read 'resource.type="cloud_run_job"' --limit 50 --project averis-email-system`

### The RM40 billing guard

Deployed and armed separately from the app (`scripts/gcp/deploy-cost-guard.ps1`,
`scripts/gcp/killswitch/`) — see
`docs/cost-guard-status.md` for the exact deployed configuration
(budget `sdoc-verifier-killswitch`, MYR 40.00/calendar month including
credits, project filter restricted to `projects/969206696114`, alerts at
50/80/100%).

**What it does when it trips:** a Pub/Sub budget notification above the
threshold reaches the `sdoc-billing-killswitch` Cloud Function
(`scripts/gcp/killswitch/`), which — when armed (`DRY_RUN=false`) and after
confirming its own IAM permission — disconnects billing from
`averis-email-system`. That stops every billable resource in the project
at once (API, scorer, worker, uptime checks). The runtime identity holds
only project-read and `resourcemanager.projects.deleteBillingAssignment`;
it has **no** billing relink permission and no billing-account admin role.
It logs `billing_guard_failed` on an internal error and
`refused_different_account` if the event doesn't match the pinned
project/account — both are wired to the same alert channel as uptime.

**Recovery is manual, by design:**
1. Diagnose the spend source first — do not just relink and hope.
2. Relink billing in the GCP console (or `gcloud billing projects link`) —
   no script in this repo does this automatically; `selftest.sh` fails the
   suite if one ever gains that call.
3. Fix the cost source (bad loop, raised instance caps, etc.).
4. Re-run `scripts/gcp/deploy-cost-guard.ps1 -Arm` with a new budget/timestamp
   before resuming the demo.
5. Redeploy the app (`deploy.sh`).

Ordinary app deploys must never perform steps 2 or 4 — `deploy.sh` only
ever checks billing is healthy (`require_billing`) and refuses otherwise; it
never reconnects it. RM40 is a trigger on *reported* GCP cost, not an
instantaneous or lifetime cap — billing data lags, so actual overshoot is
approximately (spending rate × detection delay) and is not bounded by this
setting. Vercel, Neon and OpenRouter have their own, independent billing
and are outside this guard's reach (Vercel: kept on the Hobby plan, no
paid upgrade authorized; see the amendment doc for their own limits).

### Rollback

```bash
gcloud run revisions list --service sdoc-api --region asia-southeast1 --project averis-email-system
gcloud run services update-traffic sdoc-api --region asia-southeast1 --project averis-email-system \
  --to-revisions=<REVISION>=100
```

Same for `sdoc-scorer`. For the worker job, redeploy `deploy.sh` at a
previous commit (`IMAGE_TAG=<previous short sha>`), since jobs don't keep
traffic-split revisions the way services do. For the web app, use Vercel's
own deployment list to promote a previous deployment.

### Teardown

`gcloud projects delete averis-email-system` stops all billing; the project
is recoverable for 30 days. This is a last resort, not part of the normal
reset flow — use `demo-reset.sh` for a clean demo state instead.

## Gmail integration — not part of this deploy

Live Gmail ingest (`api/app/api/routes/gmail.py` et al., README section 10)
exists in the codebase but is **deliberately not configured** in the cloud
deploy. `deploy.sh` explicitly does not set `GOOGLE_CLIENT_ID` /
`GOOGLE_CLIENT_SECRET` / `GOOGLE_REDIRECT_URI` on `sdoc-api` (see the
comment above the `sdoc-worker` deploy step in `scripts/gcp/deploy.sh`).
Those settings are optional in `api/app/core/config.py` and the feature
degrades cleanly when unset, so this is safe: it is local-dev-only until a
separate, deliberate change wires OAuth secrets and a production redirect
URI into the deploy. Do not expect "Import from Gmail" to work on the live
demo URL.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `deploy.sh`: secret "has no versions" | run `set-secrets.sh` first |
| `smoke.sh`: "writes are NOT protected" | `DEMO_PASSCODE` is empty — rerun `set-secrets.sh`, then `deploy.sh` |
| UI: "Could not start the run" (502) | the worker job hand-off failed (`executor.ExecutorError`) — rerun `deploy.sh` to re-apply the job's IAM bindings |
| Run refused with 409 | a run is already active — wait, or check `GET /api/runs` for a stuck one |
| Run refused with 429 | the rolling 24h run allowance (`max_runs_per_day`) is used up — wait, it clears on its own |
| Runs never get a score | check the run was started with no email filter (subset runs and `reprocess` are never scored); confirm `sdoc-api`'s service account has `roles/run.invoker` on `sdoc-scorer` |
| Billing guard fired unexpectedly | see "The RM40 billing guard" above — diagnose before relinking |

## Verification

Before treating any of the above as accurate for a given deploy, confirm
against the live URLs once they exist: `bash scripts/gcp/smoke.sh` must
print `smoke OK`, `/health` must report `writes_protected: true` and
`run_executor: "cloudrun-job"`, and `gcloud billing projects describe
averis-email-system --project averis-email-system` must still report
`billingEnabled: True`.
