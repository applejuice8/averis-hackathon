#!/usr/bin/env bash
# One-time, re-runnable GCP setup for the pinned project (task-13 addendum:
# averis-email-system / 969206696114, asia-southeast1, billing account
# 015CE1-381F1A-582702 — see common.sh). Creates secret CONTAINERS only;
# values come from set-secrets.sh. Never links billing: require_billing
# (common.sh) refuses instead, because linking billing is an operator
# decision, not something this script does automatically. The budget /
# kill switch is a separate, already-deployed script — see the note this
# prints at the end — and is not recreated here.
#   ALERT_EMAIL=you@example.com bash scripts/gcp/bootstrap.sh
set -euo pipefail
cd "$(dirname "$0")"
: "${ALERT_EMAIL:?set ALERT_EMAIL (uptime + future alerts)}"
GITHUB_REPO="${GITHUB_REPO:-applejuice8/secret-hack}"
source ./common.sh
require_billing
quiet() { "$@" >/dev/null 2>&1; }
step() { echo "==> $*"; }

step "project $PROJECT_ID"
actual_number="$(gcloud_p projects describe "$PROJECT_ID" --format='value(projectNumber)')"
[[ "$actual_number" == "$PROJECT_NUMBER" ]] ||
  { echo "project number mismatch: $PROJECT_ID is $actual_number, expected $PROJECT_NUMBER" >&2; exit 1; }

step "APIs"
gcloud_p services enable run.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com iam.googleapis.com iamcredentials.googleapis.com \
  sts.googleapis.com storage.googleapis.com monitoring.googleapis.com \
  cloudresourcemanager.googleapis.com

step "Artifact Registry '$AR_REPO' (keeps the 3 newest images)"
quiet gcloud_p artifacts repositories describe "$AR_REPO" --location="$REGION" ||
  gcloud_p artifacts repositories create "$AR_REPO" --repository-format=docker --location="$REGION"
gcloud_p artifacts repositories set-cleanup-policies "$AR_REPO" --location="$REGION" \
  --policy=ar-cleanup-policy.json --no-dry-run >/dev/null

step "function build artifacts (from the billing-guard Cloud Function, if deployed)"
# deploy-cost-guard.ps1 deploys a gen2 Cloud Function, which creates its own
# Artifact Registry repo (gcf-artifacts) and a GCS source-upload bucket
# (gcf-v2-uploads-...). Neither is managed by that script's own cleanup, so
# fold them into the same accounting here. Both are no-ops if the guard
# has not been deployed yet.
if gcloud_p artifacts repositories describe gcf-artifacts --location="$REGION" >/dev/null 2>&1; then
  gcloud_p artifacts repositories set-cleanup-policies gcf-artifacts --location="$REGION" \
    --policy=ar-cleanup-policy.json --no-dry-run >/dev/null
fi
while IFS= read -r bucket; do
  [[ -n "$bucket" ]] || continue
  gcloud_p storage buckets update "gs://$bucket" --lifecycle-file=uploads-lifecycle.json >/dev/null
done < <(gcloud_p storage buckets list --format='value(name)' 2>/dev/null | grep '^gcf-' || true)

step "uploads bucket gs://$BUCKET (private, 30-day expiry)"
quiet gcloud_p storage buckets describe "gs://$BUCKET" ||
  gcloud_p storage buckets create "gs://$BUCKET" --location="$REGION" \
    --uniform-bucket-level-access --public-access-prevention
gcloud_p storage buckets update "gs://$BUCKET" --lifecycle-file=uploads-lifecycle.json >/dev/null

step "service accounts"
for sa in sdoc-web sdoc-api sdoc-scorer sdoc-deployer; do
  quiet gcloud_p iam service-accounts describe "$sa@$PROJECT_ID.iam.gserviceaccount.com" ||
    gcloud_p iam service-accounts create "$sa" --display-name="$sa"
done

