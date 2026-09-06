from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest

from tools.verify_slsa_provenance_attestation import (
    AUTHORIZED_BUILDER,
    EXPECTED_BUILD_TYPE,
    PREDICATE_TYPE,
    STATEMENT_TYPE,
    validate,
)


DIGEST_HEX = "a" * 64
SOURCE_SHA = "b" * 40
IMAGE_NAME = "ghcr.io/appolon1908-hue/codestra-middleware"


def encoded(document: dict) -> dict:
    payload = json.dumps(document, separators=(",", ":")).encode()
    return {"payload": base64.b64encode(payload).decode()}


def fixture(tmp_path: Path):
    files = {
        name: tmp_path / name
        for name in ("verified.json", "provenance.json", "RELEASE.env", "sbom.cdx.json", "trivy.json", "grype-vex.json")
    }
    for name in ("sbom.cdx.json", "trivy.json", "grype-vex.json"):
        files[name].write_text(json.dumps({"file": name}, separators=(",", ":")))
    hashes = {
        name: hashlib.sha256(files[name].read_bytes()).hexdigest()
        for name in ("sbom.cdx.json", "trivy.json", "grype-vex.json")
    }
    predicate = {
        "buildDefinition": {
            "buildType": EXPECTED_BUILD_TYPE,
            "externalParameters": {"sourceSha": SOURCE_SHA, "platform": "linux/amd64"},
            "resolvedDependencies": [
                {
                    "uri": f"git+https://github.com/appolon1908-hue/Middleware-@{SOURCE_SHA}",
                    "digest": {"gitCommit": SOURCE_SHA},
                }
            ],
        },
        "runDetails": {"builder": {"id": AUTHORIZED_BUILDER}},
    }
    provenance = {
        **predicate,
        "subject": {"digest": f"sha256:{DIGEST_HEX}"},
        "evidence": {
            "sbomSha256": hashes["sbom.cdx.json"],
            "trivySha256": hashes["trivy.json"],
            "grypeSha256": hashes["grype-vex.json"],
        },
    }
    statement = {
        "_type": STATEMENT_TYPE,
        "subject": [{"name": IMAGE_NAME, "digest": {"sha256": DIGEST_HEX}}],
        "predicateType": PREDICATE_TYPE,
        "predicate": predicate,
    }
    files["provenance.json"].write_text(json.dumps(provenance))
    files["RELEASE.env"].write_text(
        f"SOURCE_SHA={SOURCE_SHA}\n"
        f"IMAGE_REFERENCE={IMAGE_NAME}@sha256:{DIGEST_HEX}\n"
        f"IMAGE_DIGEST=sha256:{DIGEST_HEX}\n"
        f"SBOM_SHA256={hashes['sbom.cdx.json']}\n"
    )
    files["verified.json"].write_text(json.dumps(encoded(statement)))
    return files, statement, provenance


def run(files: dict[str, Path]) -> None:
    validate(
        files["verified.json"],
        files["provenance.json"],
        files["RELEASE.env"],
        files["sbom.cdx.json"],
        files["trivy.json"],
        files["grype-vex.json"],
    )


@pytest.mark.parametrize("shape", ["document", "list", "ndjson"])
def test_valid_real_slsa_shape_passes(tmp_path: Path, shape: str) -> None:
    files, statement, _ = fixture(tmp_path)
    document = encoded(statement)
    if shape == "list":
        files["verified.json"].write_text(json.dumps([document]))
    elif shape == "ndjson":
        files["verified.json"].write_text(json.dumps(document) + "\n" + json.dumps(document))
    run(files)


def test_wrong_signed_subject_fails(tmp_path: Path) -> None:
    files, statement, _ = fixture(tmp_path)
    statement["subject"][0]["digest"]["sha256"] = "c" * 64
    files["verified.json"].write_text(json.dumps(encoded(statement)))
    with pytest.raises(ValueError, match="signed provenance subject digest"):
        run(files)


def test_wrong_copied_subject_fails(tmp_path: Path) -> None:
    files, _, provenance = fixture(tmp_path)
    provenance["subject"]["digest"] = "sha256:" + "c" * 64
    files["provenance.json"].write_text(json.dumps(provenance))
    with pytest.raises(ValueError, match="copied middleware provenance subject"):
        run(files)


