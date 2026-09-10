"""Validate sanitized Server B observations; never collect state or enable calls.

The deployment authority supplies this evidence alongside calling-evidence.v1.
Matching assertions are not independent authentication or production certification.
"""
from __future__ import annotations

from datetime import datetime, timezone


HEALTH_UNITS = (
    "codestra-asterisk-health.service",
    "codestra-integration-health.service",
    "codestra-vicidial-restricted-adapter-health.service",
)
ZERO_COUNTERS = (
    "active_channels", "active_calls", "config_drift_count",
    "outbox_depth", "outbox_oldest_seconds", "retrying_events",
    "dead_letter_events", "quarantined_events", "corrupt_events", "event_gaps",
)
REQUIRED_CHECKS = (
    "asterisk_active", "adapter_active", "gateway_active",
    "ami_loopback_only", "database_loopback_only", "private_ingress_only",
    "mtls_verified", "time_synchronized", "delivery_worker_running",
    "callback_signature_verified", "callback_replay_protection_verified",
    "callback_restart_no_gap_verified", "cdr_readback_verified",
    "backup_verified", "isolated_restore_verified", "rollback_verified",
)


def evaluate(document, *, source_sha, artifact_digest, release_digest, now=None):
    """Return bounded reason codes, without reflecting any supplied values."""
    now = now or datetime.now(timezone.utc)
    if not isinstance(document, dict):
        return ["SERVER_B_EVIDENCE_MISSING"]
    blockers = []

    def check(condition, code):
        if not condition:
            blockers.append("SERVER_B_" + code)

    check(document.get("schema_version") == "server-b-readiness.v1", "INVALID_SCHEMA")
    captured = document.get("captured_at")
    try:
        captured = datetime.fromisoformat(captured.replace("Z", "+00:00"))
        fresh = captured.utcoffset() is not None and 0 <= (now - captured).total_seconds() <= 300
    except (AttributeError, TypeError, ValueError, OverflowError):
        fresh = False
    check(fresh, "STALE_OR_INVALID_EVIDENCE")
    for field, value in (
        ("public_ip", "65.21.67.207"), ("private_ip", "10.40.0.2"),
        ("source_sha", source_sha), ("artifact_digest", artifact_digest),
        ("release_digest", release_digest),
    ):
        check(isinstance(value, str) and document.get(field) == value,
              field.upper() + "_MISMATCH")
    check(document.get("deployment_profile") == "production-candidate",
          "READONLY_PROFILE_NOT_PROVEN")
    for name in REQUIRED_CHECKS:
        check(document.get(name) is True, name.upper() + "_NOT_PROVEN")
    for name in ZERO_COUNTERS:
        check(type(document.get(name)) is int and document[name] == 0,
              name.upper() + "_NONZERO_OR_UNKNOWN")

    units = document.get("health_units")
    units = units if isinstance(units, dict) else {}
    for name in HEALTH_UNITS:
        unit = units.get(name)
        unit = unit if isinstance(unit, dict) else {}
        # Completed oneshot probes normally show inactive/dead. A reset-failed
        # unit without a recent successful execution must not satisfy this gate.
        check(unit.get("result") == "success"
              and type(unit.get("exit_status")) is int and unit["exit_status"] == 0
              and type(unit.get("last_success_age_seconds")) is int
              and 0 <= unit["last_success_age_seconds"] <= 300,
              "HEALTH_UNIT_NOT_PROVEN:" + name)

    counters = document.get("call_counters")
    counters = counters if isinstance(counters, dict) else {}
    check(counters.get("authority") == "durable-cdr-and-call-ledger",
          "CALL_COUNTER_AUTHORITY_NOT_PROVEN")
    # Process-lifetime `core show channels count` is insufficient: a restart
    # resets it. Both durable observations must cover the same verification run.
    check(counters.get("same_observation_window") is True,
          "CALL_COUNTER_WINDOW_NOT_PROVEN")
    for name in ("calls_placed_before", "calls_placed_after"):
        check(type(counters.get(name)) is int and counters[name] == 0,
              name.upper() + "_NONZERO_OR_UNKNOWN")
    return blockers
