#!/usr/bin/env bash
# Post-deploy checks against the live api, and the web app if its origin is
# given. Fails loudly.
#   PROJECT_ID=... REGION=... [WEB_URL=https://your-app.vercel.app] \
#     bash scripts/gcp/smoke.sh
set -euo pipefail
source "$(dirname "$0")/common.sh"
API_URL="$(service_url sdoc-api)"
fail() { echo "SMOKE FAIL: $*" >&2; exit 1; }
code() { curl -s -o /dev/null -w '%{http_code}' --max-time 60 "$@"; }

health="$(curl -s --max-time 60 "$API_URL/health")"
"$PY" -c '
import json, sys
h = json.loads(sys.argv[1])
assert h["writes_protected"] is True, "writes are NOT protected (DEMO_PASSCODE empty?)"
assert h["data_dir"]["present"], "dataset missing from the image"
assert h["database"]["ok"], "database unreachable"
assert h["run_executor"] == "cloudrun-job", "api is not using the worker job"
' "$health" || fail "api /health (see above)"
[[ "$(code -X POST "$API_URL/api/pipeline/run")" == 401 ]] || fail "unauthenticated run was not refused"
n="$(curl -s --max-time 60 "$API_URL/api/emails" | "$PY" -c 'import json,sys; print(len(json.load(sys.stdin)))')"
(( n >= 520 )) || fail "expected at least 520 emails, got $n (seed with demo-reset.sh)"

if [[ -n "${WEB_URL:-}" ]]; then
  for i in 1 2 3; do [[ "$(code "$WEB_URL/")" == 200 ]] && break; sleep 5; done
  [[ "$(code "$WEB_URL/")" == 200 ]] || fail "web / is not 200"
  [[ "$(code -X POST "$WEB_URL/api/pipeline/run")" == 401 ]] || fail "web proxy did not reach the api"
  echo "smoke OK: $WEB_URL"
else
  echo "WEB_URL not set; skipped the Vercel-hosted web checks" >&2
  echo "smoke OK: $API_URL"
fi
