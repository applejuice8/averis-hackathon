# Shared names and helpers for scripts/gcp/*.sh — source it, don't run it.
#
# Pinned per the task-13 addendum: this project only. Override PROJECT_ID /
# REGION / PROJECT_NUMBER / BILLING_ACCOUNT only for tests (see selftest.sh) —
# a bootstrap or deploy against a different project is out of scope here.
PROJECT_ID="${PROJECT_ID:-averis-email-system}"
REGION="${REGION:-asia-southeast1}"
PROJECT_NUMBER="${PROJECT_NUMBER:-969206696114}"
BILLING_ACCOUNT="${BILLING_ACCOUNT:-015CE1-381F1A-582702}"

# Scope every gcloud call to this project without touching the user's global
# gcloud configuration. Defence in depth only — every gcloud_p call below
# also passes --project explicitly; see selftest.sh's --project check.
export CLOUDSDK_CORE_PROJECT="$PROJECT_ID"

AR_REPO=sdoc
AR_HOST="$REGION-docker.pkg.dev"
AR_PATH="$AR_HOST/$PROJECT_ID/$AR_REPO"
BUCKET="$PROJECT_ID-sdoc-uploads"
WORKER_JOB=sdoc-worker
WEB_SA="sdoc-web@$PROJECT_ID.iam.gserviceaccount.com"
API_SA="sdoc-api@$PROJECT_ID.iam.gserviceaccount.com"
SCORER_SA="sdoc-scorer@$PROJECT_ID.iam.gserviceaccount.com"
DEPLOYER_SA="sdoc-deployer@$PROJECT_ID.iam.gserviceaccount.com"
SECRETS=(NEON_DB_URI OPENROUTER_API_KEY GROUND_TRUTH)

# a python that actually runs (Windows ships a python3 stub that doesn't)
PY=""
for candidate in python3 python; do
  if "$candidate" -c "import sys" >/dev/null 2>&1; then PY="$candidate"; break; fi
done
[[ -n "$PY" ]] || { echo "python is required" >&2; exit 1; }

# gcloud_p — every project-scoped gcloud call goes through this so the
# target project is always explicit on the command line, never implied by
# gcloud's own ambient config (CLOUDSDK_CORE_PROJECT above is defence in
# depth, not a substitute). Exceptions: `gcloud auth ...` calls, which are
# about the caller's own credentials/local docker config, not a project's
# resources, and don't take --project.
gcloud_p() { gcloud "$@" --project "$PROJECT_ID"; }

project_number() {
  if [[ -n "${PROJECT_NUMBER:-}" ]]; then echo "$PROJECT_NUMBER"; return; fi
  gcloud_p projects describe "$PROJECT_ID" --format='value(projectNumber)'
}

# Cloud Run's deterministic URL: https://<service>-<project-number>.<region>.run.app
service_url() { echo "https://$1-$(project_number).$REGION.run.app"; }

# Authenticated Google REST call: gapi METHOD URL [JSON_BODY]
gapi() {
  local args=(-fsS -X "$1" -H "Authorization: Bearer $(gcloud auth print-access-token)")
  if [[ $# -ge 3 ]]; then args+=(-H "Content-Type: application/json" --data "$3"); fi
  curl "${args[@]}" "$2"
}

# The email notification channel for an address (empty if none yet)
find_channel() {
  gapi GET "https://monitoring.googleapis.com/v3/projects/$PROJECT_ID/notificationChannels" |
    "$PY" -c 'import json,sys; e=sys.argv[1]; print(next((c["name"] for c in json.load(sys.stdin).get("notificationChannels", []) if c.get("labels", {}).get("email_address") == e), ""))' "$1"
}

# require_billing — refuse to continue unless PROJECT_ID's billing is
# enabled AND linked to BILLING_ACCOUNT. Never links or changes billing:
# that stays an operator decision made in the console (or by hand), never
# something this repo's scripts do automatically.
require_billing() {
  local info enabled account
  info="$(gcloud_p billing projects describe "$PROJECT_ID" --format='value(billingEnabled,billingAccountName)' 2>&1)" ||
    { echo "billing check failed for $PROJECT_ID: $info" >&2; exit 1; }
  enabled="$(cut -f1 <<<"$info")"
  account="$(cut -f2 <<<"$info")"
  [[ "$enabled" == "True" ]] || { echo "billing is not enabled on $PROJECT_ID; refusing (this must be fixed by hand)" >&2; exit 1; }
  [[ "$account" == "billingAccounts/$BILLING_ACCOUNT" ]] ||
    { echo "$PROJECT_ID is linked to the wrong billing account ($account, expected billingAccounts/$BILLING_ACCOUNT); refusing (this must be fixed by hand)" >&2; exit 1; }
}
