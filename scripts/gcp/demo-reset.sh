#!/usr/bin/env bash
# Remove uploads + their reviews, reload the dataset, run every email, score.
# Also the first-time seed.
#   PROJECT_ID=... REGION=... bash scripts/gcp/demo-reset.sh
set -euo pipefail
source "$(dirname "$0")/common.sh"
gcloud_p run jobs execute "$WORKER_JOB" --region "$REGION" --args=-m,pipeline.worker,seed,--reset --wait
