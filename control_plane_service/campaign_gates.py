"""Fail-closed, campaign-scoped channel gates.

The first production candidate is deliberately not a global email switch.  An
empty canary allowlist authorizes policy simulation only and cannot dispatch.
"""
from __future__ import annotations

import os
from pathlib import Path

from .core import ControlPlaneError


def _enabled(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() == "true"


def _canary_allowlist() -> set[str]:
    path = os.getenv("COD_WEB_OUT_CANARY_RECIPIENT_FILE", "").strip()
    if path:
        try:
            info = os.stat(path, follow_symlinks=False)
            if not os.path.isfile(path) or info.st_mode & 0o077:
                raise ControlPlaneError("canary_recipient_file_permissions_invalid")
            raw = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            raise ControlPlaneError("canary_recipient_file_unavailable") from exc
    else:
        raw = os.getenv("COD_WEB_OUT_CANARY_RECIPIENT", "")
    return {item.strip().casefold() for item in raw.split(",") if item.strip()}


def authorize_campaign_email(value: dict, *, simulation: bool = False) -> None:
    campaign = str(value.get("campaign_id") or "")
    if campaign != "COD-WEB-OUT":
        if not _enabled("GLOBAL_EMAIL_PRODUCTION"):
            raise ControlPlaneError("campaign_email_gate_denied")
        return
    if str(value.get("tenant_id") or "") != "COD":
        raise ControlPlaneError("campaign_tenant_denied")
    business_unit = str(value.get("business_unit_id") or "")
    if business_unit != "COD":
        raise ControlPlaneError("campaign_business_unit_denied")
    if not _enabled("COD_WEB_OUT_EMAIL_ENABLED"):
        raise ControlPlaneError("campaign_email_gate_denied")
    if os.getenv("COD_WEB_OUT_EMAIL_MODE", "DISABLED") != "CANARY":
        raise ControlPlaneError("campaign_email_mode_denied")
    if not _enabled("COD_WEB_OUT_EMAIL_ALLOWLIST_REQUIRED"):
        raise ControlPlaneError("canary_allowlist_required")
    recipient = str(value.get("recipient") or "").strip().casefold()
    allowlist = _canary_allowlist()
    if simulation and not recipient and not allowlist:
        if value.get("external_submission") is not False:
            raise ControlPlaneError("simulation_must_disable_external_submission")
        return
    if not recipient or recipient not in allowlist:
        raise ControlPlaneError("canary_recipient_denied")


def authorize_channel(value: dict, *, simulation: bool = False) -> None:
    channel = str(value.get("channel") or "")
    if channel in {"email", "sms"} and not _enabled("CAMPAIGN_SCOPED_CHANNEL_GATES_ENABLED"):
        raise ControlPlaneError("campaign_channel_gates_disabled")
    if channel == "email":
        authorize_campaign_email(value, simulation=simulation)
    elif channel == "sms" and not _enabled("SMS_PRODUCTION"):
        raise ControlPlaneError("sms_production_disabled")
