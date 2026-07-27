from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import uuid4

import pytest

from campaign_provisioning import (
    CampaignDesignRequest,
    CampaignDesignService,
    DesignConflict,
    DesignValidationError,
    SQLiteDesignRepository,
)


def request(**overrides):
    values = {
        "integration_uuid": str(uuid4()),
        "odoo_campaign_id": 123,
        "business_unit": "COD",
        "purpose": "WEB",
        "direction": "outbound",
        "environment": "production",
        "default_language": "en",
        "time_zone": "America/Santo_Domingo",
        "calling_hours": "COD-STANDARD",
        "consent_policy": "COD-CONSENT-V1",
        "dnc_policy": "GLOBAL-DNC-V1",
        "recording_policy": "COD-RECORDING-V1",
        "lead_source_policy": "COD-LEAD-SOURCE-V1",
        "callback_policy": "COD-CALLBACK-V1",
        "appointment_policy": "COD-APPOINTMENT-V1",
        "disposition_family": "COD-WEB-OUT-V1",
        "script_template": "COD-WEB-SDR",
        "n8n_template": "LEAD-FOLLOWUP-V1",
        "reporting_category": "COD-WEB",
        "owner_user_id": 10,
        "supervisor_user_id": 12,
        "activation_policy": "MANUAL-GATED",
    }
    values.update(overrides)
    return CampaignDesignRequest(**values)


def test_preview_is_complete_disabled_and_idempotent(tmp_path):
    service = CampaignDesignService(SQLiteDesignRepository(str(tmp_path / "design.db")))
    design_request = request()

    first = service.preview(design_request)
    replay = service.preview(design_request)

    assert replay == first
    assert first["odoo"]["campaign_code"] == "COD-WEB-OUT"
    assert first["vicidial"]["default_list_id"] == 21000
    assert first["vicidial"]["active"] is False
    assert first["n8n"]["workflows_active"] is False
    assert not any(first["feature_flags"].values())
    assert first["policies"]["transfer_policy"] == "same-campaign-only"


def test_staging_uses_test_range(tmp_path):
    service = CampaignDesignService(SQLiteDesignRepository(str(tmp_path / "design.db")))
    manifest = service.preview(request(environment="staging"))
    assert manifest["vicidial"]["default_list_id"] == 91000
    assert manifest["n8n"]["scope"].startswith("STG-")


def test_changed_replay_is_rejected(tmp_path):
    service = CampaignDesignService(SQLiteDesignRepository(str(tmp_path / "design.db")))
    original = request()
    service.preview(original)
    with pytest.raises(DesignConflict):
        service.preview(replace(original, purpose="AI"))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("business_unit", "OTHER"),
        ("purpose", "web"),
        ("direction", "sideways"),
        ("integration_uuid", "not-a-uuid"),
        ("consent_policy", ""),
    ],
)
def test_invalid_design_is_rejected(tmp_path, field, value):
    service = CampaignDesignService(SQLiteDesignRepository(str(tmp_path / "design.db")))
    with pytest.raises(DesignValidationError):
        service.preview(replace(request(), **{field: value}))


def test_concurrent_allocation_never_duplicates(tmp_path):
    path = str(tmp_path / "design.db")
    service = CampaignDesignService(SQLiteDesignRepository(path))
    requests = [request(odoo_campaign_id=index + 1) for index in range(24)]

    with ThreadPoolExecutor(max_workers=8) as workers:
        manifests = list(workers.map(service.preview, requests))

    list_ids = [item["vicidial"]["default_list_id"] for item in manifests]
    assert len(list_ids) == len(set(list_ids))
    assert sorted(list_ids) == list(range(21000, 21024))
