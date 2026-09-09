import copy
import json
import re
from pathlib import Path
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from control_plane_service import calling_readiness as readiness


NOW = datetime(2026, 9, 9, 12, tzinfo=timezone.utc)
DIGEST = "sha256:" + "a" * 64


def evidence(now=NOW):
    expected = {
        "schema_version": "calling-evidence.v1", "environment": "staging-readonly",
        "contract_digest": DIGEST, "components": {},
    }
    for name, repository in readiness.AUTHORITIES.items():
        expected["components"][name] = {
            "repository": "appolon1908-hue/" + repository, "repository_id": 123,
            "protected_branch": "release/production-activation", "source_sha": "b" * 40,
            "artifact_digest": DIGEST, "configuration_digest": DIGEST,
            "rollback_digest": DIGEST, "migration_head": "migration-1",
            "runtime_identity": "test-runtime-" + name,
        }
    expected["release_digest"] = readiness.release_digest(expected)
    observed = copy.deepcopy(expected)
    observed["captured_at"] = now.isoformat()
    for actual in observed["components"].values():
        actual.update(contract_digest=DIGEST, captured_at=now.isoformat(), healthy=True,
                      ready=True, signature_verified=True, provenance_verified=True,
                      protected_merge_verified=True)
    observed["safety"] = {flag: False for flag in readiness.FLAGS}
    observed["safety"].update(
        calls_placed_before=0, calls_placed_after=0, unexpected_writes=0,
        middleware_authority_count=1, asterisk_ready=True, ami_ready=True,
        trunk_ready=True, mtls_identity_verified=True, callback_signature_verified=True,
        callback_replay_protection_verified=True, event_lag_seconds=0, reconciliation_depth=0,
    )
    observed["proofs"] = {
        name: {"passed": True, "contract_digest": DIGEST, "evidence_digest": DIGEST,
               "release_digest": expected["release_digest"]}
        for name in readiness.PROOFS
    }
    return expected, observed


def codes(result):
    return {entry["code"] for entry in result["blockers"]}


def test_matching_readback_is_not_activation_and_does_not_mutate():
    expected, observed = evidence()
    before = copy.deepcopy((expected, observed))
    result = readiness.evaluate(expected, observed, now=NOW)
    assert result["status"] == "READBACK_MATCHES"
    assert result["production_activation_authorized"] is False
    assert result["live_state_collected"] is False
    assert (expected, observed) == before


@pytest.mark.parametrize("field,value,code", [
    ("source_sha", "c" * 40, "SOURCE_SHA_MISMATCH"),
    ("artifact_digest", "latest", "ARTIFACT_DIGEST_MISMATCH"),
    ("configuration_digest", "sha256:" + "c" * 64, "CONFIGURATION_DIGEST_MISMATCH"),
    ("runtime_identity", "different-host", "RUNTIME_IDENTITY_MISMATCH"),
    ("migration_head", "migration-2", "MIGRATION_HEAD_MISMATCH"),
    ("repository_id", True, "REPOSITORY_ID_MISMATCH"),
    ("contract_digest", "sha256:" + "c" * 64, "CONTRACT_MISMATCH"),
    ("ready", "true", "READY_NOT_PROVEN"),
    ("signature_verified", None, "SIGNATURE_VERIFIED_NOT_PROVEN"),
])
def test_runtime_drift_fails_closed(field, value, code):
    expected, observed = evidence()
    observed["components"]["vicidial"][field] = value
    result = readiness.evaluate(expected, observed, now=NOW)
    assert {"component": "vicidial", "code": code} in result["blockers"]


@pytest.mark.parametrize("value", [True, "false", 0, None])
@pytest.mark.parametrize("flag", readiness.FLAGS)
def test_flags_must_be_explicit_json_false(flag, value):
    expected, observed = evidence()
    observed["safety"][flag] = value
    assert "EFFECT_NOT_DISABLED:" + flag in codes(readiness.evaluate(expected, observed, now=NOW))


@pytest.mark.parametrize("flag", readiness.FLAGS)
def test_omitted_action_flag_is_not_assumed_disabled(flag):
    expected, observed = evidence()
    del observed["safety"][flag]
    assert "EFFECT_NOT_DISABLED:" + flag in codes(readiness.evaluate(expected, observed, now=NOW))


