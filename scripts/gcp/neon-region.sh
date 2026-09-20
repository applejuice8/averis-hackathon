#!/usr/bin/env bash
# Standalone diagnostic: print the Neon provider/region and the matching
# Cloud Run region for a NEON_DB_URI in a dotenv file. Never prints the
# host, user or password.
#
# Nothing in scripts/gcp requires this to run first: for this project the
# answer is already settled (Neon ap-southeast-1, GCP asia-southeast1 — see
# the task-13 addendum) and common.sh pins REGION directly. This script is
# only useful if the database ever moves to a different Neon region.
#   bash scripts/gcp/neon-region.sh [.env]
set -euo pipefail
source "$(dirname "$0")/lib-env.sh"
ENV_FILE="${1:-.env}"
[[ -f "$ENV_FILE" ]] || { echo "no such file: $ENV_FILE" >&2; exit 1; }

uri="$(env_value NEON_DB_URI "$ENV_FILE")"
[[ -n "$uri" ]] || { echo "NEON_DB_URI is not set in $ENV_FILE" >&2; exit 1; }
host="${uri#*@}"
host="${host%%[:/?]*}"   # ep-name-123[-pooler].[c-N.]<region>.<provider>.neon.tech
unset uri
rest="${host#*.}"
unset host
region="${rest%%.*}"
if [[ "$region" =~ ^c-[0-9]+$ ]]; then rest="${rest#*.}"; region="${rest%%.*}"; fi
provider="${rest#*.}"
provider="${provider%%.*}"

case "$provider/$region" in
  aws/ap-southeast-1) gcp=asia-southeast1 ;;
  aws/ap-southeast-2) gcp=australia-southeast1 ;;
  aws/us-east-1)      gcp=us-east4 ;;
  aws/us-east-2)      gcp=us-east5 ;;
  aws/us-west-2)      gcp=us-west1 ;;
  aws/eu-central-1)   gcp=europe-west3 ;;
  aws/eu-west-2)      gcp=europe-west2 ;;
  aws/sa-east-1)      gcp=southamerica-east1 ;;
  azure/eastus2)      gcp=us-east4 ;;
  *)                  gcp=asia-southeast1 ;;
esac
echo "neon: $provider $region"
echo "gcp:  $gcp"
