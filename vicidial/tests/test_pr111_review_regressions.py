from __future__ import annotations

import gzip
import runpy
from pathlib import Path

import pytest

from codestra_vicidial.models import AgentCommand
from codestra_vicidial.repository import CollisionError, MemoryRepository
from codestra_vicidial.service import AdapterService, FeatureFlags
from codestra_vicidial.state import StateStore


def _context() -> dict:
    return {
        "correlation_id": "pr111-review-regression",
        "actor": "pytest",
        "reason": "verify fail-closed recovery",
        "requested_at": "2026-09-08T20:00:00Z",
    }


def _agent_command(adoption_hash: str) -> AgentCommand:
    return AgentCommand.model_validate({
        "context": _context(),
        "agent": {
            "user_id": "COD1001",
            "full_name": "Codestra Agent",
            "user_group": "COD_TEST_SDR",
            "campaigns": ["CODT0001"],
            "inbound_groups": ["COD_TEST_CLOSERS"],
            "active": False,
            "adopt_existing_sha256": adoption_hash,
        },
    })


def test_recovery_identity_mismatch_never_disables_agent(tmp_path, monkeypatch):
    repo = MemoryRepository()
    state = StateStore(tmp_path / "state.sqlite3")
    service = AdapterService(
        repo,
        state,
        FeatureFlags(writes=True, agent_sync=True),
    )
    original = {
        "user_id": "COD1001",
        "full_name": "Legacy Agent",
        "user_group": "LEGACY",
        "campaigns": ["LEGACY01"],
        "inbound_groups": [],
        "active": False,
    }
    adoption_hash = state.digest(original)
    command = _agent_command(adoption_hash)
    desired = command.agent.model_dump(mode="json") | {"active": False}
    desired["adopt_existing_sha256"] = None
    state.put_agent_adoption_intent(
        command.agent.user_id,
        adoption_hash,
        state.digest(desired),
    )

    # Simulate a retained intent followed by an out-of-band reassignment whose
    # ACL is malformed. Recovery must not disable this merely matching user_id.
    repo.agents["COD1001"] = {
        "user_id": "COD1001",
        "full_name": "Reassigned Agent",
        "user_group": "OTHER_GROUP",
        "campaigns": [],
        "inbound_groups": [],
        "active": True,
    }
    monkeypatch.setattr(
        repo,
        "agent",
        lambda _user: (_ for _ in ()).throw(CollisionError("malformed ACL")),
    )
    monkeypatch.setattr(
        repo,
        "disable_agent",
        lambda _user: pytest.fail("identity mismatch must block before mutation"),
    )

    with pytest.raises(CollisionError, match="agent recovery identity mismatch"):
        service.sync_agent("recovery-identity-mismatch", command)
    assert state.agent_adoption_intent("COD1001") is not None


def test_oci_gzip_requires_an_explicit_supported_media_type():
    namespace = runpy.run_path("vicidial/scripts/verify_oci_export.py")
    layer_diff_id = namespace["layer_diff_id"]
    payload = gzip.compress(b"layer contents", mtime=0)
    with pytest.raises(ValueError, match="unsupported OCI layer media type"):
        layer_diff_id(payload, "application/invalid+gzip")
    assert layer_diff_id(
        payload, "application/vnd.oci.image.layer.v1.tar+gzip"
    ).startswith("sha256:")


def test_oci_root_descriptor_controls_document_shape():
    namespace = runpy.run_path("vicidial/scripts/verify_oci_export.py")
    require_document_shape = namespace["require_document_shape"]
    with pytest.raises(ValueError, match="document shape conflicts"):
        require_document_shape(
            {"schemaVersion": 2, "config": {}, "layers": []},
            {"mediaType": "application/vnd.oci.image.index.v1+json"},
        )
    with pytest.raises(ValueError, match="document shape conflicts"):
        require_document_shape(
            {"schemaVersion": 2, "manifests": []},
            {"mediaType": "application/vnd.oci.image.manifest.v1+json"},
        )


def test_entrypoint_guards_all_canonical_runtime_effect_toggles():
    source = Path("vicidial/docker/entrypoint.sh").read_text()
    for flag in (
        "ENABLE_PRODUCTION_DIALING",
        "ENABLE_LIVE_CALL_CONTROL",
        "ENABLE_IVR_ROUTING",
        "ENABLE_AI_ACTIONS",
        "ENABLE_IVR_CALLBACKS",
        "ENABLE_WARM_TRANSFER",
    ):
        assert flag in source
