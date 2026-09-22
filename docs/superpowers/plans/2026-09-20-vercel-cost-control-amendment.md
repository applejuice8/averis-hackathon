# Deployment review and Vercel amendment

Reviewed 2026-09-20 against local `feat/cloud-deploy` at `51fb6ab`, the implementation
plan, design spec, and current Google Cloud/Vercel documentation. This amendment
supersedes conflicting deployment, cost, upload-size, and acceptance instructions
in the original plan and spec. It does not approve a push. Guard deployment evidence is in `docs/cost-guard-status.md`; the application itself remains undeployed.

## Verdict and actual progress

The plan is legitimate engineering work: private scoring, durable worker execution,
reviewer-protected writes, resumable processing, isolated secrets, container smoke
tests, and live acceptance all address real defects. Keep that structure.

It is **designed for low fixed cost**, not proven to cost less than US$1 or guaranteed
to stay under US$5. Free tiers are conditional/shared, jobs can be launched repeatedly,
and storage, network traffic, model calls, and builds are separate meters. Moving a
lightly used web service to Vercel may save little money; its main benefit here is
simpler Next.js hosting and removal of one GCP image/service.

Tasks 1–5 were implemented at the reviewed commit; the baseline suite passed 90 tests.
That is 5/21 task headings, **not 24% of engineering effort or overall product progress**.
Forecasts of 64 → 109 tests are historical estimates, not acceptance criteria. Tasks
6–8 (private scorer identity and durable worker), production images, and a live
end-to-end deployment remain major prerequisites.

Read-only cloud inspection confirmed `averis-email-system` (969206696114) exists and
billing is enabled on the expected account. **Account currency is MYR**, verified
through the Billing API. The original `5USD`/`10USD` commands are invalid for this
account; the user selected an RM40 monthly cutoff on 2026-09-20. Cloud Run and Billing Budgets APIs were
disabled. Budget listing therefore failed: existing account budgets are **unknown**.
No Vercel project was present in the connected team. The CLI's default project is a
different project: all scripts must explicitly pass `--project=averis-email-system`.

## Revised topology

```text
Browser → Vercel Next.js (Singapore, native Next.js build; project root: web)
             ↓ HTTPS, runtime server-side API_URL, same-origin browser proxy
          GCP Cloud Run API → IAM-private Cloud Run scorer
             ↓              → Cloud Run worker job (same API image)
          Neon / GCS / opt-in OpenRouter

GCP project-scoped monthly budget → Pub/Sub → billing-disconnect function
```

The GCP product is **Cloud Run**. CloudFront is an AWS product and is not needed.
Keep Neon where it is. Keep API, scorer, job, secrets, and uploaded-file storage in
GCP Singapore. Do not add a load balancer, VPC connector, or GCP web service.

On Vercel choose the existing team, Next.js framework, root directory `web`, Node 22,
the committed pnpm lockfile, and production `API_URL` set to the deployed API HTTPS
origin. Never configure `NEXT_PUBLIC_API_URL`, database credentials, the scorer key,
or the OpenRouter key on the web project. Reviewer authorization remains in the API.
Preview deployments must not receive the production API URL by default.

The user confirmed this is a noncommercial hackathon demo and selected **Vercel Hobby**.
Do not upgrade to Pro. Keep the project on Hobby; future commercial use would require
revisiting eligibility. A paid Vercel plan needs its own spend controls; the GCP
function cannot stop Vercel charges. Vercel's documented spend-management pause
option is separate from simply setting an alert amount.

## Implemented locally by this amendment

- `web/vercel.json`: native Next.js build in `sin1`.
- `web/next.config.ts`: runtime proxy replaces build-time rewrite. Standalone output
  is optional via `WEB_STANDALONE=1` for Docker, not the Vercel deployment mechanism.
- `web/app/api/[...path]/route.ts`: same-origin writes, bounded request/response
  bodies, explicit timeout and gateway errors.
- All application actions are public; there is no reviewer unlock flow or
  shared passcode.
- `/healthz` calls neither API nor database; `robots.txt` discourages indexing.
- `scripts/gcp/killswitch/`: notification validation, dry-run-first handler,
  idempotent project billing disconnect, and failure retries.
- `scripts/gcp/deploy-cost-guard.ps1`: explicitly scoped setup, readback checks,
  separate runtime/trigger/build identities, and required dry-run evidence before
  arming. No command automatically reattaches billing.

The web changes remain local. The billing function is now **deployed and armed at
RM40 per calendar month (MYR, after credits)**. Live dry-run delivery, runtime
permission checks and armed configuration readback passed; see
`docs/cost-guard-status.md`. The web/backend live acceptance run is still pending.

## Corrections required before launch

