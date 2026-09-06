from __future__ import annotations

import copy
import importlib.util
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "validate_production_recovery_canary.py"
spec = importlib.util.spec_from_file_location("recovery_canary", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


AUTHORITIES = [
    "platform-postgresql",
    "provisioning-sqlite",
    "odoo-postgresql",
    "odoo-filestore",
    "openbao-raft",
    "grafana-metadata",
    "superset-metadata",
    "prometheus-tsdb",
    "loki-storage",
    "tempo-storage",
    "configuration-bundle",
]


def timestamp(offset_seconds: int) -> str:
    base = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)
    return (base + timedelta(seconds=offset_seconds)).isoformat().replace("+00:00", "Z")


def recovery(authority: str, index: int) -> dict:
    marker = f"{index % 16:x}"
    previous = f"{(index + 1) % 16:x}"
    artifact = f"{(index + 2) % 16:x}" * 64
    candidate = "sha256:" + marker * 64
    return {
        "authority": authority,
        "source_sha": marker * 40,
        "image_digest": candidate,
        "backup": {
            "status": "PASS",
            "generation": f"backup-generation-{index:02d}",
            "started_at": timestamp(index * 1000),
            "completed_at": timestamp(index * 1000 + 30),
            "artifact_sha256": artifact,
            "encrypted": True,
            "checksum_verified": True,
            "source_identity_recorded": True,
            "image_identity_recorded": True,
            "off_host": {
                "status": "PASS",
                "uri_ref": "env:CODESTRA_STAGING_OFF_HOST_BACKUP_URI",
                "sha256": artifact,
            },
            "evidence_ref": f"evidence:backup/{authority}/{index:02d}",
        },
        "restore": {
            "status": "PASS",
            "isolated": True,
            "generation": f"backup-generation-{index:02d}",
            "started_at": timestamp(index * 1000 + 60),
            "completed_at": timestamp(index * 1000 + 120),
            "rto_seconds": 60,
            "rto_limit_seconds": 1800,
            "rpo_seconds": 120,
            "rpo_limit_seconds": 86400,
            "integrity": "PASS",
            "residual_resources": 0,
            "health_readback": "PASS",
            "readiness_readback": "PASS",
            "version_readback": "PASS",
            "evidence_ref": f"evidence:restore/{authority}/{index:02d}",
        },
        "rollback": {
            "status": "PASS",
            "rehearsed": True,
            "candidate_digest": candidate,
            "previous_digest": "sha256:" + previous * 64,
            "started_at": timestamp(index * 1000 + 180),
            "completed_at": timestamp(index * 1000 + 240),
            "duration_seconds": 60,
            "duration_limit_seconds": 1800,
            "data_integrity": "PASS",
            "source_readback": "PASS",
            "digest_readback": "PASS",
            "monitoring_continuity": "PASS",
            "evidence_ref": f"evidence:rollback/{authority}/{index:02d}",
        },
    }


def policy() -> dict:
    return {
        "schema_version": 1,
        "required_recovery_authorities": AUTHORITIES,
        "canary": {
            "maximum_traffic_percent": 1,
            "allowed_methods": ["GET", "HEAD"],
        },
        "soak": {
            "minimum_duration_seconds": 3600,
            "maximum_unhealthy_containers": 0,
            "maximum_restarting_containers": 0,
            "maximum_down_prometheus_targets": 0,
            "maximum_actionable_alerts": 0,
            "maximum_failed_systemd_units": 0,
            "maximum_source_runtime_drift": 0,
            "maximum_cross_business_leaks": 0,
            "maximum_secrets_in_logs": 0,
        },
    }


