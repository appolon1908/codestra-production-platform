import base64
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools.verify_attestation_predicate import validate


def envelope(statement) -> dict:
    raw = statement if isinstance(statement, bytes) else json.dumps(statement).encode()
    return {"payload": base64.b64encode(raw).decode()}


def verification(predicate: dict) -> str:
    return json.dumps(envelope({"predicate": predicate}))


def files(tmp_path, copied, verified):
    evidence = tmp_path / "sbom.json"
    evidence.write_text(copied, encoding="utf-8")
    output = tmp_path / "verified.json"
    output.write_text(verified, encoding="utf-8")
    return output, evidence


def test_verified_sbom_predicate_must_equal_copied_evidence(tmp_path) -> None:
    predicate = {"bomFormat": "CycloneDX", "components": []}
    verified, evidence = files(tmp_path, json.dumps(predicate), verification(predicate))
    validate(verified, evidence)
    evidence.write_text('{"different":true}')
    with pytest.raises(ValueError, match="differs"):
        validate(verified, evidence)


@pytest.mark.parametrize("container", ["object", "array", "json-lines"])
def test_supported_cosign_output_formats_and_key_order(tmp_path, container):
    record = envelope({"predicate": {"components": [], "bomFormat": "CycloneDX"}})
    if container == "object":
        output = json.dumps(record)
    elif container == "array":
        output = json.dumps([record, record])
    else:
        output = json.dumps(record) + "\n\n" + json.dumps(record) + "\n"
    validate(*files(tmp_path, '{"bomFormat":"CycloneDX","components":[]}', output))


@pytest.mark.parametrize("copied", ["null", "false", "1", "[]", '"text"', "{}"])
def test_rejects_non_object_or_empty_copied_predicate(tmp_path, copied):
    with pytest.raises(ValueError, match="nonempty JSON object"):
        validate(*files(tmp_path, copied, json.dumps(envelope({}))))


@pytest.mark.parametrize("output", ["", "[]", "null", "true", "[1]", "[{}]", "{}"])
def test_rejects_empty_or_malformed_verification_documents(tmp_path, output):
    with pytest.raises(ValueError):
        validate(*files(tmp_path, '{"valid":true}', output))


@pytest.mark.parametrize("payload", [None, "", 3, "%%%", "!!!!", "é"])
def test_rejects_invalid_payload_without_skipping_it(tmp_path, payload):
    with pytest.raises(ValueError):
        validate(*files(tmp_path, '{"valid":true}', json.dumps({"payload": payload})))


@pytest.mark.parametrize("statement", [None, [], False, {}, {"predicate": None}, {"predicate": {}}])
def test_rejects_invalid_decoded_statement_and_predicate(tmp_path, statement):
    with pytest.raises(ValueError):
        validate(*files(tmp_path, '{"valid":true}', json.dumps(envelope(statement))))


@pytest.mark.parametrize("bad_record", [{}, {"payload": "invalid"}, {"payload": None}])
@pytest.mark.parametrize("bad_first", [False, True])
def test_matching_record_cannot_hide_invalid_other_record(tmp_path, bad_record, bad_first):
    good = envelope({"predicate": {"valid": True}})
    records = [bad_record, good] if bad_first else [good, bad_record]
    with pytest.raises(ValueError):
        validate(*files(tmp_path, '{"valid":true}', json.dumps(records)))


@pytest.mark.parametrize("actual", [{"flag": 1}, {"nested": [1]}, {"amount": 1.0}])
def test_comparison_preserves_json_types(tmp_path, actual):
    key = next(iter(actual))
    expected = {"flag": True, "nested": [True], "amount": 1}[key]
    with pytest.raises(ValueError, match="differs"):
        validate(*files(tmp_path, json.dumps({key: expected}), verification(actual)))


def test_accepts_match_among_other_well_formed_predicates(tmp_path):
    records = [envelope({"predicate": {"other": True}}), envelope({"predicate": {"valid": True}})]
    validate(*files(tmp_path, '{"valid":true}', json.dumps(records)))


@pytest.mark.parametrize("where", ["copy", "envelope", "statement"])
def test_rejects_duplicate_keys_in_every_json_layer(tmp_path, where):
    copied = '{"valid":true}'
    output = verification({"valid": True})
    if where == "copy":
        copied = '{"valid":false,"valid":true}'
    elif where == "envelope":
        payload = envelope({"predicate": {"valid": True}})["payload"]
        output = json.dumps({"payload": payload})[:-1] + ',"payload":' + json.dumps(payload) + '}'
    else:
        output = json.dumps(envelope(b'{"predicate":{"valid":false},"predicate":{"valid":true}}'))
    with pytest.raises(ValueError, match="duplicate JSON keys"):
        validate(*files(tmp_path, copied, output))


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
@pytest.mark.parametrize("where", ["copy", "statement"])
def test_rejects_non_finite_numbers(tmp_path, constant, where):
    copied = '{"valid":true}'
    output = verification({"valid": True})
    if where == "copy":
        copied = '{"number":' + constant + '}'
    else:
        output = json.dumps(envelope(('{"predicate":{"number":' + constant + '}}').encode()))
    with pytest.raises(ValueError, match="non-finite JSON number"):
        validate(*files(tmp_path, copied, output))


@pytest.mark.parametrize("raw", [b'{', b'\xff'])
def test_rejects_corrupt_payload_json(tmp_path, raw):
    with pytest.raises(ValueError, match="malformed"):
        validate(*files(tmp_path, '{"valid":true}', json.dumps(envelope(raw))))


def test_rejects_malformed_json_lines_after_valid_record(tmp_path):
    output = verification({"valid": True}) + '\n{"payload":'
    with pytest.raises(ValueError, match="malformed JSON"):
        validate(*files(tmp_path, '{"valid":true}', output))


def test_cli_fails_without_echoing_evidence_or_traceback(tmp_path):
    verified, copied = files(tmp_path, '{"private-evidence-marker":NaN}', verification({"valid": True}))
    script = Path(__file__).resolve().parents[1] / "tools/verify_attestation_predicate.py"
    result = subprocess.run(
        [sys.executable, str(script), "--verification", str(verified), "--predicate", str(copied)],
        capture_output=True, text=True, check=False, timeout=10,
    )
    assert result.returncode == 1
    assert "verification failed" in result.stderr
    assert "private-evidence-marker" not in result.stderr
    assert "Traceback" not in result.stderr
