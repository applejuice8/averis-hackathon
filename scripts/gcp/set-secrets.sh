#!/usr/bin/env bash
# OPERATOR ONLY. Pushes secret values into Secret Manager without printing
# them: NEON_DB_URI and OPENROUTER_API_KEY from a dotenv file, the reviewer
# passcode typed (hidden) or generated, the answer key from secrets/.
#   PROJECT_ID=... REGION=... bash scripts/gcp/set-secrets.sh [.env]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "$ROOT/scripts/gcp/common.sh"
source "$ROOT/scripts/gcp/lib-env.sh"
ENV_FILE="${1:-$ROOT/.env}"
[[ -f "$ENV_FILE" ]] || { echo "no such file: $ENV_FILE" >&2; exit 1; }

push() { # push SECRET  (value on stdin; never echoed)
  gcloud_p secrets versions add "$1" --data-file=- >/dev/null
  echo "  $1: new version added"
}

for name in NEON_DB_URI OPENROUTER_API_KEY; do
  value="$(env_value "$name" "$ENV_FILE")"
  [[ -n "$value" ]] || { echo "$name is empty in $ENV_FILE" >&2; exit 1; }
  printf '%s' "$value" | push "$name"
  unset value
done

read -rsp "Reviewer passcode for judges (leave blank to generate one): " passcode
echo
if [[ -z "$passcode" ]]; then
  passcode="$("$PY" -c 'import secrets; print(secrets.token_urlsafe(9))')"
  # This is a freshly minted demo password meant to be handed to judges, not
  # disclosure of an existing secret — never do this for NEON_DB_URI,
  # OPENROUTER_API_KEY or GROUND_TRUTH above/below, and never for a
  # passcode the operator typed in themselves.
  echo "  generated passcode: $passcode   <- give this to judges in the submission form"
fi
printf '%s' "$passcode" | push DEMO_PASSCODE
unset passcode

GT="$ROOT/secrets/ground_truth.json"
[[ -f "$GT" ]] || { echo "missing $GT (see secrets/README.md)" >&2; exit 1; }
"$PY" -c 'import json,sys; sys.stdout.write(json.dumps(json.load(open(sys.argv[1])), separators=(",", ":")))' "$GT" | push GROUND_TRUTH
echo "Done. Redeploy (scripts/gcp/deploy.sh) so running services pick up the new values."