def test_readiness_flags_cover_platform_action_contracts():
    import yaml

    root = Path(__file__).resolve().parents[1]
    ecosystem = yaml.safe_load((root / "contracts/telephony/codestra-calling-ecosystem.v1.yaml").read_text())
    required = set(ecosystem["activation_defaults"])
    mapping = (root / "specs/VICIDIAL_ODOO_MAPPING_SPEC.md").read_text()
    required.update(re.findall(r"^\* `(ENABLE_[A-Z_]+)`$", mapping, re.MULTILINE))
    adapter = (root / "vicidial/config/adapter.env.example").read_text()
    required.update(re.findall(r"^(ENABLE_[A-Z_]+)=", adapter, re.MULTILINE))
    defaults = (root / "config/preproduction-safety.env.example").read_text()
    required.update(re.findall(r"^([A-Z_]+)=(?:false|DISABLED)$", defaults, re.MULTILINE))
    assert required <= set(readiness.FLAGS)
    assert len(readiness.FLAGS) == len(set(readiness.FLAGS))


@pytest.mark.parametrize("value", [1, -1, False, "0", None])
def test_counter_must_be_known_integer_zero(value):
    expected, observed = evidence()
    observed["safety"]["calls_placed_after"] = value
    assert "NONZERO_OR_UNKNOWN:calls_placed_after" in codes(readiness.evaluate(expected, observed, now=NOW))


@pytest.mark.parametrize("age", [-1, 301])
@pytest.mark.parametrize("component", [False, True])
def test_stale_or_future_evidence_cannot_be_refreshed_by_wrapper(age, component):
    expected, observed = evidence()
    target = observed["components"]["vicidial"] if component else observed
    target["captured_at"] = (NOW - timedelta(seconds=age)).isoformat()
    assert "STALE_OR_INVALID_EVIDENCE" in codes(readiness.evaluate(expected, observed, now=NOW))


def test_tuple_changes_invalidate_prior_proofs():
    expected, observed = evidence()
    expected["components"]["middleware"]["source_sha"] = "d" * 40
    observed["components"]["middleware"]["source_sha"] = "d" * 40
    assert "RELEASE_DIGEST_NOT_BOUND_TO_MANIFEST" in codes(readiness.evaluate(expected, observed, now=NOW))
    expected["release_digest"] = readiness.release_digest(expected)
    observed["release_digest"] = expected["release_digest"]
    assert "MISSING_OR_MISMATCHING_PROOF" in codes(readiness.evaluate(expected, observed, now=NOW))


@pytest.mark.parametrize("section", ["components", "safety", "proofs"])
def test_malformed_or_missing_sections_block(section):
    expected, observed = evidence()
    observed[section] = []
    assert readiness.evaluate(expected, observed, now=NOW)["status"] == "BLOCKED"


def test_missing_component_and_duplicate_authority_block():
    expected, observed = evidence()
    del observed["components"]["odoo"]
    observed["safety"]["middleware_authority_count"] = 2
    result = readiness.evaluate(expected, observed, now=NOW)
    assert "MISSING_COMPONENT" in codes(result)
    assert "MIDDLEWARE_AUTHORITY_NOT_UNIQUE" in codes(result)


@pytest.mark.parametrize("raw", [b'{"x":1,"x":2}', b'[]', b'not json', b'\xff', b' ' * (readiness.MAX_BYTES + 1)])
def test_file_errors_are_bounded_and_redacted(tmp_path, raw):
    path = tmp_path / "secret-location.json"
    path.write_bytes(raw)
    result = readiness.snapshot(str(path), str(path))
    assert result["status"] == "BLOCKED"
    assert "secret-location" not in json.dumps(result)
    assert all(item["code"] == "EVIDENCE_UNAVAILABLE_OR_INVALID" for item in result["blockers"])


def test_http_route_authorization_and_readiness_status(monkeypatch, tmp_path):
    from control_plane_service import server

    expected, observed = evidence(datetime.now(timezone.utc))
    for name, value in (("EXPECTED", expected), ("OBSERVED", observed)):
        path = tmp_path / (name + ".json")
        path.write_text(json.dumps(value))
        monkeypatch.setenv("CALLING_" + name + "_EVIDENCE_FILE", str(path))
    monkeypatch.setattr(server, "operator", lambda token: ("test", token, None)
                        if token in ("platform_admin", "tenant_admin", "auditor") else None)
    monkeypatch.setattr(server, "verifier", lambda name: "")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_port}/v1/admin/system/calling-readiness"

    def request(token="", query=""):
        req = Request(base + query, headers={"Authorization": "Bearer " + token})
        try:
            response = urlopen(req, timeout=3)
        except HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    try:
        for role in ("", "tenant_admin", "auditor"):
            assert request(role)[0] == 403
        assert request("platform_admin")[0] == 200
        assert request("platform_admin", "?expected=/etc/passwd")[0] == 400
        monkeypatch.delenv("CALLING_OBSERVED_EVIDENCE_FILE")
        status, body = request("platform_admin")
        assert status == 503
        assert body["production_activation_authorized"] is False
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=3)
