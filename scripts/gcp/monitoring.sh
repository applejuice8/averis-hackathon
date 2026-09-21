#!/usr/bin/env bash
# Uptime checks every 5 min from 3 regions on web /healthz and api /livez.
# Process liveness only: no promise that instances remain warm; never wake Neon.
# One alert policy emails ALERT_EMAIL when either check keeps failing.
#   PROJECT_ID=... REGION=... ALERT_EMAIL=... bash scripts/gcp/monitoring.sh
set -euo pipefail
cd "$(dirname "$0")"
: "${ALERT_EMAIL:?set ALERT_EMAIL}"
: "${WEB_HOST:?set WEB_HOST to the deployed Vercel production hostname}"
: "${API_HOST:?set API_HOST from the deployed Cloud Run API status URL}"
source ./common.sh
MON="https://monitoring.googleapis.com/v3/projects/$PROJECT_ID"
PROJECT_NUMBER="$(project_number)"
export PROJECT_NUMBER

uptime_id() { # uptime_id DISPLAY_NAME -> check id or ""
  gapi GET "$MON/uptimeCheckConfigs" |
    "$PY" -c 'import json,sys; n=sys.argv[1]; print(next((c["name"].rsplit("/",1)[-1] for c in json.load(sys.stdin).get("uptimeCheckConfigs", []) if c["displayName"] == n), ""))' "$1"
}

ensure_uptime() { # ensure_uptime DISPLAY_NAME HOST PATH -> check id
  # PATH is given WITHOUT its leading slash (healthz, not /healthz) and the
  # slash is added in Python. Git Bash on Windows rewrites any argument that
  # starts with "/" into a Windows path before the native python.exe sees it,
  # which silently created checks probing "/C:/Program Files/Git/healthz".
  local id body
  id="$(uptime_id "$1")"
  if [[ -z "$id" ]]; then
    body="$("$PY" -c '
import json, sys
name, host, path, project = sys.argv[1:5]
path = "/" + path.lstrip("/")
print(json.dumps({
    "displayName": name,
    "monitoredResource": {"type": "uptime_url", "labels": {"project_id": project, "host": host}},
    "httpCheck": {"path": path, "port": 443, "useSsl": True, "validateSsl": True},
    "period": "300s", "timeout": "10s",
    "selectedRegions": ["ASIA_PACIFIC", "EUROPE", "USA_VIRGINIA"],
}))' "$1" "$2" "$3" "$PROJECT_ID")"
    id="$(gapi POST "$MON/uptimeCheckConfigs" "$body" | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["name"].rsplit("/",1)[-1])')"
  fi
  echo "$id"
}

WEB_CHECK="$(ensure_uptime sdoc-web "$WEB_HOST" healthz)"
API_CHECK="$(ensure_uptime sdoc-api-livez "$API_HOST" livez)"
CHANNEL="$(find_channel "$ALERT_EMAIL")"
[[ -n "$CHANNEL" ]] || { echo "no alert channel for $ALERT_EMAIL; run bootstrap.sh first" >&2; exit 1; }

has_policy="$(gapi GET "$MON/alertPolicies" | "$PY" -c 'import json,sys; print(any(p["displayName"] == "SDOC uptime" for p in json.load(sys.stdin).get("alertPolicies", [])))')"
if [[ "$has_policy" != "True" ]]; then
  policy="$("$PY" -c '
import json, sys
web, api, channel = sys.argv[1:4]
def down(check_id, label):
    return {"displayName": f"{label} failing", "conditionThreshold": {
        "filter": ("metric.type=\"monitoring.googleapis.com/uptime_check/check_passed\" "
                   f"AND resource.type=\"uptime_url\" AND metric.label.check_id=\"{check_id}\""),
        "aggregations": [{"alignmentPeriod": "300s", "perSeriesAligner": "ALIGN_NEXT_OLDER",
                          "crossSeriesReducer": "REDUCE_COUNT_FALSE", "groupByFields": ["resource.label.*"]}],
        "comparison": "COMPARISON_GT", "thresholdValue": 1, "duration": "600s",
        "trigger": {"count": 1}}}
print(json.dumps({"displayName": "SDOC uptime", "combiner": "OR",
                  "conditions": [down(web, "web"), down(api, "api")],
                  "notificationChannels": [channel]}))' "$WEB_CHECK" "$API_CHECK" "$CHANNEL")"
  gapi POST "$MON/alertPolicies" "$policy" >/dev/null
fi
echo "uptime checks: $WEB_CHECK, $API_CHECK -> alert policy 'SDOC uptime' -> $ALERT_EMAIL"