def evidence() -> dict:
    return {
        "schema_version": 1,
        "candidate": {
            "release_id": "codestra-candidate-20260903",
            "platform_source_sha": "a" * 40,
            "endpoint_manifest_sha256": "b" * 64,
        },
        "recovery": [recovery(authority, index) for index, authority in enumerate(AUTHORITIES)],
        "canary": {
            "status": "PASS",
            "started_at": timestamp(20000),
            "completed_at": timestamp(21800),
            "traffic_percent": 1,
            "methods_observed": ["GET", "HEAD"],
            "source_match": True,
            "digest_match": True,
            "unexpected_404": 0,
            "unexpected_5xx": 0,
            "calls_delta": 0,
            "emails_delta": 0,
            "sms_delta": 0,
            "provider_effects_delta": 0,
            "business_writes_delta": 0,
            "cross_business_leaks": 0,
            "secrets_in_logs": 0,
            "monitoring_continuity": "PASS",
            "automatic_rollback_ready": True,
            "evidence_ref": "evidence:canary/20260903",
        },
        "soak": {
            "status": "PASS",
            "started_at": timestamp(22000),
            "completed_at": timestamp(25600),
            "unhealthy_containers": 0,
            "restarting_containers": 0,
            "down_prometheus_targets": 0,
            "actionable_alerts": 0,
            "failed_systemd_units": 0,
            "source_runtime_drift": 0,
            "cross_business_leaks": 0,
            "secrets_in_logs": 0,
            "evidence_ref": "evidence:soak/20260903",
        },
        "safety": {
            "business_writes": False,
            "communications_delivery": False,
            "provider_effects": False,
            "financial_or_trading_mutation": False,
        },
    }


class RecoveryCanaryTests(unittest.TestCase):
    def test_complete_evidence_passes(self) -> None:
        result = module.validate(evidence(), policy())
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(len(result["recovery_authorities"]), 11)
        self.assertEqual(result["canary"]["traffic_percent"], 1)
        self.assertEqual(result["soak"]["duration_seconds"], 3600)

    def test_every_recovery_authority_is_required(self) -> None:
        value = evidence()
        value["recovery"].pop()
        with self.assertRaisesRegex(module.EvidenceError, "count does not match"):
            module.validate(value, policy())

    def test_off_host_checksum_must_match(self) -> None:
        value = evidence()
        value["recovery"][0]["backup"]["off_host"]["sha256"] = "f" * 64
        with self.assertRaisesRegex(module.EvidenceError, "off-host checksum"):
            module.validate(value, policy())

    def test_restore_must_be_isolated(self) -> None:
        value = evidence()
        value["recovery"][0]["restore"]["isolated"] = False
        with self.assertRaisesRegex(module.EvidenceError, "isolated must be true"):
            module.validate(value, policy())

    def test_restore_rto_must_fit_limit(self) -> None:
        value = evidence()
        value["recovery"][0]["restore"]["rto_seconds"] = 1801
        with self.assertRaisesRegex(module.EvidenceError, "RTO exceeds"):
            module.validate(value, policy())

    def test_restore_residual_resources_must_be_zero(self) -> None:
        value = evidence()
        value["recovery"][0]["restore"]["residual_resources"] = 1
        with self.assertRaisesRegex(module.EvidenceError, "must be zero"):
            module.validate(value, policy())

    def test_rollback_must_not_be_noop(self) -> None:
        value = evidence()
        value["recovery"][0]["rollback"]["previous_digest"] = value["recovery"][0]["image_digest"]
        with self.assertRaisesRegex(module.EvidenceError, "no-op"):
            module.validate(value, policy())

    def test_canary_cannot_exceed_one_percent(self) -> None:
        value = evidence()
        value["canary"]["traffic_percent"] = 1.01
        with self.assertRaisesRegex(module.EvidenceError, "one-percent"):
            module.validate(value, policy())

    def test_canary_cannot_observe_write_method(self) -> None:
        value = evidence()
        value["canary"]["methods_observed"].append("POST")
        with self.assertRaisesRegex(module.EvidenceError, "GET/HEAD"):
            module.validate(value, policy())

    def test_canary_live_effect_delta_must_be_zero(self) -> None:
        value = evidence()
        value["canary"]["emails_delta"] = 1
        with self.assertRaisesRegex(module.EvidenceError, "emails_delta must be zero"):
            module.validate(value, policy())

    def test_soak_duration_must_meet_minimum(self) -> None:
        value = evidence()
        value["soak"]["completed_at"] = timestamp(25599)
        with self.assertRaisesRegex(module.EvidenceError, "below the policy minimum"):
            module.validate(value, policy())

    def test_soak_health_must_remain_zero(self) -> None:
        value = evidence()
        value["soak"]["down_prometheus_targets"] = 1
        with self.assertRaisesRegex(module.EvidenceError, "exceeds policy"):
            module.validate(value, policy())

    def test_secret_value_field_is_rejected(self) -> None:
        value = evidence()
        value["recovery"][0]["backup"]["password"] = "not-a-real-secret"
        with self.assertRaisesRegex(module.EvidenceError, "secret value field"):
            module.validate(value, policy())


if __name__ == "__main__":
    unittest.main()
