"""CloudEvent entry point; no web endpoint, credentials, or user-selected target."""

import json
import os

import functions_framework
import google.auth
from decision import Config, handle
from google.auth.transport.requests import AuthorizedSession


class Billing:
    def __init__(self):
        credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        self.session = AuthorizedSession(credentials)

    def get(self, project):
        response = self.session.get(
            f"https://cloudbilling.googleapis.com/v1/projects/{project}/billingInfo", timeout=20
        )
        response.raise_for_status()
        return response.json()

    def can_disable(self, project):
        permission = "resourcemanager.projects.deleteBillingAssignment"
        response = self.session.post(
            f"https://cloudresourcemanager.googleapis.com/v1/projects/{project}:testIamPermissions",
            json={"permissions": [permission]}, timeout=20,
        )
        response.raise_for_status()
        return permission in response.json().get("permissions", [])

    def disable(self, project):
        response = self.session.put(
            f"https://cloudbilling.googleapis.com/v1/projects/{project}/billingInfo",
            json={"billingAccountName": ""}, timeout=20,
        )
        response.raise_for_status()
        result = response.json()
        if result.get("billingEnabled") is not False or result.get("billingAccountName"):
            raise RuntimeError("billing API did not confirm disconnection")


@functions_framework.cloud_event
def stop_billing(event):
    config = Config.from_env(os.environ)
    try:
        result = handle(event.data.get("message", {}), config, Billing())
    except Exception:
        # Do not log Pub/Sub payloads, tokens, or full HTTP responses.
        print(json.dumps({"severity": "ERROR", "event": "billing_guard_failed", "project": config.project}), flush=True)
        raise
    print(json.dumps({
        "severity": "NOTICE", "event": result, "project": config.project,
        "budget_id": config.budget_id, "limit": str(config.limit), "dry_run": config.dry_run,
    }), flush=True)
