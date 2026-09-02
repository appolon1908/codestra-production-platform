import hashlib
import json
import subprocess
import sys
from pathlib import Path


def test_release_bundle_is_reproducible_and_fail_closed(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    script = root / "tools" / "build_release_bundle.py"
    outputs = []
    for name in ("one", "two"):
        output = tmp_path / name
        subprocess.run(
            [
                sys.executable,
                str(script),
                "--root",
                str(root),
                "--output",
                str(output),
                "--commit",
                "a" * 40,
                "--run-id",
                "fixture-run",
                "--workflow-ref",
                "fixture-workflow",
                "--middleware-sha",
                "f199b6c40f4e467979e9a8b255a0e686321a182d",
                "--middleware-image-digest",
                "sha256:ec2cf4ca73ff072fbdd48bda108a60f103526cb3e97a721abdf38435b010908b",
                "--middleware-signature-status",
                "PASS",
                "--middleware-provenance-status",
                "PASS",
                "--middleware-sbom-sha256", "d" * 64,
                "--middleware-provenance-sha256", "e" * 64,
                "--middleware-openvex-sha256", "f" * 64,
                "--migration-revision",
                "fixture-revision-1",
            ],
            check=True,
        )
        outputs.append(output)
    archives = [next(path.glob("*.tar.gz")) for path in outputs]
    assert hashlib.sha256(archives[0].read_bytes()).digest() == hashlib.sha256(archives[1].read_bytes()).digest()
    deployment = json.loads((outputs[0] / "deployment-manifest.json").read_text())
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
    } <= deployment["required_flags"].keys()
    assert deployment["release_tuple"]["middleware_protected_sha"] == (
        "f199b6c40f4e467979e9a8b255a0e686321a182d"
    )
    assert deployment["release_tuple"]["middleware_image_digest"] == (
        "sha256:ec2cf4ca73ff072fbdd48bda108a60f103526cb3e97a721abdf38435b010908b"
    )
    sbom = json.loads((outputs[0] / "sbom.cdx.json").read_text())
    assert sbom["bomFormat"] == "CycloneDX"
    assert sbom["components"]
    provenance = json.loads((outputs[0] / "provenance.json").read_text())
    assert provenance["_type"] == "https://in-toto.io/Statement/v1"
    assert provenance["predicateType"] == "https://slsa.dev/provenance/v1"
    assert provenance["predicate"]["buildDefinition"]["externalParameters"]["commit"] == "a" * 40
    assert provenance["predicate"]["runDetails"]["metadata"]["invocationId"] == "fixture-run"


def test_release_bundle_rejects_staging_only_middleware_digest(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    result = subprocess.run(
        [
            sys.executable,
            str(root / "tools/build_release_bundle.py"),
            "--root", str(root),
            "--output", str(tmp_path / "blocked"),
            "--commit", "a" * 40,
            "--run-id", "fixture-run",
            "--workflow-ref", "fixture-workflow",
            "--middleware-sha", "b" * 40,
            "--middleware-image-digest",
            "sha256:2e15399387967c02d78cc56565157412f0cc2cb9ad6393695d17c39a88cdd2ff",
            "--middleware-signature-status", "PASS",
            "--middleware-provenance-status", "PASS",
            "--middleware-sbom-sha256", "d" * 64,
            "--middleware-provenance-sha256", "e" * 64,
            "--middleware-openvex-sha256", "f" * 64,
            "--migration-revision", "fixture-revision-1",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "staging-only middleware digest is prohibited" in result.stderr


def test_release_bundle_rejects_superseded_middleware_digest(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    result = subprocess.run(
        [
            sys.executable, str(root / "tools/build_release_bundle.py"),
            "--root", str(root), "--output", str(tmp_path / "blocked-old"),
            "--commit", "a" * 40, "--run-id", "fixture-run",
            "--workflow-ref", "fixture-workflow", "--middleware-sha", "b" * 40,
            "--middleware-image-digest",
            "sha256:336c9a31648a0481737fa4bcc3eafb02a22e4b4fc66ba7b8ec1759c087e05e02",
            "--middleware-signature-status", "PASS",
            "--middleware-provenance-status", "PASS",
            "--middleware-sbom-sha256", "d" * 64,
            "--middleware-provenance-sha256", "e" * 64,
            "--middleware-openvex-sha256", "f" * 64,
            "--migration-revision", "fixture-revision-1",
        ],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "superseded middleware digest" in result.stderr
