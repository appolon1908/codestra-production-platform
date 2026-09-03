import copy
import hashlib
import json
from pathlib import Path

import pytest

from tools.verify_middleware_release_evidence import validate


SOURCE = "b" * 40
TREE = "c" * 40
DIGEST = "sha256:" + "d" * 64
IMAGE = "ghcr.io/appolon1908-hue/codestra-middleware"
WORKFLOW = (
    "https://github.com/appolon1908-hue/Middleware-/"
    ".github/workflows/release.yml@refs/heads/main"
)
OIDC = "https://token.actions.githubusercontent.com"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evidence(tmp_path: Path) -> tuple[Path, Path]:
    directory = tmp_path / "evidence"
    directory.mkdir()
    sbom = {
        "spdxVersion": "SPDX-2.3",
        "name": IMAGE,
        "packages": [{"name": "fixture", "versionInfo": "1"}],
        "annotations": [{"comment": DIGEST}],
    }
    (directory / "middleware.spdx.json").write_text(json.dumps(sbom))
    vulnerability = {
        "descriptor": {"name": "grype"},
        "source": {
            "type": "image",
            "target": {"userInput": f"{IMAGE}:{DIGEST}"},
        },
        "matches": [],
    }
    (directory / "middleware.grype.json").write_text(json.dumps(vulnerability))
    manifest = {
        "schema_version": "1.0",
        "release_id": f"{SOURCE[:12]}-{DIGEST[7:19]}",
        "service": "middleware-api",
        "repository": "appolon1908-hue/Middleware-",
        "source": {"git_sha": SOURCE, "git_tree_id": TREE, "ref": "refs/heads/main"},
        "image": {
            "repository": IMAGE,
            "digest": DIGEST,
            "reference": f"{IMAGE}@{DIGEST}",
            "platforms": ["linux/amd64"],
        },
        "runtime": {
            "schema_or_migration_head": "0009_observability_incidents",
            "external_effects_default": "disabled",
        },
        "build": {
            "run_id": 123,
            "run_attempt": 1,
            "workflow_identity": WORKFLOW,
            "provenance": "buildkit-mode-max",
        },
        "verification": {
            "certificate_identity": WORKFLOW,
            "oidc_issuer": OIDC,
            "transparency_log_required": True,
        },
        "promotion": {
            "staging_and_production_same_digest": True,
            "mutable_tags_authoritative": False,
        },
        "artifacts": {
            "sbom": {
                "sha256": "sha256:" + digest(directory / "middleware.spdx.json")
            },
            "vulnerability_report": {
                "sha256": "sha256:" + digest(directory / "middleware.grype.json")
            },
        },
    }
    (directory / "release-manifest.v1.json").write_text(json.dumps(manifest))
    bundle = {
        "mediaType": "application/vnd.dev.sigstore.bundle.v0.3+json",
        "messageSignature": {"messageDigest": {}, "signature": "fixture"},
        "verificationMaterial": {
            "certificate": {"rawBytes": "fixture"},
            "timestampVerificationData": {},
            "tlogEntries": [{"logIndex": "1"}],
        },
    }
    (directory / "release-manifest.v1.sigstore.json").write_text(json.dumps(bundle))
    authority = {
        "schema_version": "codestra.production-release-tuple.v2",
        "change_id": "CHG-FIXTURE",
        "release_version": "fixture",
        "middleware_repository": "appolon1908-hue/Middleware-",
        "middleware_source_sha": SOURCE,
        "middleware_source_tree": TREE,
        "middleware_image_repository": IMAGE,
        "middleware_digest": DIGEST,
        "middleware_migration_head": "0009_observability_incidents",
        "middleware_run_id": "123",
        "middleware_run_attempt": 1,
        "middleware_artifact_id": 456,
        "middleware_artifact": f"signed-middleware-release-{SOURCE}-123-1",
        "middleware_artifact_zip_sha256": "a" * 64,
        "middleware_release_manifest_sha256": digest(
            directory / "release-manifest.v1.json"
        ),
        "middleware_sigstore_bundle_sha256": digest(
            directory / "release-manifest.v1.sigstore.json"
        ),
        "middleware_sbom_sha256": digest(directory / "middleware.spdx.json"),
        "middleware_vulnerability_report_sha256": digest(
            directory / "middleware.grype.json"
        ),
        "middleware_workflow_identity": WORKFLOW,
        "middleware_oidc_issuer": OIDC,
        "middleware_external_effects_default": "disabled",
        "same_digest_promotion_required": True,
        "production_deployment_authorized": False,
    }
    tuple_path = tmp_path / "tuple.json"
    tuple_path.write_text(json.dumps(authority))
    return directory, tuple_path


def test_signed_appolon_evidence_is_bound(tmp_path: Path) -> None:
    directory, tuple_path = evidence(tmp_path)
    values = validate(directory, tuple_path)
    assert values["MIDDLEWARE_PROTECTED_SHA"] == SOURCE
    assert values["MIDDLEWARE_IMAGE_DIGEST"] == DIGEST
    assert values["MIDDLEWARE_MIGRATION_HEAD"] == "0009_observability_incidents"


def test_mismatched_sbom_is_rejected(tmp_path: Path) -> None:
    directory, tuple_path = evidence(tmp_path)
    (directory / "middleware.spdx.json").write_text('{"changed":true}\n')
    with pytest.raises(ValueError, match="middleware.spdx.json SHA-256 differs"):
        validate(directory, tuple_path)


def test_vulnerability_findings_are_rejected(tmp_path: Path) -> None:
    directory, tuple_path = evidence(tmp_path)
    report = json.loads((directory / "middleware.grype.json").read_text())
    report["matches"] = [{"vulnerability": {"id": "CVE-FIXTURE"}}]
    (directory / "middleware.grype.json").write_text(json.dumps(report))
    manifest_path = directory / "release-manifest.v1.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["artifacts"]["vulnerability_report"]["sha256"] = (
        "sha256:" + digest(directory / "middleware.grype.json")
    )
    manifest_path.write_text(json.dumps(manifest))
    authority = json.loads(tuple_path.read_text())
    authority["middleware_vulnerability_report_sha256"] = digest(
        directory / "middleware.grype.json"
    )
    authority["middleware_release_manifest_sha256"] = digest(manifest_path)
    tuple_path.write_text(json.dumps(authority))
    with pytest.raises(ValueError, match="vulnerability gate has findings"):
        validate(directory, tuple_path)


def test_source_tree_mismatch_is_rejected(tmp_path: Path) -> None:
    directory, tuple_path = evidence(tmp_path)
    authority = json.loads(tuple_path.read_text())
    authority["middleware_source_tree"] = "e" * 40
    tuple_path.write_text(json.dumps(authority))
    with pytest.raises(ValueError, match="source tree differs"):
        validate(directory, tuple_path)


def test_tuple_cannot_self_authorize_deployment(tmp_path: Path) -> None:
    directory, tuple_path = evidence(tmp_path)
    authority = json.loads(tuple_path.read_text())
    authority["production_deployment_authorized"] = True
    tuple_path.write_text(json.dumps(authority))
    with pytest.raises(ValueError, match="must not self-authorize"):
        validate(directory, tuple_path)


def test_extra_artifact_is_rejected(tmp_path: Path) -> None:
    directory, tuple_path = evidence(tmp_path)
    (directory / "unexpected.txt").write_text("unexpected")
    with pytest.raises(ValueError, match="file set is not exact"):
        validate(directory, tuple_path)