@pytest.mark.parametrize("field", ["buildDefinition", "runDetails"])
def test_wrong_signed_slsa_predicate_fails(tmp_path: Path, field: str) -> None:
    files, _, provenance = fixture(tmp_path)
    provenance[field]["tampered"] = True
    files["provenance.json"].write_text(json.dumps(provenance))
    with pytest.raises(ValueError, match="unauthorized"):
        run(files)


def test_custom_evidence_tampering_fails(tmp_path: Path) -> None:
    files, _, provenance = fixture(tmp_path)
    provenance["evidence"]["sbomSha256"] = "c" * 64
    files["provenance.json"].write_text(json.dumps(provenance))
    with pytest.raises(ValueError, match="evidence hash"):
        run(files)


def test_sbom_file_tampering_fails(tmp_path: Path) -> None:
    files, _, _ = fixture(tmp_path)
    files["sbom.cdx.json"].write_text("tampered")
    with pytest.raises(ValueError, match="evidence hash"):
        run(files)


def test_release_env_sbom_tampering_fails(tmp_path: Path) -> None:
    files, _, _ = fixture(tmp_path)
    text = files["RELEASE.env"].read_text()
    files["RELEASE.env"].write_text(text.replace("SBOM_SHA256=", "SBOM_SHA256=" + "c" * 64 + "#"))
    with pytest.raises(ValueError, match="SBOM hash differs"):
        run(files)


def test_source_sha_tampering_fails(tmp_path: Path) -> None:
    files, _, provenance = fixture(tmp_path)
    provenance["buildDefinition"]["externalParameters"]["sourceSha"] = "c" * 40
    files["provenance.json"].write_text(json.dumps(provenance))
    with pytest.raises(ValueError, match="build definition"):
        run(files)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("buildType",), "https://attacker.invalid/build"),
        (("externalParameters", "platform"), "linux/arm64"),
        (("resolvedDependencies", 0, "uri"), "git+https://attacker.invalid/repo"),
        (("resolvedDependencies", 0, "digest", "gitCommit"), "c" * 40),
    ],
)
def test_unexpected_build_definition_fails(tmp_path: Path, path: tuple, value: str) -> None:
    files, _, provenance = fixture(tmp_path)
    target = provenance["buildDefinition"]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    files["provenance.json"].write_text(json.dumps(provenance))
    with pytest.raises(ValueError, match="build definition"):
        run(files)


def test_unauthorized_builder_fails(tmp_path: Path) -> None:
    files, _, provenance = fixture(tmp_path)
    provenance["runDetails"]["builder"]["id"] = "https://attacker.invalid/workflow"
    files["provenance.json"].write_text(json.dumps(provenance))
    with pytest.raises(ValueError, match="builder is unauthorized"):
        run(files)


def test_wrong_predicate_type_fails(tmp_path: Path) -> None:
    files, statement, _ = fixture(tmp_path)
    statement["predicateType"] = "https://attacker.invalid/type"
    files["verified.json"].write_text(json.dumps(encoded(statement)))
    with pytest.raises(ValueError, match="predicate type"):
        run(files)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({}, "no payload"),
        ({"payload": "%%%"}, "invalid base64"),
        ({"payload": base64.b64encode(b"not-json").decode()}, "invalid JSON"),
    ],
)
def test_malformed_payload_fails(tmp_path: Path, mutation: dict, message: str) -> None:
    files, _, _ = fixture(tmp_path)
    files["verified.json"].write_text(json.dumps(mutation))
    with pytest.raises(ValueError, match=message):
        run(files)


@pytest.mark.parametrize("missing", ["predicate", "subject"])
def test_missing_statement_fields_fail(tmp_path: Path, missing: str) -> None:
    files, statement, _ = fixture(tmp_path)
    del statement[missing]
    files["verified.json"].write_text(json.dumps(encoded(statement)))
    with pytest.raises(ValueError):
        run(files)


def test_malformed_document_cannot_hide_before_valid_document(tmp_path: Path) -> None:
    files, statement, _ = fixture(tmp_path)
    files["verified.json"].write_text(json.dumps([{}, encoded(statement)]))
    with pytest.raises(ValueError, match="no payload"):
        run(files)
