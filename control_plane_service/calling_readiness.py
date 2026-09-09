"""Read-only evaluation of operator-mounted calling release/read-back evidence.

This compares assertions collected by the deployment authority. It does not
authenticate artifacts, collect live state, authorize deployment, or dial calls.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path


AUTHORITIES = {
    "middleware": "Middleware-", "vicidial": "Vicidialer-Codestra",
    "websocket": "Websocket-", "odoo": "Odoo", "caddy": "Caddy",
    "kong": "Kong", "keycloak": "Keycloak", "sdk": "SDK-repository",
    "infrastructure": "Infustruction-repo", "n8n": "N8N",
    "operator_ui": "Codestra-Communication-CC",
    "platform": "codestra-production-platform",
}
FLAGS = (
    "VICIDIAL_WRITES", "LIVE_CALL_CONTROL", "PRODUCTION_DIALING",
    "LIVE_PSTN_DIALING", "TELEPHONY_ADMIN_WRITE",
    "ENABLE_VICIDIAL_WRITES", "ENABLE_CAMPAIGN_SYNC", "ENABLE_AGENT_SYNC",
    "ENABLE_LEAD_PUBLICATION", "ENABLE_LIVE_CALL_CONTROL", "ENABLE_WARM_TRANSFER",
    "ENABLE_IVR_ROUTING", "ENABLE_IVR_CALLBACKS", "ENABLE_APPT_PREP",
    "ENABLE_PROVISIONING", "ENABLE_PRODUCTION_DIALING",
    "ENABLE_EMAIL_DELIVERY", "ENABLE_SMS_DELIVERY", "ENABLE_AI_ACTIONS",
    "SEND_EVENTS", "ENABLE_EXTERNAL_DELIVERY", "LIVE_WRITE", "ODOO_WRITE",
    "N8N_DELIVERY_ENABLED", "GENERAL_AI_DIALING", "CALLBACK_DISPATCH",
)
PROOFS = ("backup", "restore", "rollback", "monitoring", "identity", "route_policy")
SHA = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
MAX_BYTES = 1024 * 1024
MAX_AGE_SECONDS = 300


def _object(value):
    return value if isinstance(value, dict) else {}


def _timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result if result.utcoffset() is not None else None
    except ValueError:
        return None


def _matches(pattern, value):
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _result(blockers):
    return {
        "schema_version": "calling-readiness.v1",
        "status": "BLOCKED" if blockers else "READBACK_MATCHES",
        "production_activation_authorized": False,
        "live_state_collected": False,
        "blockers": blockers,
    }


def release_digest(expected):
    """Bind proof references to all fields of the expected release manifest."""
    payload = {key: value for key, value in expected.items() if key != "release_digest"}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def evaluate(expected, observed, *, now=None):
    """Fail closed on absent, malformed, stale, unsafe, or mismatching evidence."""
    now = now or datetime.now(timezone.utc)
    expected, observed = _object(expected), _object(observed)
    blockers = []

    def check(condition, code, component="ecosystem"):
        if not condition:
            blockers.append({"component": component, "code": code})

    for label, document in (("expected", expected), ("observed", observed)):
        check(document.get("schema_version") == "calling-evidence.v1", "INVALID_SCHEMA", label)
    environment = expected.get("environment")
    check(environment in ("staging-readonly", "production-readonly"), "INVALID_ENVIRONMENT")
    check(observed.get("environment") == environment, "ENVIRONMENT_MISMATCH")
    contract = expected.get("contract_digest")
    check(_matches(DIGEST, contract), "INVALID_CONTRACT_DIGEST")
    check(observed.get("contract_digest") == contract, "CONTRACT_MISMATCH")
    captured = _timestamp(observed.get("captured_at"))
    check(captured is not None and 0 <= (now - captured).total_seconds() <= MAX_AGE_SECONDS,
          "STALE_OR_INVALID_EVIDENCE")
    expected_components = _object(expected.get("components"))
    observed_components = _object(observed.get("components"))
    check(set(expected_components) == set(AUTHORITIES), "EXPECTED_COMPONENT_SET_MISMATCH")
    check(set(observed_components) == set(AUTHORITIES), "OBSERVED_COMPONENT_SET_MISMATCH")
    for name, repository in AUTHORITIES.items():
        want = _object(expected_components.get(name))
        actual = _object(observed_components.get(name))
        check(bool(want) and bool(actual), "MISSING_COMPONENT", name)
        check(want.get("repository") == "appolon1908-hue/" + repository,
              "INVALID_REPOSITORY_AUTHORITY", name)
        check(type(want.get("repository_id")) is int and want["repository_id"] > 0,
              "INVALID_REPOSITORY_ID", name)
        check(_matches(SHA, want.get("source_sha")), "INVALID_SOURCE_SHA", name)
        for field in ("artifact_digest", "configuration_digest", "rollback_digest"):
            check(_matches(DIGEST, want.get(field)), "INVALID_" + field.upper(), name)
        for field in ("protected_branch", "migration_head", "runtime_identity"):
            check(isinstance(want.get(field), str) and bool(want[field].strip())
                  and want[field] not in ("unknown", "pending"), "INVALID_" + field.upper(), name)
        for field in ("repository", "repository_id", "protected_branch", "source_sha",
                      "artifact_digest", "configuration_digest", "migration_head",
                      "runtime_identity", "rollback_digest"):
            check(type(actual.get(field)) is type(want.get(field))
                  and actual.get(field) == want.get(field), field.upper() + "_MISMATCH", name)
        check(actual.get("contract_digest") == contract, "CONTRACT_MISMATCH", name)
        component_time = _timestamp(actual.get("captured_at"))
        check(component_time is not None and captured is not None
              and 0 <= (now - component_time).total_seconds() <= MAX_AGE_SECONDS
              and component_time <= captured, "STALE_OR_INVALID_EVIDENCE", name)
        for field in ("healthy", "ready", "signature_verified", "provenance_verified", "protected_merge_verified"):
            check(actual.get(field) is True, field.upper() + "_NOT_PROVEN", name)

    safety = _object(observed.get("safety"))
    for flag in FLAGS:
        check(safety.get(flag) is False, "EFFECT_NOT_DISABLED:" + flag)
    for counter in ("calls_placed_before", "calls_placed_after", "unexpected_writes"):
        check(type(safety.get(counter)) is int and safety[counter] == 0,
              "NONZERO_OR_UNKNOWN:" + counter)
    check(safety.get("middleware_authority_count") == 1
          and type(safety.get("middleware_authority_count")) is int,
          "MIDDLEWARE_AUTHORITY_NOT_UNIQUE")
    for field in ("asterisk_ready", "ami_ready", "trunk_ready", "mtls_identity_verified",
                  "callback_signature_verified", "callback_replay_protection_verified"):
        check(safety.get(field) is True, field.upper() + "_NOT_PROVEN", "vicidial")
    for field in ("event_lag_seconds", "reconciliation_depth"):
        check(type(safety.get(field)) is int and safety[field] == 0,
              "NONZERO_OR_UNKNOWN:" + field)
    proofs = _object(observed.get("proofs"))
    for name in PROOFS:
        proof = _object(proofs.get(name))
        check(proof.get("passed") is True
              and proof.get("contract_digest") == contract
              and _matches(DIGEST, proof.get("evidence_digest"))
              and proof.get("release_digest") == expected.get("release_digest"),
              "MISSING_OR_MISMATCHING_PROOF", name)
    check(_matches(DIGEST, expected.get("release_digest")), "INVALID_RELEASE_DIGEST")
    try:
        bound_digest = release_digest(expected)
    except (ValueError, TypeError, RecursionError):
        bound_digest = None
    check(bound_digest is not None and expected.get("release_digest") == bound_digest,
          "RELEASE_DIGEST_NOT_BOUND_TO_MANIFEST")
    check(observed.get("release_digest") == expected.get("release_digest"), "RELEASE_MISMATCH")
    return _result(blockers)


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _read(path):
    if not path:
        raise ValueError("unconfigured evidence")
    with Path(path).open("rb") as handle:
        raw = handle.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("oversized evidence")
    value = json.loads(raw, object_pairs_hook=_unique_pairs)
    if not isinstance(value, dict):
        raise ValueError("invalid evidence")
    return value


def snapshot(expected_path=None, observed_path=None):
    documents, blockers = [], []
    for name, path in (
        ("expected", expected_path or os.getenv("CALLING_EXPECTED_EVIDENCE_FILE")),
        ("observed", observed_path or os.getenv("CALLING_OBSERVED_EVIDENCE_FILE")),
    ):
        try:
            documents.append(_read(path))
        except (OSError, ValueError, RecursionError):
            documents.append({})
            blockers.append({"component": name, "code": "EVIDENCE_UNAVAILABLE_OR_INVALID"})
    # Never reflect paths, file contents, exception messages, or submitted identities.
    return _result(blockers) if blockers else evaluate(*documents)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected", required=True)
    parser.add_argument("--observed", required=True)
    args = parser.parse_args()
    result = snapshot(args.expected, args.observed)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "READBACK_MATCHES" else 1


if __name__ == "__main__":
    raise SystemExit(main())
