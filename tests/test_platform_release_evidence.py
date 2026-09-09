"""Synthetic offline evidence; none of these artifacts certify a runtime."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema.exceptions import ValidationError

from scripts.validate_platform_release_evidence import validate_release_evidence
from test_platform_authority import _release_manifest

ROOT = Path(__file__).resolve().parents[1]


def write(root, path, data):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def complete(root):
    manifest = _release_manifest()
    for field in [manifest["contracts"], manifest["runtime"], *manifest["edge"].values()]:
        field["sha256"] = write(root, field["path"], b"synthetic authority " + field["path"].encode())
    manifest["evidence"] = []
    for environment in ("staging", "production"):
        classes = ["integration", "backup", "restore", "monitoring", "rollback"]
        if environment == "production":
            classes.append("approval")
        entries = {}
        for kind in classes:
            body = {
                "schema_version": "platform-promotion-evidence.v1",
                "environment": environment, "evidence_class": kind,
                "release_id": manifest["release_id"],
                "authority_git_sha": manifest["authority"]["git_sha"],
                "service_digests": {row["service_id"]: row["image"]["digest"] for row in manifest["services"]},
                "result": "PASS", "fixture": "SYNTHETIC_NOT_RUNTIME_EVIDENCE",
            }
            path = f"evidence/{environment}/{kind}.json"
            entries[kind] = {"path": path, "sha256": write(root, path, json.dumps(body).encode()), "environment": environment}
        manifest["promotion"][environment] = {"status": "accepted", "evidence": entries}
        manifest["evidence"].extend(entries.values())
    return manifest


def test_complete_distinct_synthetic_artifacts_pass(tmp_path):
    validate_release_evidence(complete(tmp_path), root=tmp_path)


def test_relabelled_staging_artifact_does_not_authorize_production(tmp_path):
    manifest = complete(tmp_path)
    stage = manifest["promotion"]["staging"]["evidence"]["integration"]
    prod = manifest["promotion"]["production"]["evidence"]["integration"]
    prod["path"], prod["sha256"] = stage["path"], stage["sha256"]
    with pytest.raises(ValidationError):
        validate_release_evidence(manifest, root=tmp_path)


def test_same_staging_bytes_under_new_path_are_rejected(tmp_path):
    manifest = complete(tmp_path)
    stage = manifest["promotion"]["staging"]["evidence"]["integration"]
    prod = manifest["promotion"]["production"]["evidence"]["integration"]
    prod["sha256"] = write(tmp_path, prod["path"], (tmp_path / stage["path"]).read_bytes())
    with pytest.raises(ValueError, match="distinct"):
        validate_release_evidence(manifest, root=tmp_path)


@pytest.mark.parametrize("field,value", [
    ("environment", "staging"), ("evidence_class", "restore"), ("result", "FAIL"),
    ("release_id", "unrelated-release"), ("authority_git_sha", "f" * 40),
    ("service_digests", {}), ("schema_version", "unrecognized"),
])
def test_even_rehashed_artifact_must_bind_exact_release_subject(tmp_path, field, value):
    manifest = complete(tmp_path)
    ref = manifest["promotion"]["production"]["evidence"]["integration"]
    body = json.loads((tmp_path / ref["path"]).read_bytes())
    body[field] = value
    body["observation_id"] = "distinct-synthetic-observation"
    ref["sha256"] = write(tmp_path, ref["path"], json.dumps(body).encode())
    with pytest.raises(ValueError, match="subject mismatch"):
        validate_release_evidence(manifest, root=tmp_path)


def test_changed_artifact_bytes_fail_hash(tmp_path):
    manifest = complete(tmp_path)
    ref = manifest["promotion"]["production"]["evidence"]["approval"]
    (tmp_path / ref["path"]).write_text("modified")
    with pytest.raises(ValueError, match="digest mismatch"):
        validate_release_evidence(manifest, root=tmp_path)


def test_evidence_index_cannot_omit_gate_artifact(tmp_path):
    manifest = complete(tmp_path)
    manifest["evidence"].pop()
    with pytest.raises(ValueError, match="missing from evidence index"):
        validate_release_evidence(manifest, root=tmp_path)


def test_symlink_directory_cannot_supply_evidence(tmp_path):
    manifest = complete(tmp_path)
    (tmp_path / "evidence").rename(tmp_path / "redirected")
    (tmp_path / "evidence").symlink_to(tmp_path / "redirected", target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        validate_release_evidence(manifest, root=tmp_path)


def test_duplicate_json_fields_fail_closed(tmp_path):
    manifest = complete(tmp_path)
    ref = manifest["promotion"]["production"]["evidence"]["approval"]
    data = (tmp_path / ref["path"]).read_bytes().replace(b'{', b'{"environment":"staging",', 1)
    ref["sha256"] = write(tmp_path, ref["path"], data)
    with pytest.raises(ValueError, match="duplicate JSON"):
        validate_release_evidence(manifest, root=tmp_path)


def test_cli_success_does_not_authorize_deployment_and_bad_hash_fails(tmp_path):
    manifest = complete(tmp_path)
    candidate = tmp_path / "manifest.json"
    candidate.write_text(json.dumps(manifest))
    command = [sys.executable, str(ROOT / "scripts/validate_platform_release_evidence.py"),
               str(candidate), "--evidence-root", str(tmp_path)]
    passed = subprocess.run(command, capture_output=True, text=True, check=False)
    assert passed.returncode == 0, passed.stdout + passed.stderr
    assert "DEPLOYMENT_AUTHORIZED=NO" in passed.stdout
    manifest["contracts"]["sha256"] = "f" * 64
    candidate.write_text(json.dumps(manifest))
    failed = subprocess.run(command, capture_output=True, text=True, check=False)
    assert failed.returncode == 2
    assert "PLATFORM_RELEASE_EVIDENCE=FAIL" in failed.stdout
