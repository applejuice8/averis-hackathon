"""Destructive billing action is tested with an in-memory fake, never a live account."""

import base64
import importlib.util
import json
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "scripts/gcp/killswitch/decision.py"
spec = importlib.util.spec_from_file_location("budget_decision", SOURCE)
decision = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = decision
spec.loader.exec_module(decision)

NOW = datetime(2026, 9, 20, 12, tzinfo=UTC)
CFG = decision.Config("averis-email-system", "015CE1-381F1A-582702", "test-budget", "USD", Decimal("5"))


def notification(cost=5, **overrides):
    payload = dict(costAmount=cost, budgetAmount=5, currencyCode="USD", budgetAmountType="SPECIFIED_AMOUNT",
                   costIntervalStart="2026-09-01T00:00:00Z")
    payload.update(overrides)
    return {
        "attributes": {"billingAccountId": CFG.account, "budgetId": CFG.budget_id, "schemaVersion": "1.0"},
        "publishTime": NOW.isoformat(),
        "data": base64.b64encode(json.dumps(payload).encode()).decode(),
    }


class Billing:
    def __init__(self, account=CFG.account):
        self.account = f"billingAccounts/{account}" if account else ""
        self.reads = []
        self.writes = []

    def get(self, project):
        self.reads.append(project)
        return {"billingAccountName": self.account, "billingEnabled": bool(self.account)}

    def can_disable(self, project):
        return project == CFG.project

    def disable(self, project):
        self.writes.append(project)
        self.account = ""


@pytest.mark.parametrize("cost", [0, 4.99, "4.999999"])
def test_below_threshold_never_contacts_billing(cost):
    billing = Billing()
    assert decision.handle(notification(cost), CFG, billing, NOW) == "under_budget"
    assert not billing.reads and not billing.writes


@pytest.mark.parametrize("cost", [5, "5.000000", 500])
def test_dry_run_reads_but_never_unlinks(cost):
    billing = Billing()
    assert decision.handle(notification(cost), CFG, billing, NOW) == "would_disable_billing"
    assert billing.reads == [CFG.project] and not billing.writes


def test_armed_action_is_exactly_scoped_and_idempotent():
    billing = Billing()
    armed = replace(CFG, dry_run=False, armed_at=NOW - timedelta(minutes=1))
    assert decision.handle(notification(), armed, billing, NOW) == "billing_disabled"
    assert decision.handle(notification(), armed, billing, NOW) == "already_disabled"
    assert billing.writes == ["averis-email-system"]


@pytest.mark.parametrize("amount", [True, None, "NaN", "Infinity", -1, {}, "bad"])
def test_invalid_cost_cannot_trigger(amount):
    billing = Billing()
    assert decision.handle(notification(amount), CFG, billing, NOW) == "ignored_invalid"
    assert not billing.reads


@pytest.mark.parametrize("changes", [
    {"budgetAmount": 10}, {"budgetAmount": 0}, {"currencyCode": "MYR"},
    {"budgetAmountType": "LAST_MONTH_COST"}, {"costIntervalStart": "2026-08-01T00:00:00Z"},
    {"costIntervalStart": "2026-10-01T00:00:00Z"},
])
def test_other_budget_or_period_is_ignored(changes):
    billing = Billing()
    assert decision.handle(notification(**changes), CFG, billing, NOW).startswith("ignored_")
    assert not billing.reads


@pytest.mark.parametrize("key,value", [("budgetId", "other"), ("billingAccountId", "other"), ("schemaVersion", "2")])
def test_source_identity_must_match(key, value):
    message = notification()
    message["attributes"][key] = value
    assert decision.evaluate(message, CFG, NOW) == "ignored_identity"


@pytest.mark.parametrize("message", [{}, {"data": "bad"}, {"attributes": None}, None])
def test_malformed_message_is_acknowledged(message):
    assert decision.evaluate(message, CFG, NOW) == "ignored_invalid"


def test_stale_and_pre_arming_messages_cannot_disconnect():
    message = notification()
    message["publishTime"] = (NOW - timedelta(days=2)).isoformat()
    assert decision.evaluate(message, CFG, NOW) == "ignored_stale"
    armed = replace(CFG, dry_run=False, armed_at=NOW + timedelta(seconds=1))
    assert decision.evaluate(notification(), armed, NOW) == "ignored_before_arming"


def test_changed_billing_account_is_never_unlinked():
    billing = Billing("OTHER1-OTHER2-OTHER3")
    assert decision.handle(notification(), replace(CFG, dry_run=False), billing, NOW) == "refused_different_account"
    assert not billing.writes


def test_missing_iam_permission_cannot_claim_successful_dry_run():
    class MissingPermission(Billing):
        def can_disable(self, project):
            return False

    billing = MissingPermission()
    with pytest.raises(PermissionError):
        decision.handle(notification(), CFG, billing, NOW)
    assert not billing.writes


def test_myr_budget_uses_myr_amount_without_currency_conversion():
    config = replace(CFG, currency="MYR", limit=Decimal("20"))
    assert decision.evaluate(notification(20, currencyCode="MYR", budgetAmount=20), config, NOW) == "threshold_reached"
    assert decision.evaluate(notification(19.99, currencyCode="MYR", budgetAmount=20), config, NOW) == "under_budget"


def test_api_failure_is_retried_without_blind_unlink():
    class BrokenBilling(Billing):
        def get(self, project):
            raise TimeoutError("retry me")

    billing = BrokenBilling()
    with pytest.raises(TimeoutError):
        decision.handle(notification(), replace(CFG, dry_run=False), billing, NOW)
    assert not billing.writes


def test_config_requires_explicit_arming_and_valid_positive_amount():
    env = dict(TARGET_PROJECT_ID=CFG.project, EXPECTED_BILLING_ACCOUNT=CFG.account,
               EXPECTED_BUDGET_ID=CFG.budget_id, BUDGET_CURRENCY="USD", COST_LIMIT="5")
    assert decision.Config.from_env(env).dry_run
    with pytest.raises(KeyError):
        decision.Config.from_env(dict(env, DRY_RUN="false"))
    for changes in [{"COST_LIMIT": "0"}, {"COST_LIMIT": "NaN"}, {"DRY_RUN": "maybe"}, {"BUDGET_CURRENCY": ""}]:
        with pytest.raises(ValueError):
            decision.Config.from_env(dict(env, **changes))
