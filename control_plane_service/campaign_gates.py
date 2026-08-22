"""Fail-closed, campaign-scoped channel gates.

The first production candidate is deliberately not a global email switch.  An
empty canary allowlist authorizes policy simulation only and cannot dispatch.
"""
from __future__ import annotations

import os

from .core import ControlPlaneError


def _enabled(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() == "true"


def authorize_campaign_email(value: dict, *, simulation: bool = False) -> None:
    campaign = str(value.get("campaign_id") or "")
    if campaign != "COD-WEB-OUT":
        if not _enabled("GLOBAL_EMAIL_PRODUCTION"):
            raise ControlPlaneError("campaign_email_gate_denied")
        return
    if str(value.get("tenant_id") or "") != "COD":
        raise ControlPlaneError("campaign_tenant_denied")
    business_unit = str(value.get("business_unit_id") or "")
    if business_unit and business_unit != "COD":
        raise ControlPlaneError("campaign_business_unit_denied")
    if not _enabled("COD_WEB_OUT_EMAIL_ENABLED"):
        raise ControlPlaneError("campaign_email_gate_denied")
    if os.getenv("COD_WEB_OUT_EMAIL_MODE", "DISABLED") != "CANARY":
        raise ControlPlaneError("campaign_email_mode_denied")
    if not _enabled("COD_WEB_OUT_EMAIL_ALLOWLIST_REQUIRED"):
        raise ControlPlaneError("canary_allowlist_required")
    recipient = str(value.get("recipient") or "").strip().casefold()
    allowlist = {
        item.strip().casefold() for item in
        os.getenv("COD_WEB_OUT_CANARY_RECIPIENT", "").split(",") if item.strip()
    }
    if simulation and not recipient and not allowlist:
        if value.get("external_submission") is not False:
            raise ControlPlaneError("simulation_must_disable_external_submission")
        return
    if not recipient or recipient not in allowlist:
        raise ControlPlaneError("canary_recipient_denied")


def authorize_channel(value: dict, *, simulation: bool = False) -> None:
    if not _enabled("CAMPAIGN_SCOPED_CHANNEL_GATES_ENABLED"):
        return
    channel = str(value.get("channel") or "")
    if channel == "email":
        authorize_campaign_email(value, simulation=simulation)
    elif channel == "sms" and not _enabled("SMS_PRODUCTION"):
        raise ControlPlaneError("sms_production_disabled")
