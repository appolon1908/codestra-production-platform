import json
import hashlib
from pathlib import Path

import pytest

from tools.verify_middleware_release_evidence import validate


def evidence(tmp_path: Path, digest: str = "sha256:" + "c" * 64) -> Path:
    source = "b" * 40
    sbom = {"bomFormat": "CycloneDX", "components": []}
    (tmp_path / "sbom.cdx.json").write_text(json.dumps(sbom))
    sbom_hash = hashlib.sha256((tmp_path / "sbom.cdx.json").read_bytes()).hexdigest()
    (tmp_path / "RELEASE.env").write_text(
        f"SOURCE_SHA={source}\n"
        f"IMAGE_REFERENCE=ghcr.io/codestra-srl/codestra-middleware@{digest}\n"
        f"IMAGE_DIGEST={digest}\n"
        f"SBOM_SHA256={sbom_hash}\n"
    )
    (tmp_path / "provenance.json").write_text(json.dumps({
        "buildDefinition": {"externalParameters": {"sourceSha": source}},
        "subject": {"digest": digest},
        "evidence": {"sbomSha256": sbom_hash},
        "runDetails": {"builder": {"id": (
            "https://github.com/Codestra-SRL/codestra-middleware/"
            ".github/workflows/exact-main-production-release.yml@refs/heads/main"
        )}},
    }))
    (tmp_path / "signature-verification.txt").write_text("verified\n")
    (tmp_path / "provenance-verification.txt").write_text("verified\n")
    (tmp_path / "vex").mkdir()
    encoded_digest = digest.replace(":", "%3A")
    (tmp_path / "vex" / "openvex.json").write_text(json.dumps({
        "metadata": {"source_sha": source, "image_digest": digest},
        "statements": [{"products": [{"@id": f"pkg:oci/middleware@{encoded_digest}"}]}],
    }))
    return tmp_path


def test_production_middleware_evidence_is_bound(tmp_path: Path) -> None:
    values = validate(evidence(tmp_path))
    assert values["SOURCE_SHA"] == "b" * 40
    assert values["IMAGE_DIGEST"] == "sha256:" + "c" * 64


def test_staging_only_evidence_is_rejected(tmp_path: Path) -> None:
    staging = (
        "sha256:2e15399387967c02d78cc56565157412f0cc2cb9ad6393695d17c39a88cdd2ff"
    )
    with pytest.raises(ValueError, match="staging-only"):
        validate(evidence(tmp_path, staging))


def test_mismatched_sbom_is_rejected(tmp_path: Path) -> None:
    directory = evidence(tmp_path)
    (directory / "sbom.cdx.json").write_text('{"changed":true}\n')
    with pytest.raises(ValueError, match="SBOM hash differs"):
        validate(directory)


def test_mismatched_openvex_subject_is_rejected(tmp_path: Path) -> None:
    directory = evidence(tmp_path)
    openvex_path = directory / "vex" / "openvex.json"
    openvex = json.loads(openvex_path.read_text())
    openvex["metadata"]["image_digest"] = "sha256:" + "d" * 64
    openvex_path.write_text(json.dumps(openvex))
    with pytest.raises(ValueError, match="OpenVEX subject digest differs"):
        validate(directory)


def test_protected_tuple_must_match_release_and_selection(tmp_path: Path) -> None:
    directory = evidence(tmp_path)
    values = validate(directory)
    authority = {
        "change_id": "CHG-20260821-CODESTRA-PRODUCTION-ACTIVATION-01",
        "middleware_artifact": "fixture-artifact",
        "middleware_digest": values["IMAGE_DIGEST"],
        "middleware_openvex_sha256": values["OPENVEX_SHA256"],
        "middleware_provenance_sha256": values["PROVENANCE_SHA256"],
        "middleware_run_id": "123",
        "middleware_sbom_sha256": values["SBOM_SHA256"],
        "middleware_source_sha": values["SOURCE_SHA"],
        "release_version": "fixture-release",
    }
    tuple_path = tmp_path / "tuple.json"
    tuple_path.write_text(json.dumps(authority))
    validate(directory, tuple_path, "123", "fixture-artifact")
    authority["middleware_run_id"] = "456"
    tuple_path.write_text(json.dumps(authority))
    with pytest.raises(ValueError, match="middleware_run_id mismatch"):
        validate(directory, tuple_path, "123", "fixture-artifact")
