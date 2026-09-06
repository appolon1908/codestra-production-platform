from copy import deepcopy
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from tools.validate_production_database_manifest import validate


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "PRODUCTION-DATABASE-MANIFEST.yaml"


def test_production_database_manifest_is_complete_and_fail_closed():
    validate(MANIFEST)
    document = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    assert document["certification_status"] == "FAIL"
    assert len(document["components"]) == 21
    assert any(c["isolated_restore"] != "PASS" for c in document["components"])


def test_pass_cannot_be_claimed_without_every_restore_and_off_host_copy(tmp_path):
    document = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    document["certification_status"] = "PASS"
    candidate = tmp_path / "manifest.yaml"
    candidate.write_text(
        yaml.safe_dump(document, sort_keys=False, width=10000), encoding="utf-8"
    )
    with pytest.raises(AssertionError):
        validate(candidate)


def test_missing_store_is_rejected(tmp_path):
    document = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    document["components"] = deepcopy(document["components"][:-1])
    candidate = tmp_path / "manifest.yaml"
    candidate.write_text(
        yaml.safe_dump(document, sort_keys=False, width=10000), encoding="utf-8"
    )
    with pytest.raises(AssertionError, match="coverage mismatch"):
        validate(candidate)


def test_durable_store_cannot_exempt_off_host_backup(tmp_path):
    document = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    document["components"][0]["off_host_backup"] = "N/A"
    candidate = tmp_path / "manifest.yaml"
    candidate.write_text(
        yaml.safe_dump(document, sort_keys=False, width=10000), encoding="utf-8"
    )
    with pytest.raises(AssertionError):
        validate(candidate)


def test_pass_requires_checksum_bound_evidence_root(tmp_path):
    document = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    document["certification_status"] = "PASS"
    for component in document["components"]:
        component["isolated_restore"] = "PASS"
        if component["kind"] != "redis":
            component["local_backup"] = "PASS"
            component["off_host_backup"] = "PASS"
    candidate = tmp_path / "manifest.yaml"
    candidate.write_text(
        yaml.safe_dump(document, sort_keys=False, width=10000), encoding="utf-8"
    )
    with pytest.raises(AssertionError, match="evidence root"):
        validate(candidate)


def test_complete_checksum_bound_evidence_can_pass(tmp_path):
    document = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    document["certification_status"] = "PASS"
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    for component in document["components"]:
        component["isolated_restore"] = "PASS"
        if component["kind"] != "redis":
            component["local_backup"] = "PASS"
            component["off_host_backup"] = "PASS"
        payload = f"verified evidence for {component['id']}\n".encode()
        relative = f"{component['id']}.txt"
        (evidence_root / relative).write_bytes(payload)
        (evidence_root / relative).chmod(0o600)
        component["evidence_bundle"] = {
            "path": relative,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "captured_at": datetime.now(timezone.utc).isoformat(),
        }
    candidate = tmp_path / "manifest.yaml"
    candidate.write_text(
        yaml.safe_dump(document, sort_keys=False, width=10000), encoding="utf-8"
    )
    validate(candidate, evidence_root)


def test_stale_evidence_is_rejected(tmp_path):
    document = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    document["certification_status"] = "PASS"
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    stale = datetime.now(timezone.utc) - timedelta(hours=25)
    for component in document["components"]:
        component["isolated_restore"] = "PASS"
        if component["kind"] != "redis":
            component["local_backup"] = "PASS"
            component["off_host_backup"] = "PASS"
        payload = component["id"].encode()
        relative = f"{component['id']}.txt"
        (evidence_root / relative).write_bytes(payload)
        (evidence_root / relative).chmod(0o600)
        component["evidence_bundle"] = {
            "path": relative,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "captured_at": stale.isoformat(),
        }
    candidate = tmp_path / "manifest.yaml"
    candidate.write_text(
        yaml.safe_dump(document, sort_keys=False, width=10000), encoding="utf-8"
    )
    with pytest.raises(AssertionError, match="stale certification evidence"):
        validate(candidate, evidence_root)


def test_symlink_evidence_is_rejected(tmp_path):
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    target = tmp_path / "target"
    target.write_bytes(b"not trusted")
    target.chmod(0o600)
    (evidence_root / "link").symlink_to(target)
    with pytest.raises(OSError):
        from tools.validate_production_database_manifest import read_evidence

        read_evidence(evidence_root, "link")
