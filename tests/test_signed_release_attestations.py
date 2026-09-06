import base64
import hashlib
import json
from copy import deepcopy

import pytest

from tools.verify_signed_release_attestations import validate
from tools.verify_slsa_provenance_attestation import (
    AUTHORIZED_BUILDER,
    EXPECTED_BUILD_TYPE,
)

SOURCE = "b" * 40
DIGEST = "sha256:" + "a" * 64
IMAGE = "ghcr.io/appolon1908-hue/codestra-middleware"


def write_statement(path, statement):
    path.write_text(
        json.dumps(
            {"payload": base64.b64encode(json.dumps(statement).encode()).decode()}
        )
    )


@pytest.fixture
def evidence(tmp_path):
    sbom = {"spdxVersion": "SPDX-2.3", "packages": []}
    sbom_path = tmp_path / "middleware.spdx.json"
    sbom_path.write_text(json.dumps(sbom))
    manifest = {
        "source": {"git_sha": SOURCE},
        "image": {
            "digest": DIGEST,
            "repository": IMAGE,
            "reference": IMAGE + "@" + DIGEST,
            "platforms": ["linux/amd64"],
        },
        "build": {"workflow_identity": AUTHORIZED_BUILDER},
        "artifacts": {
            "sbom": {
                "path": "middleware.spdx.json",
                "sha256": "sha256:"
                + hashlib.sha256(sbom_path.read_bytes()).hexdigest(),
            }
        },
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    predicate = {
        "buildDefinition": {
            "buildType": EXPECTED_BUILD_TYPE,
            "externalParameters": {"sourceSha": SOURCE, "platform": "linux/amd64"},
            "resolvedDependencies": [
                {
                    "uri": f"git+https://github.com/appolon1908-hue/Middleware-@{SOURCE}",
                    "digest": {"gitCommit": SOURCE},
                }
            ],
        },
        "runDetails": {"builder": {"id": AUTHORIZED_BUILDER}},
    }
    statement = {
        "_type": "https://in-toto.io/Statement/v0.1",
        "subject": [{"name": IMAGE, "digest": {"sha256": DIGEST[7:]}}],
        "predicateType": "https://slsa.dev/provenance/v1",
        "predicate": predicate,
    }
    provenance_path = tmp_path / "provenance-verified.json"
    write_statement(provenance_path, statement)
    sbom_statement = deepcopy(statement)
    sbom_statement.update(predicateType="https://spdx.dev/Document", predicate=sbom)
    sbom_verified = tmp_path / "sbom-verified.json"
    write_statement(sbom_verified, sbom_statement)
    return (
        [manifest_path, sbom_path, provenance_path, sbom_verified, SOURCE, DIGEST],
        statement,
        sbom_statement,
    )


def test_canonical_signed_release_bindings(evidence):
    args, _, _ = evidence
    validate(*args)


@pytest.mark.parametrize("which", [2, 3])
@pytest.mark.parametrize("field", ["subject", "predicate", "predicateType", "_type"])
def test_wrong_attestation_rejected(evidence, which, field):
    args, provenance, sbom = evidence
    statement = provenance if which == 2 else sbom
    statement[field] = [] if field == "subject" else "wrong"
    write_statement(args[which], statement)
    with pytest.raises(ValueError):
        validate(*args)


@pytest.mark.parametrize("index", [2, 3])
def test_empty_attestation_rejected(evidence, index):
    args, _, _ = evidence
    args[index].write_text("[]")
    with pytest.raises(ValueError):
        validate(*args)


def test_modified_sbom_rejected(evidence):
    args, _, _ = evidence
    args[1].write_text("{}")
    with pytest.raises(ValueError, match="SPDX SBOM"):
        validate(*args)


@pytest.mark.parametrize("index", [4, 5])
def test_wrong_pinned_tuple_rejected(evidence, index):
    args, _, _ = evidence
    args[index] = "wrong"
    with pytest.raises(ValueError, match="authority"):
        validate(*args)
