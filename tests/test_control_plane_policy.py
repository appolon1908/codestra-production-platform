from datetime import datetime, time, timezone

import pytest

from control_plane.policy import (
    AuthorizationError,
    CampaignMode,
    CampaignPolicy,
    LeadContext,
    OriginationSafety,
    PolicyEngine,
)


def policy(mode: CampaignMode = CampaignMode.HUMAN_ONLY) -> CampaignPolicy:
    return CampaignPolicy(
        tenant_id="tenant-a",
        campaign_id="COD-WEB-OUT",
        mode=mode,
        countries=frozenset({"DO"}),
        jurisdictions=frozenset({"DO-01"}),
        timezone="America/Santo_Domingo",
        calling_days=frozenset(range(5)),
        window_start=time(9),
        window_end=time(17),
    )


def lead(**changes) -> LeadContext:
    values = {
        "tenant_id": "tenant-a",
        "campaign_id": "COD-WEB-OUT",
        "requested_mode": CampaignMode.HUMAN_ONLY,
        "country": "DO",
        "jurisdiction": "DO-01",
        "consent": True,
        "dnc": False,
        "opted_out": False,
        "observed_at": datetime(2026, 8, 14, 14, 0, tzinfo=timezone.utc),
    }
    values.update(changes)
    return LeadContext(**values)


def test_exact_tenant_campaign_and_calling_window() -> None:
    engine = PolicyEngine([policy()], OriginationSafety())
    assert engine.evaluate(lead()).eligible is True
    with pytest.raises(AuthorizationError, match="not explicitly authorized"):
        engine.evaluate(lead(tenant_id="tenant-b"))
    assert engine.evaluate(lead(dnc=True)).reason == "dnc_suppressed"
    assert engine.evaluate(lead(consent=False)).reason == "consent_missing"


def test_campaign_modes_are_fail_closed_for_ai() -> None:
    with pytest.raises(AuthorizationError, match="AI origination"):
        PolicyEngine([policy(CampaignMode.AI_ONLY)], OriginationSafety()).evaluate(
            lead(requested_mode=CampaignMode.AI_ONLY)
        )
    hybrid = PolicyEngine([policy(CampaignMode.HYBRID)], OriginationSafety())
    with pytest.raises(AuthorizationError, match="AI origination"):
        hybrid.evaluate(lead(requested_mode=CampaignMode.AI_ONLY))


def test_origination_flags_must_remain_false() -> None:
    with pytest.raises(AuthorizationError, match="not fail-closed"):
        OriginationSafety(send_events=True).assert_fail_closed()
    with pytest.raises(AuthorizationError, match="not fail-closed"):
        OriginationSafety(kill_switch=False).assert_fail_closed()
