import sqlite3

import pytest

from control_plane_service.core import ControlPlaneError
from control_plane_service.mapping_registry import MappingRegistry


@pytest.fixture
def registry(tmp_path):
    return MappingRegistry(str(tmp_path / "registry.db"))


def campaign(key="create-1"):
    return {"tenant_id":"COD","campaign_code":"TEST_SYN","name":"Synthetic",
            "direction":"OUTBOUND","telephony_enabled":False,"desired_state":"INACTIVE",
            "idempotency_key":key,"correlation_id":"9c0f086e-0dd4-4df9-b3e5-96693b612ff4",
            "immutable_payload":{"campaign_code":"TEST_SYN","desired_state":"INACTIVE"}}


def test_transactional_command_creates_uuid_job_and_outbox(registry):
    result, duplicate = registry.create_campaign(campaign(), actor="odoo")
    assert not duplicate
    assert result["entity_id"] != "TEST_SYN"
    assert result["event"]["event_kind"] == "COMMAND"
    assert result["event"]["payload"]["job_id"] == result["job_id"]
    assert result["event"]["correlation_id"] == "9c0f086e-0dd4-4df9-b3e5-96693b612ff4"
    with sqlite3.connect(registry.path) as db:
        assert db.execute("select count(*) from cp_campaign").fetchone()[0] == 1
        assert db.execute("select count(*) from cp_sync_job").fetchone()[0] == 1
        assert db.execute("select count(*) from cp_event").fetchone()[0] == 1


def test_idempotent_replay_does_not_duplicate(registry):
    first, _ = registry.create_campaign(campaign(), actor="odoo")
    second, duplicate = registry.create_campaign(campaign(), actor="odoo")
    assert duplicate and second["job_id"] == first["job_id"]
    with sqlite3.connect(registry.path) as db:
        assert db.execute("select count(*) from cp_sync_job").fetchone()[0] == 1


def test_idempotency_key_payload_conflict(registry):
    registry.create_campaign(campaign(), actor="odoo")
    changed = campaign(); changed["immutable_payload"] = {"campaign_code":"OTHER"}
    with pytest.raises(ControlPlaneError, match="idempotency_conflict"):
        registry.create_campaign(changed, actor="odoo")


def test_invalid_uuid_fields_are_rejected_before_database_work(registry):
    value = campaign()
    value["correlation_id"] = "not-a-uuid"
    with pytest.raises(ControlPlaneError, match="invalid_correlation_id"):
        registry.create_campaign(value, actor="odoo")
    value = campaign()
    value["id"] = "not-a-uuid"
    with pytest.raises(ControlPlaneError, match="invalid_entity_id"):
        registry.create_campaign(value, actor="odoo")


def test_stale_result_rejected_and_state_unchanged(registry):
    created, _ = registry.create_campaign(campaign(), actor="odoo")
    before = registry.get_job(created["job_id"])
    with pytest.raises(ControlPlaneError, match="stale_version"):
        registry.record_result(created["job_id"], {"entity_version":0,"status":"ok"}, tenant_id="COD")
    assert registry.get_job(created["job_id"])["status"] == before["status"]


def test_cross_tenant_result_is_denied(registry):
    created, _ = registry.create_campaign(campaign(), actor="odoo")
    with pytest.raises(ControlPlaneError, match="cross_tenant_denied"):
        registry.record_result(
            created["job_id"], {"entity_version": 1, "status": "ok"},
            tenant_id="OTHER",
        )


def test_invalid_state_transition_rejected(registry):
    created, _ = registry.create_campaign(campaign(), actor="odoo")
    with pytest.raises(ControlPlaneError, match="invalid_transition"):
        registry.transition_job(created["job_id"], "SYNCED", expected_version=1)


def test_readback_is_required_for_synced(registry):
    created, _ = registry.create_campaign(campaign(), actor="odoo")
    job_id = created["job_id"]
    registry.transition_job(job_id,"SYNCING",expected_version=1)
    registry.record_result(job_id,{"entity_version":1,"adapter_status":200}, tenant_id="COD")
    registry.transition_job(job_id,"VERIFYING",expected_version=1)
    drift = registry.verify(job_id,lambda _: {"active":True},{"active":False})
    assert drift["sync_status"] == "DRIFTED" and not drift["verified"]


def test_matching_readback_marks_synced(registry):
    created, _ = registry.create_campaign(campaign(), actor="odoo")
    job_id = created["job_id"]
    registry.transition_job(job_id,"SYNCING",expected_version=1)
    registry.transition_job(job_id,"VERIFYING",expected_version=1)
    result=registry.verify(job_id,lambda _: {"active":False},{"active":False})
    assert result["sync_status"] == "SYNCED" and result["verified"]


def test_high_risk_drift_cannot_auto_remediate(registry):
    result=registry.reconcile("COD","agent","agent-1","VICIDIAL",{"user":"A"},{"user":"B"},"IDENTITY_MISMATCH")
    assert result["difference_count"] == 1
    assert result["risk"] == "HIGH"
    assert not result["auto_remediation_allowed"]


def test_extension_has_one_active_owner(registry):
    stamp="2026-08-22T00:00:00+00:00"
    with sqlite3.connect(registry.path) as db:
        db.execute("insert into cp_agent values(?,?,?,?,?,?,?,?,?,?)",("a1","COD","one","ACTIVE","ACTIVE",None,1,"DRAFT",stamp,stamp))
        db.execute("insert into cp_agent values(?,?,?,?,?,?,?,?,?,?)",("a2","COD","two","ACTIVE","ACTIVE",None,1,"DRAFT",stamp,stamp))
        db.execute("insert into cp_extension values(?,?,?,?,?,?,?,?,?,?,?)",("e1","COD","6101","PJSIP/6101","6101","INACTIVE",None,1,"DRAFT",stamp,stamp))
        db.execute("insert into cp_extension_assignment values(?,?,?,?,?,?,?,?,?,?,?)",("x1","e1","a1","ACTIVE",None,1,stamp,None,None,stamp,stamp))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("insert into cp_extension_assignment values(?,?,?,?,?,?,?,?,?,?,?)",("x2","e1","a2","ACTIVE",None,1,stamp,None,None,stamp,stamp))


def test_retry_then_dead_letter(registry):
    created,_=registry.create_campaign(campaign(),actor="odoo")
    job=created["job_id"]
    assert registry.fail_job(job,"DESTINATION_UNAVAILABLE","bounded safe detail",retryable=True)=="RETRY_PENDING"
    for _ in range(4):
        status=registry.fail_job(job,"DESTINATION_UNAVAILABLE","bounded safe detail",retryable=True)
    assert status == "DEAD_LETTER"


def test_tenant_scope_rejects_invalid_value(monkeypatch):
    class Fake:
        def execute(self,*_): raise AssertionError("database must not be called")
    monkeypatch.setattr("control_plane_service.mapping_registry.is_postgres",lambda:True)
    with pytest.raises(ControlPlaneError,match="invalid_tenant"):
        MappingRegistry._tenant_scope(Fake(),"x"*65)
