import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_non_activatable_release_record_is_exact():
    data = json.loads((ROOT / "config/non-activatable-releases.json").read_text())
    entry, = data["releases"]
    assert entry["protected_sha"] == "01f2676772b11919e1d79cc74d36bc5eeaa682cd"
    assert entry["status"] == "NON_ACTIVATABLE"
    assert entry["replacement_required"] is True


def test_environment_rotation_contract_is_atomic_and_complete():
    data = json.loads(
        (ROOT / "config/environment-secret-rotation-ownership.json").read_text()
    )
    env = data["environment_file"]
    assert env == {
        "path": "/etc/codestra/secrets/control-plane.env",
        "owner": "root:root",
        "mode": "0600",
        "atomic_group": "control-plane-email-authorities",
    }
    secrets = {entry["secret_id"]: entry for entry in data["secrets"]}
    assert set(secrets) == {
        "ODOO_OUTBOUND_HMAC_SECRET",
        "KLYROW_WEBHOOK_SECRET",
    }
    for entry in secrets.values():
        assert len(entry["consumers"]) >= 3
        assert entry["new_auth_check"].endswith(" new")
        assert entry["old_auth_check"].endswith(" old --expect-rejected")
    rollout = data["rollout"]
    assert any("atomically replace both" in step for step in rollout["success_order"])
    assert any("revoke predecessors" in step for step in rollout["success_order"])
    assert any("restore the complete environment" in step for step in rollout["rollback_order"])
    assert "old-key rejection result" in rollout["required_evidence"]


def test_recovery_runbook_never_embeds_key_material():
    text = (ROOT / "docs/SIGNING_AUTHORITY_RECOVERY.md").read_text()
    assert "BEGIN OPENSSH PRIVATE KEY" not in text
    assert "BEGIN PRIVATE KEY" not in text
    assert "ssh-ed25519 AAAA" not in text
    assert "codestra-release" in text
