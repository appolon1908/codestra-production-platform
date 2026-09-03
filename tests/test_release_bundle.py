import hashlib
import json
import subprocess
import sys
from pathlib import Path


def command(root: Path, output: Path, *, digest_status: str = "PASS") -> list[str]:
    return [
        sys.executable,
        str(root / "tools/build_release_bundle.py"),
        "--root", str(root),
        "--output", str(output),
        "--commit", "a" * 40,
        "--run-id", "fixture-run",
        "--workflow-ref", "fixture-workflow",
        "--middleware-image-signature-status", digest_status,
        "--middleware-provenance-status", "PASS",
        "--middleware-sbom-attestation-status", "PASS",
        "--middleware-manifest-signature-status", "PASS",
        "--migration-revision", "0009_observability_incidents",
    ]


def test_release_bundle_is_reproducible_and_fail_closed(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    outputs = []
    for name in ("one", "two"):
        output = tmp_path / name
        subprocess.run(command(root, output), check=True)
        outputs.append(output)
    archives = [next(path.glob("*.tar.gz")) for path in outputs]
    assert hashlib.sha256(archives[0].read_bytes()).digest() == hashlib.sha256(
        archives[1].read_bytes()
    ).digest()
    deployment = json.loads((outputs[0] / "deployment-manifest.json").read_text())
    assert deployment["schema_version"] == "codestra.deployment.v2"
    assert deployment["required_flags"]
    assert not any(deployment["required_flags"].values())
    assert {
        "SEND_EVENTS",
        "ENABLE_EXTERNAL_DELIVERY",
        "ODOO_DELIVERY_ENABLED",
        "N8N_DELIVERY_ENABLED",
        "CALLBACK_DISPATCH",
        "ENABLE_VICIDIAL_WRITES",
        "PRODUCTION_DIALING",
        "LIVE_EMAIL_DELIVERY",
        "LIVE_SMS_DELIVERY",
        "LIVE_PSTN_DIALING",
        "ODOO_WRITE",
    } <= deployment["required_flags"].keys()
    release = deployment["release_tuple"]
    assert release["middleware_repository"] == "appolon1908-hue/Middleware-"
    assert release["middleware_protected_sha"] == "1aa4d505846b7494aff94bec3d7ea68c895e2dd3"
    assert release["middleware_source_tree"] == "f67ed2eb19afc67dbe51624b5ba6298ec5dc5e32"
    assert release["middleware_image"] == "ghcr.io/appolon1908-hue/codestra-middleware"
    assert release["middleware_image_digest"] == "sha256:cec8b5a1b0e713857be1dbc94b73780bf9ae1a200d0901f95cb62193b9c2f504"
    assert release["middleware_migration_head"] == "0009_observability_incidents"
    assert release["production_deployment_authorized"] is False
    for field in (
        "middleware_image_signature_verification",
        "middleware_provenance_verification",
        "middleware_sbom_attestation_verification",
        "middleware_manifest_signature_verification",
    ):
        assert release[field] == "PASS"
    sbom = json.loads((outputs[0] / "sbom.cdx.json").read_text())
    assert sbom["bomFormat"] == "CycloneDX"
    assert sbom["components"]
    provenance = json.loads((outputs[0] / "provenance.json").read_text())
    assert provenance["_type"] == "https://in-toto.io/Statement/v1"
    assert provenance["predicateType"] == "https://slsa.dev/provenance/v1"
    assert (
        provenance["predicate"]["buildDefinition"]["externalParameters"]["commit"]
        == "a" * 40
    )
    assert (
        provenance["predicate"]["runDetails"]["metadata"]["invocationId"]
        == "fixture-run"
    )


def test_release_bundle_rejects_nonpassing_cryptographic_gate(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    result = subprocess.run(
        command(root, tmp_path / "blocked", digest_status="FAIL"),
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "cryptographic verification statuses must be PASS" in result.stderr


def test_release_bundle_rejects_wrong_migration_head(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    args = command(root, tmp_path / "blocked-head")
    args[-1] = "9999_wrong"
    result = subprocess.run(args, capture_output=True, text=True)
    assert result.returncode != 0
    assert "migration revision differs" in result.stderr
