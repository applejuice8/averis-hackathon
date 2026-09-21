#!/usr/bin/env bash
# Build, push and deploy: scorer -> worker job -> api. The web app is
# hosted on Vercel (web/vercel.json), not here — pass its origin as WEB_URL
# so the api's CORS_ORIGINS is correct. Used by people and (later) CI.
#   PROJECT_ID=... REGION=... WEB_URL=https://your-app.vercel.app \
#     [IMAGE_TAG=...] bash scripts/gcp/deploy.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
source scripts/gcp/common.sh
: "${WEB_URL:?set WEB_URL to the deployed Vercel origin (https://..., no trailing slash), used for CORS_ORIGINS on the api service}"
require_billing
TAG="${IMAGE_TAG:-$(git rev-parse --short HEAD)}"

gcloud auth configure-docker "$AR_HOST" --quiet >/dev/null
build_push() { # build_push NAME CONTEXT [docker build args...]
  local image="$AR_PATH/$1:$TAG"
  docker build -t "$image" "${@:3}" "$2"
  docker push "$image"
}
build_push api . -f api/Dockerfile
build_push scorer docs-provided/problem-statement/sdoc-hackathon-docker/server
# web is built and deployed by Vercel, not here.

# Cloud Storage volume flags: replace on update, plain add on first create.
set_uploads_flags() { # set_uploads_flags services|jobs NAME
  UPLOADS=(--add-volume "name=uploads,type=cloud-storage,bucket=$BUCKET,mount-options=uid=10001;gid=10001"
           --add-volume-mount "volume=uploads,mount-path=/data/uploads")
  if gcloud_p run "$1" describe "$2" --region "$REGION" >/dev/null 2>&1; then
    UPLOADS=(--clear-volumes --clear-volume-mounts "${UPLOADS[@]}")
  fi
}

# The service's actual URL, read back from Cloud Run after a deploy — not
# guessed from the project-number/region formula (common.sh's service_url),
# because that formula can't produce a Vercel origin and callers here always
# have a fresh deploy to read from anyway.
deployed_url() { gcloud_p run services describe "$1" --region "$REGION" --format='value(status.url)'; }

echo "==> sdoc-scorer (private)"
gcloud_p run deploy sdoc-scorer --image "$AR_PATH/scorer:$TAG" --region "$REGION" \
  --service-account "$SCORER_SA" --no-allow-unauthenticated --port 8000 \
  --cpu 1 --memory 512Mi --min-instances 0 --max-instances 1 --cpu-throttling \
  --set-secrets "/secrets/ground_truth.json=GROUND_TRUTH:latest" --quiet
gcloud_p run services add-iam-policy-binding sdoc-scorer --region "$REGION" \
  --member "serviceAccount:$API_SA" --role roles/run.invoker --quiet >/dev/null
SCORER_URL="$(deployed_url sdoc-scorer)"

API_ENV="RUN_EXECUTOR=cloudrun-job,GCP_PROJECT_ID=$PROJECT_ID,GCP_REGION=$REGION,WORKER_JOB=$WORKER_JOB,SCORER_URL=$SCORER_URL,SCORER_AUTH=gcp-id-token,LOG_FORMAT=json,CORS_ORIGINS=$WEB_URL"
API_SECRETS="NEON_DB_URI=NEON_DB_URI:latest,OPENROUTER_API_KEY=OPENROUTER_API_KEY:latest,DEMO_PASSCODE=DEMO_PASSCODE:latest"
# Gmail ingest (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REDIRECT_URI)
# is deliberately not wired in here. It's optional in api/app/core/config.py
# and degrades cleanly when unset; wiring OAuth secrets and a redirect URI
# into the cloud deploy is a separate, deliberate change (task-13 addendum).

echo "==> $WORKER_JOB (job)"
set_uploads_flags jobs "$WORKER_JOB"
gcloud_p run jobs deploy "$WORKER_JOB" --image "$AR_PATH/api:$TAG" --region "$REGION" \
  --service-account "$API_SA" --command python --args=-m,pipeline.worker,seed \
  --tasks 1 --parallelism 1 --max-retries 1 --task-timeout 1800s --cpu 1 --memory 1Gi \
  --set-env-vars "$API_ENV" --set-secrets "$API_SECRETS" "${UPLOADS[@]}" --quiet
gcloud_p run jobs add-iam-policy-binding "$WORKER_JOB" --region "$REGION" \
  --member "serviceAccount:$API_SA" --role roles/run.jobsExecutorWithOverrides --quiet >/dev/null

echo "==> sdoc-api"
set_uploads_flags services sdoc-api
# --max-instances 1 is load-bearing, not a cost trim: the duplicate-attempt
# guard (api/app/services/processing.py, per-email asyncio.Lock) and the
# active-run limit (settings.max_active_runs, api/app/api/routes/pipeline.py)
# are both per-process. Pinning this service to one instance is what makes
# them behave globally for this demo. Do not raise it without first making
# those guards cross-instance (e.g. a DB-backed lock).
gcloud_p run deploy sdoc-api --image "$AR_PATH/api:$TAG" --region "$REGION" \
  --service-account "$API_SA" --allow-unauthenticated --port 8000 \
  --cpu 1 --memory 1Gi --min-instances 0 --max-instances 1 --concurrency 40 --timeout 300 \
  --cpu-throttling --cpu-boost --execution-environment gen2 \
  --set-env-vars "$API_ENV" --set-secrets "$API_SECRETS" "${UPLOADS[@]}" --quiet
API_URL="$(deployed_url sdoc-api)"

cat <<EOF

api: $API_URL

Vercel project env var:
  API_URL=$API_URL

This deploy set CORS_ORIGINS=$WEB_URL — confirm the web app is actually
live at that origin before treating the demo as ready.
EOF