1. **Cost protection precedes builds/public deployment.** Run the guard setup in
   dry-run mode and then arm it at the selected cutoff before the first app deploy.
   Re-check billing status in every deploy; never automatically relink a disabled
   project. The old Task 18b placement was too late, and its Pub/Sub budget flag
   `--all-updates-rule-pubsub-topic` was invalid; use `--notifications-rule-pubsub-topic`.
2. **No hard dollar guarantee.** Instance limits bound concurrency, not total work
   over time. One task/parallelism-one per job execution does not prevent multiple
   executions. Add a database-backed global active-run limit, idempotent dispatch,
   bounded retries and a per-day run allowance before publishing the passcode.
3. **Vercel payload limit.** Functions accept requests/responses up to 4.5 MB.
   Keep the proxy's conservative 4,000,000-byte bound. Tasks 16/17 must allow up to
   four files, at most **3 MiB each and 3 MiB combined**, plus the bounded email
   fields. Reject oversized bodies in both API and UI. Large documents/exports
   require signed GCS URLs or a different path; increasing a Next.js setting does
   not raise Vercel's platform limit. Sample-kit files must fit these limits.
4. **Timeout is not cancellation.** `asyncio.wait_for(run_in_threadpool(...))`
   stops waiting but may leave the underlying processor/model call running. Pass
   deadlines into processing and external calls, or use the worker with polling.
   Prevent duplicate processing before exposing Retry; a web timeout must not
   automatically start another paid attempt. Keep deterministic mode by default.
5. **Score lifecycle.** The proposed worker's normal `run_command` does not score,
   while `seed` does. Either score completed benchmark runs explicitly, or change
   acceptance/UI to show an unscored completed run and expose a protected scoring
   action. Never score uploaded documents against the benchmark answer key.
6. **Monitoring and storage.** Retain the plan's `/healthz` and `/livez` fix. Treat
   probes as availability checks, not a guarantee of warm instances. Keeping three
   image versions does not guarantee Artifact Registry stays within its free
   allowance. Include function build/source storage and Cloud Build in the estimate.
7. **Deployment gates.** Require API tests/lint, billing-guard tests, TypeScript,
   Next build, proxy smoke tests and container smoke before promotion. A Vercel Git
   integration can deploy before a separate GitHub check finishes: configure that
   gate explicitly or deploy from a successful CI workflow. GCP WIF does not replace
   the Vercel deployment credential. No push until separately authorized.

## Keep the 21-task sequence, with these adjustments

| Task(s) | Revised deliverable / status |
|---|---|
| 1–5 | Completed baseline; retain and rerun regression checks. |
| 6–8 | Private-scorer identity and durable worker; add admission/idempotency and resolve scoring lifecycle. |
| 9 | Harden API image and scorer context; no answer key in public images. |
| 10 | Vercel web/runtime proxy (local code added); optional Docker image remains only for local parity. |
| 11 | Wire reviewer sidebar, locked controls, expired-passcode handling to the existing auth route. |
| 12 | Local compose parity plus API/scorer image smoke and native Next.js/proxy checks. |
| 13 | GCP bootstrap/deploy scripts for API/scorer/job only. Run the former 18b guard here **first**. |
| 14 | Deploy GCP backend, seed/score, then Vercel; verify the public URL in a signed-out browser. |
| 15–17 | Retry/intake/sample kit with 3 MiB combined attachments, bounded processing, duplicate prevention. |
| 18 | Liveness checks/alerts; no periodic database query or model call. |
| 18b | Moved before first deployment: cutoff → dry-run delivery → arm → config/IAM evidence. |
| 19 | CI-gated backend deployment and Vercel promotion; distinct identities/credentials. |
| 20 | Runbook and live acceptance, including billing guard state and outage recovery. |
| 21 | Push only with explicit user authorization; truthful authorship for actual contributors. |

## Billing guard operation

The guard covers **this GCP project's reported monthly cost after credits**. It is
not a lifetime competition cap. Vercel, Neon and OpenRouter are independent and
need their own free-plan/quota/credit controls. Delayed reporting permits overshoot.
Unlinking billing stops the backend and can make resources unavailable or subject
to deletion. Do not use this project for unrelated workloads. Preserve needed data.

Use PowerShell (examples intentionally leave the cutoff unspecified):

```powershell
# User-selected cutoff; run dry-run delivery checks before arming.
$cutoff = [decimal]40
$gcloud = 'C:\Users\aloys\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd'
.\scripts\gcp\deploy-cost-guard.ps1 -Limit $cutoff -Currency MYR -GcloudPath $gcloud

# Allow Eventarc delivery and inspect the dry-run event. It cannot unlink billing.
& $gcloud functions logs read sdoc-billing-killswitch --gen2 `
  --region=asia-southeast1 --project=averis-email-system --limit=20