step "secret containers (values: set-secrets.sh)"
for s in "${SECRETS[@]}"; do
  quiet gcloud_p secrets describe "$s" || gcloud_p secrets create "$s" --replication-policy=automatic
done
bind_secret() {
  gcloud_p secrets add-iam-policy-binding "$1" --member="serviceAccount:$2" \
    --role=roles/secretmanager.secretAccessor >/dev/null
}
for s in NEON_DB_URI OPENROUTER_API_KEY DEMO_PASSCODE; do bind_secret "$s" "$API_SA"; done
bind_secret GROUND_TRUTH "$SCORER_SA"

step "IAM"
gcloud_p storage buckets add-iam-policy-binding "gs://$BUCKET" --member="serviceAccount:$API_SA" \
  --role=roles/storage.objectUser >/dev/null
gcloud_p projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$API_SA" \
  --role=roles/logging.logWriter --condition=None >/dev/null
gcloud_p artifacts repositories add-iam-policy-binding "$AR_REPO" --location="$REGION" \
  --member="serviceAccount:$DEPLOYER_SA" --role=roles/artifactregistry.writer >/dev/null
# run.admin, not run.developer: deploys set invoker bindings (setIamPolicy)
gcloud_p projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$DEPLOYER_SA" \
  --role=roles/run.admin --condition=None >/dev/null
for sa in "$WEB_SA" "$API_SA" "$SCORER_SA"; do
  gcloud_p iam service-accounts add-iam-policy-binding "$sa" --member="serviceAccount:$DEPLOYER_SA" \
    --role=roles/iam.serviceAccountUser >/dev/null
done

step "GitHub OIDC for $GITHUB_REPO@main (no JSON keys)"
quiet gcloud_p iam workload-identity-pools describe github --location=global ||
  gcloud_p iam workload-identity-pools create github --location=global --display-name="GitHub Actions"
quiet gcloud_p iam workload-identity-pools providers describe github-actions --location=global --workload-identity-pool=github ||
  gcloud_p iam workload-identity-pools providers create-oidc github-actions --location=global \
    --workload-identity-pool=github --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
    --attribute-condition="assertion.repository=='$GITHUB_REPO' && assertion.ref=='refs/heads/main'"
gcloud_p iam service-accounts add-iam-policy-binding "$DEPLOYER_SA" --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github/attribute.repository/$GITHUB_REPO" >/dev/null

step "alert channel for $ALERT_EMAIL"
CHANNEL="$(find_channel "$ALERT_EMAIL")"
if [[ -z "$CHANNEL" ]]; then
  body="$("$PY" -c 'import json,sys; print(json.dumps({"type": "email", "displayName": "SDOC alerts", "labels": {"email_address": sys.argv[1]}}))' "$ALERT_EMAIL")"
  CHANNEL="$(gapi POST "https://monitoring.googleapis.com/v3/projects/$PROJECT_ID/notificationChannels" "$body" |
    "$PY" -c 'import json,sys; print(json.load(sys.stdin)["name"])')"
fi

cat <<EOF

Bootstrap complete. Next:
  1. bash scripts/gcp/set-secrets.sh .env             (operator only)
  2. WEB_URL=https://<vercel-app> bash scripts/gcp/deploy.sh
  3. bash scripts/gcp/demo-reset.sh                   (first seed)
  4. WEB_URL=https://<vercel-app> bash scripts/gcp/smoke.sh

The billing kill switch is deployed and armed separately:
  scripts/gcp/deploy-cost-guard.ps1 / scripts/gcp/test-cost-guard.ps1

GitHub repo variables for a future deploy-on-merge workflow (repo admin):
  GCP_PROJECT_ID=$PROJECT_ID
  GCP_PROJECT_NUMBER=$PROJECT_NUMBER
  GCP_REGION=$REGION
  GCP_WIF_PROVIDER=projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github/providers/github-actions
  GCP_DEPLOYER_SA=$DEPLOYER_SA
EOF
