"""Validate one project's monthly budget notification before disconnecting billing."""

import base64
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation


def money(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError("amount must be a finite non-negative number")
    try:
        amount = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("invalid amount") from exc
    if not amount.is_finite() or amount < 0:
        raise ValueError("amount must be a finite non-negative number")
    return amount


def timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return parsed.astimezone(UTC)


@dataclass(frozen=True)
class Config:
    project: str
    account: str
    budget_id: str
    currency: str
    limit: Decimal
    dry_run: bool = True
    armed_at: datetime | None = None

    @classmethod
    def from_env(cls, env):
        project = env["TARGET_PROJECT_ID"]
        account = env["EXPECTED_BILLING_ACCOUNT"]
        budget_id = env["EXPECTED_BUDGET_ID"]
        currency = env["BUDGET_CURRENCY"]
        limit = money(env["COST_LIMIT"])
        dry_run = env.get("DRY_RUN", "true")
        if not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", project):
            raise ValueError("invalid target project")
        if not re.fullmatch(r"[A-Z0-9]{6}-[A-Z0-9]{6}-[A-Z0-9]{6}", account):
            raise ValueError("invalid billing account")
        if not budget_id or not re.fullmatch(r"[A-Z]{3}", currency) or limit <= 0:
            raise ValueError("explicit budget, currency and positive limit required")
        if dry_run not in {"true", "false"}:
            raise ValueError("DRY_RUN must be true or false")
        armed_at = timestamp(env["ARMED_AT"]) if dry_run == "false" else None
        return cls(project, account, budget_id, currency, limit, dry_run == "true", armed_at)


def evaluate(message: dict, config: Config, now: datetime) -> str:
    """Malformed/unrelated/stale events are acknowledged without a billing API call."""
    try:
        attrs = message["attributes"]
        if (attrs.get("billingAccountId"), attrs.get("budgetId"), attrs.get("schemaVersion")) != (
            config.account, config.budget_id, "1.0"
        ):
            return "ignored_identity"
        published = timestamp(message["publishTime"])
        if published > now + timedelta(minutes=5) or now - published > timedelta(hours=36):
            return "ignored_stale"
        if config.armed_at and published < config.armed_at:
            return "ignored_before_arming"
        payload = json.loads(base64.b64decode(message["data"], validate=True))
        start = timestamp(payload["costIntervalStart"])
        if (start.year, start.month, start.day) != (now.year, now.month, 1) or start > published:
            return "ignored_period"
        if payload["currencyCode"] != config.currency or payload["budgetAmountType"] != "SPECIFIED_AMOUNT":
            return "ignored_currency_or_type"
        if money(payload["budgetAmount"]) != config.limit:
            return "ignored_changed_budget"
        return "threshold_reached" if money(payload["costAmount"]) >= config.limit else "under_budget"
    except (KeyError, ValueError, TypeError, AttributeError, OverflowError):
        return "ignored_invalid"


def handle(message: dict, config: Config, billing, now: datetime | None = None) -> str:
    """API failures deliberately escape so Pub/Sub retries. Never blindly unlink."""
    result = evaluate(message, config, now or datetime.now(UTC))
    if result != "threshold_reached":
        return result
    current = billing.get(config.project)
    account = current.get("billingAccountName", "")
    if not account and current.get("billingEnabled") is False:
        return "already_disabled"
    if account != f"billingAccounts/{config.account}":
        return "refused_different_account"
    if not billing.can_disable(config.project):
        raise PermissionError("runtime identity cannot disconnect this project's billing")
    if config.dry_run:
        return "would_disable_billing"
    billing.disable(config.project)
    return "billing_disabled"