# This verifies a matching above-threshold dry-run log exists before arming.
.\scripts\gcp\deploy-cost-guard.ps1 -Limit $cutoff -Currency MYR -GcloudPath $gcloud -Arm
```

The runtime custom role permits project inspection and deletion of **this project's**
billing assignment, with no billing-account administrator role and no relink
permission. The Pub/Sub topic is not public. Keep publisher/admin access narrow:
trusted publishers can produce budget-shaped messages. Restrict human/project
owner credentials accordingly. Eventarc can retry transient errors; repeated
delivery after a successful disconnect is harmless. No synthetic over-threshold
event is ever sent while the function is armed.

After arming, verify the project number/account, amount/currency/month/project
filter, budget topic, expected budget ID, DRY_RUN=false, retry policy, trigger
identity/invoker binding, and the runtime's custom role. Add an error/log alert for
`billing_guard_failed` and `refused_different_account`; normal budget emails remain
enabled. If billing-account/project association is locked, unlock it deliberately
or use the native spend cap; the function cannot override a locked association.

Recovery: keep the project disconnected while diagnosing the spend. Remove the
guard trigger or deploy DRY_RUN=true deliberately, then manually relink billing
only when the cost source is fixed. Replace/update the monthly budget explicitly,
retest, and re-arm with a new timestamp. Ordinary app deploys must never perform
that recovery. The function lives in the protected project and stops with it.

Google now documents a **preview native Cloud Run spend cap**, scoped to one
project/service and using estimated gross cost. Where available, add it as an
earlier service-level stop. It is not instantaneous, excludes persistent-resource
costs, and does not replace the requested all-project billing backstop. No native
spend cap was created or verified in this review.

## Verification

Local verification: **123 Python tests passed**, including 33 guard tests; Ruff
passed; TypeScript and the Next.js production build passed. The production proxy
smoke test passed against a local stub (runtime URL, origin protection, cookies,
body limits, 204/HEAD and API outage). No Docker runtime was available. The guard was subsequently deployed and armed
on GCP; the application and Vercel web remain undeployed. No real billing unlink
was performed as a test. The offline PowerShell
deployment test also passes: it substitutes every gcloud call, tests MYR setup,
rejects disabled billing/wrong currency/missing dry-run evidence, and confirms
arming never publishes a synthetic threshold event. The runtime also checks its
disconnect permission before reporting a successful dry run. Live Eventarc delivery, dependency installation, runtime permission checks and armed
configuration readback subsequently passed. An actual billing unlink was not tested.

## Sources

- [Google: automatic billing disable and its limitations](https://docs.cloud.google.com/billing/docs/how-to/disable-billing-with-notifications)
- [Google: budget notification schema](https://docs.cloud.google.com/billing/docs/how-to/budgets-programmatic-notifications)
- [gcloud budget creation flags](https://docs.cloud.google.com/sdk/gcloud/reference/billing/budgets/create)
- [Project billing permissions](https://docs.cloud.google.com/billing/docs/how-to/modify-project)
- [Cloud Run pricing](https://cloud.google.com/run/pricing)
- [Google native spend caps (preview)](https://docs.cloud.google.com/billing/docs/how-to/budgets-spend-caps)
- [Vercel function limits](https://vercel.com/docs/functions/limitations)
- [Vercel Hobby eligibility and limits](https://vercel.com/docs/plans/hobby)
- [Vercel spend management](https://vercel.com/docs/spend-management)

## Upload requirement check and approved settings (2026-09-20)

The original problem statement (both PDF copies), rules, infopack, judging rubrics
and dataset guides contain no 10 MB upload requirement. Claude selected 5 MiB per
file / 10 MiB combined as application limits. Retain the revised **3 MiB combined**
demo limit; the largest supplied attachment is 37,445 bytes and the largest email's
combined attachments total 43,149 bytes. Larger future documents can use direct,
authorized GCS uploads instead of passing through a Vercel Function.

Approved: **Vercel Hobby** and **RM40 monthly GCP billing disconnect**. The project
is `averis-email-system`; the existing account-wide RM300 alert budget is separate
and must not be modified by this setup. Deployment evidence is recorded separately
in `docs/cost-guard-status.md` once verified.

Overshoot is not bounded by the RM40 setting. Approximately: additional cost =
spending rate × detection/shutdown delay, plus other late-reported charges. For
illustration (not forecasts): RM0.10/hour × 24 hours = RM2.40 extra; RM1/hour = RM24
extra; RM5/hour = RM120 extra. Actual reporting can exceed 24 hours. Repeated worker
executions, egress and unrelated project services prevent a firm upper estimate
without enforced quotas and measured workload limits.

Ordinary deployment must not reconnect billing: if the guard disconnects the project,
a later code deploy must stop rather than reattach the account and resume spending.
Only deliberate recovery after fixing the cost source may reconnect billing.

Source: [Google's reporting-delay guidance](https://docs.cloud.google.com/billing/docs/how-to/resolve-issues).
