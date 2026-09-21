# GCP billing guard deployment record

Date: 2026-09-20. User authorized an **RM40 monthly cutoff** and **Vercel Hobby**.

## Scope

| Setting | Value |
|---|---|
| Project | `averis-email-system` (`969206696114`) |
| Region | `asia-southeast1` |
| Billing account | `015CE1-381F1A-582702` (MYR) |
| Guard budget | `sdoc-verifier-killswitch` |
| Budget ID | `27ca2599-14fc-4f91-bd79-17b0abee060d` |
| Amount / period | MYR 40.00 / calendar month, including all credits |
| Project filter | Only `projects/969206696114` |
| Alerts | 50%, 80%, 100%: RM20, RM32, RM40 |
| Pub/Sub topic | `projects/averis-email-system/topics/sdoc-budget-alerts` |
| Function | `sdoc-billing-killswitch`, Python 3.13, gen2 |
| Runtime identity | `sdoc-killswitch@averis-email-system.iam.gserviceaccount.com` |
| Trigger identity | `sdoc-budget-trigger@averis-email-system.iam.gserviceaccount.com` |
| Build identity | `sdoc-budget-build@averis-email-system.iam.gserviceaccount.com` |

## Evidence

The function was deployed privately. Its only explicit Cloud Run invoker is the
trigger identity. The runtime custom role has only project-read and
`resourcemanager.projects.deleteBillingAssignment` permissions. It has no billing
relink permission. The function has zero minimum instances, one maximum instance,
concurrency one, a 90-second timeout, and event retries enabled.

Live Pub/Sub dry-run event ID `21824896505853602` reached the function. At
**2026-09-20T05:17:29.155471Z** it logged `would_disable_billing`, with the expected
project, budget ID, `limit=40.00`, and `dry_run=true`. This exercised event delivery,
the billing-account GET and the runtime's IAM permission test; no billing PUT was
performed. Initial invocation failures during IAM propagation were retried and
then succeeded.

**Arming status: ACTIVE / armed.** Production readback at
**2026-09-20T05:24:34Z** confirmed `DRY_RUN=false`, `COST_LIMIT=40.00`, MYR, the
exact project/budget identities and event retries. The armed configuration timestamp
is `2026-09-20T05:22:14Z`; the update completed at `2026-09-20T05:23:02Z`. Billing
remains enabled: no real shutdown was performed. Structured readback and local source
hashes are in `cost-guard-verification.json`.

A harmless zero-cost probe (`21822266925793327`) was then handled by armed revision
`sdoc-billing-killswitch-00002-qob` at **2026-09-20T05:24:37.039671Z**. It logged
`under_budget` with `dry_run=false` and `limit=40.00`. No over-threshold synthetic
message was published after arming.

The pre-existing account-wide **RM300 Monthly budget alert** was not changed.
The web/backend application itself is not deployed by this guard setup. Vercel
Hobby is the selected plan for the future web deployment; no paid upgrade is authorized.

## What this does not guarantee

- RM40 is a trigger on reported monthly GCP cost, not an instantaneous or lifetime cap.
- Billing data and notifications lag. Additional cost is approximately spending rate
  multiplied by delay, plus late-reported charges; there is no guaranteed maximum.
- Independent Vercel, Neon and OpenRouter bills are outside this project's guard.
- No actual live billing disconnection was performed as a test. The function checks
  its permission, but an account-association lock or later IAM/delivery change can
  still prevent shutdown. Keep the budget publisher and trigger permissions intact.
- Disconnecting billing interrupts services and can affect resource availability.
  Never automatically reconnect billing during a normal application deploy.

## Deployment corrections verified during setup

- Current Google budget publisher is `billing-budget-alert@system.gserviceaccount.com`.
- Current gcloud budget responses use `notificationsRule`; the script also supports
  the older `allUpdatesRule` shape.
- `functions deploy --trigger-topic` takes a topic ID, not its full resource path.
- gcloud flags-file keys require leading `--`. JSON flags files preserve Windows
  quoting for the test message; arming validates structured log fields locally.

Source files: `scripts/gcp/killswitch/` and `scripts/gcp/deploy-cost-guard.ps1`.
Offline deployment checks: `scripts/gcp/test-cost-guard.ps1`.
