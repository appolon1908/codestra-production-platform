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
