"""Tenant, campaign, channel and compliance authorization.

The engine is deliberately independent of telephony.  A successful decision
means only that a lead is eligible for a later reservation; it never originates
a call or changes a VICIdial campaign.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from enum import Enum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class AuthorizationError(ValueError):
    """The request is outside an exact tenant/campaign policy."""


class CampaignMode(str, Enum):
    HUMAN_ONLY = "HUMAN_ONLY"
    AI_ONLY = "AI_ONLY"
    HYBRID = "HYBRID"


@dataclass(frozen=True)
class CampaignPolicy:
    tenant_id: str
    campaign_id: str
    mode: CampaignMode
    countries: frozenset[str]
    jurisdictions: frozenset[str]
    timezone: str
    calling_days: frozenset[int]
    window_start: time
    window_end: time
    consent_required: bool = True
    manual_human_only: bool = True

    def __post_init__(self) -> None:
        if not self.tenant_id or not self.campaign_id:
            raise AuthorizationError("tenant and campaign are required")
        if not self.countries or not self.jurisdictions:
            raise AuthorizationError("country and jurisdiction allowlists are required")
        if not self.calling_days or not self.calling_days <= frozenset(range(7)):
            raise AuthorizationError("calling days are invalid")
        if self.window_start >= self.window_end:
            raise AuthorizationError("overnight or empty calling windows are prohibited")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise AuthorizationError("campaign timezone is invalid") from exc


@dataclass(frozen=True)
class LeadContext:
    tenant_id: str
    campaign_id: str
    requested_mode: CampaignMode
    country: str
    jurisdiction: str
    consent: bool
    dnc: bool
    opted_out: bool
    observed_at: datetime


@dataclass(frozen=True)
class EligibilityDecision:
    eligible: bool
    reason: str
    tenant_id: str
    campaign_id: str
    mode: CampaignMode


@dataclass(frozen=True)
class OriginationSafety:
    send_events: bool = False
    external_delivery: bool = False
    live_write: bool = False
    odoo_write: bool = False
    n8n_delivery: bool = False
    production_dialing: bool = False
    live_call_control: bool = False
    general_ai_dialing: bool = False
    kill_switch: bool = True

    def assert_fail_closed(self) -> None:
        enabled = {
            name
            for name, value in vars(self).items()
            if name != "kill_switch" and value
        }
        if enabled or not self.kill_switch:
            raise AuthorizationError(
                f"origination safety is not fail-closed: {sorted(enabled)}"
            )


class PolicyEngine:
    def __init__(self, policies: list[CampaignPolicy], safety: OriginationSafety):
        safety.assert_fail_closed()
        self.safety = safety
        self._policies: dict[tuple[str, str], CampaignPolicy] = {}
        for policy in policies:
            key = (policy.tenant_id, policy.campaign_id)
            if key in self._policies:
                raise AuthorizationError("duplicate tenant/campaign policy")
            self._policies[key] = policy

    def evaluate(self, lead: LeadContext) -> EligibilityDecision:
        policy = self._policies.get((lead.tenant_id, lead.campaign_id))
        if policy is None:
            raise AuthorizationError("tenant/campaign is not explicitly authorized")
        if lead.requested_mode != policy.mode and policy.mode != CampaignMode.HYBRID:
            raise AuthorizationError("requested mode is not authorized for campaign")
        if policy.mode == CampaignMode.AI_ONLY:
            raise AuthorizationError("AI origination requires separate authorization")
        if lead.requested_mode == CampaignMode.AI_ONLY:
            raise AuthorizationError("AI origination requires separate authorization")
        checks = (
            (lead.country in policy.countries, "country_not_allowed"),
            (lead.jurisdiction in policy.jurisdictions, "jurisdiction_not_allowed"),
            (not lead.dnc, "dnc_suppressed"),
            (not lead.opted_out, "opted_out"),
            (lead.consent or not policy.consent_required, "consent_missing"),
        )
        for passed, reason in checks:
            if not passed:
                return EligibilityDecision(False, reason, lead.tenant_id, lead.campaign_id, policy.mode)
        if lead.observed_at.tzinfo is None:
            raise AuthorizationError("observed_at must be timezone-aware")
        local = lead.observed_at.astimezone(ZoneInfo(policy.timezone))
        if local.weekday() not in policy.calling_days:
            return EligibilityDecision(False, "outside_calling_day", lead.tenant_id, lead.campaign_id, policy.mode)
        if not policy.window_start <= local.time().replace(tzinfo=None) < policy.window_end:
            return EligibilityDecision(False, "outside_calling_window", lead.tenant_id, lead.campaign_id, policy.mode)
        return EligibilityDecision(True, "eligible", lead.tenant_id, lead.campaign_id, policy.mode)
