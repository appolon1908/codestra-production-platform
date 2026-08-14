import base64
import json

import pytest

from tools.verify_attestation_predicate import validate


def verification(predicate: dict) -> str:
    statement = json.dumps({"predicate": predicate}).encode()
    return json.dumps({"payload": base64.b64encode(statement).decode()})


def test_verified_predicate_must_equal_copied_evidence(tmp_path) -> None:
    predicate = {"bomFormat": "CycloneDX", "components": []}
    evidence = tmp_path / "sbom.json"
    evidence.write_text(json.dumps(predicate))
    verified = tmp_path / "verified.json"
    verified.write_text(verification(predicate))
    validate(verified, evidence)
    evidence.write_text('{"different":true}')
    with pytest.raises(ValueError, match="differs"):
        validate(verified, evidence)
