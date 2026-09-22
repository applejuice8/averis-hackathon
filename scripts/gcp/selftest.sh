#!/usr/bin/env bash
# Offline checks for scripts/gcp: syntax, quoting, explicit --project on
# every gcloud call, fail-loud on missing settings, no credential echoes,
# no billing-relink path, region mapping, the URL helper, and JSON files.
# No real gcloud call is ever made — scripts that would reach one are only
# run up to the point where they refuse first for a missing setting. No
# network, runs in CI.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
TMP="$(mktemp -d 2>/dev/null || mktemp -d -t sdocgcp)"
trap 'rm -rf "$TMP"' EXIT
fail() { echo "FAIL: $*" >&2; exit 1; }

# --- 1. every script parses -------------------------------------------------
for f in "$HERE"/*.sh; do bash -n "$f" || fail "syntax: $f"; done

# Sections 3-6 below check authoring practices in the scripts being
# validated. This file's own source necessarily contains the patterns it's
# searching for (as string literals inside its checks), so it excludes
# itself from those specific scans.
TARGETS=()
for f in "$HERE"/*.sh; do
  [[ "$(basename "$f")" == "selftest.sh" ]] && continue
  TARGETS+=("$f")
done

# --- 2. every *executable* script sets -euo pipefail ------------------------
# common.sh / lib-env.sh have no shebang: they're sourced, not run, and
# inherit the caller's set -e. Everything with a shebang must set it itself.
for f in "$HERE"/*.sh; do
  head -n1 "$f" | grep -q '^#!' || continue
  grep -qE '^set -euo pipefail$' "$f" || fail "missing 'set -euo pipefail': $f"
done

# --- 3. no script ever links billing ----------------------------------------
if grep -rln "gcloud billing projects link" "${TARGETS[@]}"; then
  fail "a script contains a billing-relink path (see above) — bootstrap/deploy must refuse, never relink"
fi

# --- 4. every gcloud invocation passes an explicit --project ---------------
# Convention: project-scoped calls go through gcloud_p (common.sh), which
# always appends --project. The only allowed bare `gcloud` calls are
# `gcloud auth ...` (about the caller's own credentials / local docker
# config, not a project's resources).
check_explicit_project() {
  local f="$1" line
  while IFS= read -r line; do
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    [[ "$line" == *"gcloud "* ]] || continue
    [[ "$line" == *"gcloud_p"* ]] && continue   # defines or calls the wrapper
    [[ "$line" == *"gcloud auth "* ]] && continue
    [[ "$line" == *"--project"* ]] || fail "gcloud call missing --project in $f: $line"
  done < "$f"
}
for f in "${TARGETS[@]}"; do check_explicit_project "$f"; done

# --- 5. variables are quoted (no unquoted $VAR in paths or arguments) ------
PY=""
for candidate in python3 python; do
  if "$candidate" -c "import sys" >/dev/null 2>&1; then PY="$candidate"; break; fi
done
[[ -n "$PY" ]] || fail "python is required"
if command -v shellcheck >/dev/null 2>&1; then
  # SC2086 is exactly "double quote to prevent globbing and word splitting" —
  # scoped to that one code so unrelated shellcheck opinions (style, unused
  # vars, etc.) don't gate this check. common.sh/lib-env.sh have no shebang
  # (sourced, not run), so the dialect is given explicitly.
  quoting_out="$(shellcheck --include=SC2086 -s bash "${TARGETS[@]}" 2>&1)" || {
    echo "$quoting_out"
    fail "unquoted variable(s) found (shellcheck SC2086, see above)"
  }
else
  echo "shellcheck not found on PATH; skipping the SC2086 quoting check (it runs in CI)" >&2
fi

# --- 6. no script echoes a credential ---------------------------------------
# NEON_DB_URI / OPENROUTER_API_KEY / GROUND_TRUTH content must only ever
# flow into `push` (piped to gcloud secrets), never to echo/printf/cat.
# `| push` is the one allowed sink for these variables, so exclude it.
leaks="$(grep -nE '(echo|printf|cat)[^|]*\$(value|uri|NEON_DB_URI|OPENROUTER_API_KEY|GROUND_TRUTH)\b' "${TARGETS[@]}" | grep -v '| push' || true)"
[[ -z "$leaks" ]] || fail "a script appears to print a credential value:
$leaks"

# --- 7. scripts fail loudly on missing required settings, before any gcloud call ---
# bootstrap.sh: ALERT_EMAIL has no sensible default.
out="$(cd "$HERE" && env -u ALERT_EMAIL bash bootstrap.sh 2>&1 >/dev/null)" && fail "bootstrap.sh did not refuse a missing ALERT_EMAIL"
[[ "$out" == *"ALERT_EMAIL"* ]] || fail "bootstrap.sh's missing-ALERT_EMAIL message doesn't mention it: $out"

# deploy.sh: WEB_URL has no sensible default (CORS needs the real Vercel origin).
out="$(cd "$HERE/../.." && env -u WEB_URL bash scripts/gcp/deploy.sh 2>&1 >/dev/null)" && fail "deploy.sh did not refuse a missing WEB_URL"
[[ "$out" == *"WEB_URL"* ]] || fail "deploy.sh's missing-WEB_URL message doesn't mention it: $out"

# set-secrets.sh: refuses a dotenv missing NEON_DB_URI, before touching Secret Manager.
printf 'OPENROUTER_API_KEY=x\n' > "$TMP/missing-neon.env"
out="$(bash "$HERE/set-secrets.sh" "$TMP/missing-neon.env" 2>&1)" && fail "set-secrets.sh did not refuse a missing NEON_DB_URI"
[[ "$out" == *"NEON_DB_URI"* ]] || fail "set-secrets.sh's missing-NEON_DB_URI message doesn't mention it: $out"

# --- 8. region mapping (neon-region.sh) — pure text, no gcloud, no network ---
check_region() { # check_region DOTENV_LINE EXPECTED_NEON EXPECTED_GCP
  printf '%s\n' "$1" > "$TMP/.env"
  local out
  out="$(bash "$HERE/neon-region.sh" "$TMP/.env")"
  [[ "$out" == *"neon: $2"* ]] || fail "neon label for [$1]: $out"
  [[ "$out" == *"gcp:  $3"* ]] || fail "gcp region for [$1]: $out"
  [[ "$out" != *hunter2* && "$out" != *alice* && "$out" != *ep-* ]] || fail "leaked connection details: $out"
}
check_region 'NEON_DB_URI=postgresql://alice:hunter2@ep-cool-darkness-123456-pooler.ap-southeast-1.aws.neon.tech/neondb?sslmode=require' "aws ap-southeast-1" asia-southeast1
check_region 'NEON_DB_URI="postgresql://alice:hunter2@ep-x-1.us-east-2.aws.neon.tech/db"   # main branch' "aws us-east-2" us-east5
check_region 'NEON_DB_URI=postgresql://alice:hunter2@ep-x-1.c-2.us-east-1.aws.neon.tech/db' "aws us-east-1" us-east4
check_region 'NEON_DB_URI=postgres://alice:hunter2@ep-x-1.eastus2.azure.neon.tech/db' "azure eastus2" us-east4

# --- 9. service_url (common.sh) ---------------------------------------------
url="$(PROJECT_ID=p REGION=asia-southeast1 PROJECT_NUMBER=123 bash -c "source '$HERE/common.sh'; service_url sdoc-web")"
[[ "$url" == "https://sdoc-web-123.asia-southeast1.run.app" ]] || fail "service_url: $url"

# --- 10. JSON files parse ----------------------------------------------------
for j in "$HERE"/*.json; do
  "$PY" -m json.tool "$j" >/dev/null || fail "json: $j"
done

echo "scripts/gcp selftest OK"
