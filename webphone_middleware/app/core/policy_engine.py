"""Canonical fail-closed policy evaluator used by API and workers."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Literal
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field


POLICY_VERSION = "2026-07-26.1"
MAX_FRESHNESS = timedelta(hours=24)
DecisionAction = Literal[
    "voice", "sms", "email", "callback", "transfer", "recording", "sync"
]


class PolicyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    correlation_id: str = Field(min_length=1, max_length=128)
    action: DecisionAction
    subject: str = Field(min_length=1, max_length=128)
    resource: str = Field(min_length=1, max_length=128)
    environment: Literal["test", "staging", "production"] | None = None
    evaluated_at: datetime | None = None
    consent_allowed: bool | None = None
    consent_observed_at: datetime | None = None
    dnc_suppressed: bool | None = None
    dnc_observed_at: datetime | None = None
    customer_timezone: str | None = None
    jurisdiction: str | None = None
    calling_window_start: time | None = None
    calling_window_end: time | None = None
    attempts: int | None = Field(default=None, ge=0)
    max_attempts: int | None = Field(default=None, ge=1)
    last_attempt_at: datetime | None = None
    minimum_spacing_seconds: int | None = Field(default=None, ge=0)
    channel_eligible: bool | None = None
    business_unit: str | None = None
    allowed_business_units: list[str] | None = None
    campaign: str | None = None
    allowed_campaigns: list[str] | None = None
    agent: str | None = None
    allowed_agents: list[str] | None = None
    callback_allowed: bool | None = None
    transfer_allowed: bool | None = None
    recording_required: bool | None = None
    disclosure_present: bool | None = None
    emergency_kill_switch: bool | None = None
    shadow_mode: bool = True


class PolicyResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    decision_id: str
    policy_version: str
    correlation_id: str
    action: DecisionAction
    subject: str
    resource: str
    allow: bool
    enforced: bool
    reason_codes: list[str]
    data_freshness: dict[str, str]
    evaluated_at: datetime
    expiration: datetime


def _aware(value: datetime | None) -> bool:
    return value is not None and value.tzinfo is not None


def _in_window(current: time, start: time, end: time) -> bool:
    if start == end:
        return False
    if start < end:
        return start <= current < end
    return current >= start or current < end


def evaluate(request: PolicyRequest) -> PolicyResult:
    now = request.evaluated_at or datetime.now(timezone.utc)
    if not _aware(now):
        now = now.replace(tzinfo=timezone.utc)
    reasons: list[str] = []
    freshness: dict[str, str] = {}

    required = {
        "consent": (request.consent_allowed, request.consent_observed_at),
        "dnc": (request.dnc_suppressed, request.dnc_observed_at),
        "timezone": (request.customer_timezone, request.customer_timezone),
        "jurisdiction": (request.jurisdiction, request.jurisdiction),
        "channel": (request.channel_eligible, request.channel_eligible),
        "business_unit": (request.business_unit, request.allowed_business_units),
        "campaign": (request.campaign, request.allowed_campaigns),
        "agent": (request.agent, request.allowed_agents),
        "kill_switch": (request.emergency_kill_switch, request.emergency_kill_switch),
    }
    for name, values in required.items():
        if any(value is None for value in values):
            reasons.append(f"missing_{name}_data")

    for name, observed in (
        ("consent", request.consent_observed_at),
        ("dnc", request.dnc_observed_at),
    ):
        if observed is not None and _aware(observed):
            age = now - observed
            freshness[name] = f"{max(0, int(age.total_seconds()))}s"
            if age < timedelta(0) or age > MAX_FRESHNESS:
                reasons.append(f"stale_{name}_data")
        else:
            freshness[name] = "missing"

    if request.emergency_kill_switch is True:
        reasons.append("emergency_kill_switch")
    if request.consent_allowed is False:
        reasons.append("consent_denied")
    if request.dnc_suppressed is True:
        reasons.append("dnc_suppressed")
    if request.channel_eligible is False:
        reasons.append(f"{request.action}_ineligible")
    if (
        request.business_unit is not None
        and request.allowed_business_units is not None
        and request.business_unit not in request.allowed_business_units
    ):
        reasons.append("business_unit_denied")
    if (
        request.campaign is not None
        and request.allowed_campaigns is not None
        and request.campaign not in request.allowed_campaigns
    ):
        reasons.append("campaign_denied")
    if (
        request.agent is not None
        and request.allowed_agents is not None
        and request.agent not in request.allowed_agents
    ):
        reasons.append("agent_denied")
    if request.action == "callback" and request.callback_allowed is not True:
        reasons.append("callback_denied")
    if request.action == "transfer" and request.transfer_allowed is not True:
        reasons.append("transfer_denied")
    if (
        request.action == "recording"
        and request.recording_required is True
        and request.disclosure_present is not True
    ):
        reasons.append("recording_disclosure_missing")

    if request.attempts is None or request.max_attempts is None:
        reasons.append("missing_attempt_limit_data")
    elif request.attempts >= request.max_attempts:
        reasons.append("attempt_limit_reached")
    if request.minimum_spacing_seconds is None:
        reasons.append("missing_attempt_spacing_data")
    elif request.last_attempt_at is not None:
        if not _aware(request.last_attempt_at):
            reasons.append("invalid_last_attempt_time")
        elif now - request.last_attempt_at < timedelta(
            seconds=request.minimum_spacing_seconds
        ):
            reasons.append("minimum_attempt_spacing")

    if request.calling_window_start is None or request.calling_window_end is None:
        reasons.append("missing_calling_hours_data")
    if request.customer_timezone:
        try:
            local = now.astimezone(ZoneInfo(request.customer_timezone))
            freshness["local_time"] = local.isoformat()
            if (
                request.calling_window_start is not None
                and request.calling_window_end is not None
                and not _in_window(
                    local.timetz().replace(tzinfo=None),
                    request.calling_window_start,
                    request.calling_window_end,
                )
            ):
                reasons.append("outside_calling_hours")
        except ZoneInfoNotFoundError:
            reasons.append("invalid_customer_timezone")

    allow = not reasons
    return PolicyResult(
        decision_id=str(uuid4()),
        policy_version=POLICY_VERSION,
        correlation_id=request.correlation_id,
        action=request.action,
        subject=request.subject,
        resource=request.resource,
        allow=allow,
        enforced=not request.shadow_mode,
        reason_codes=reasons or ["allowed"],
        data_freshness=freshness,
        evaluated_at=now,
        expiration=now + timedelta(minutes=5),
    )
