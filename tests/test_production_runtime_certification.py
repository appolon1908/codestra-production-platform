#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "validate_production_runtime_certification.py"
SPEC = importlib.util.spec_from_file_location("runtime_certification", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class RuntimeCertificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.template = json.loads(
            (ROOT / "config" / "production-runtime-certification.template.v1.json").read_text(encoding="utf-8")
        )

    def complete_workload(self, index: int = 0) -> dict[str, object]:
        return {
            "name": f"workload-{index}",
            "repository": "owner/repository",
            "source_sha": "1" * 40,
            "image_digest": "sha256:" + "2" * 64,
            "runtime_source_sha": "1" * 40,
            "runtime_image_digest": "sha256:" + "2" * 64,
            "configuration_checksum": "3" * 64,
            "signature": "PASS",
            "sbom": "PASS",
            "provenance": "PASS",
            "vulnerability_gate": "PASS",
            "health": "PASS",
            "readiness": "PASS",
            "identity": "PASS",
            "restart_count": 0,
            "source_runtime_drift": 0,
            "prometheus_target_required": True,
            "prometheus_target": "PASS",
            "rollback": {
                "source_sha": "4" * 40,
                "image_digest": "sha256:" + "5" * 64,
            },
        }

    def complete_api(self, index: int = 0) -> dict[str, object]:
        return {
            "application": f"application-{index}",
            "source_sha": "1" * 40,
            "image_digest": "sha256:" + "2" * 64,
            "health": "PASS",
            "readiness": "PASS",
            "version": "PASS",
            "capabilities": "PASS",
            "openapi_source_runtime_alignment": "PASS",
            "gateway_application_alignment": "PASS",
            "runtime_attribution": "PASS",
            "authentication_required": "PASS",
            "wrong_role_denied": "PASS",
            "wrong_business_denied": "PASS",
            "write_methods_denied": "PASS",
            "tls_verified": "PASS",
            "unexpected_404": 0,
            "unexpected_5xx": 0,
        }

    def complete_route(self, index: int = 0) -> dict[str, object]:
        return {
            "name": f"route-{index}",
            "method": "GET" if index % 2 == 0 else "HEAD",
            "http_status": 200,
            "status": "PASS",
            "source_sha": "1" * 40,
        }

    def complete_document(self) -> dict[str, object]:
        document = {
            "schema_version": 1,
            "template": False,
            "status": "PASS",
            "candidate_id": "candidate-20260903",
            "source_lock_sha256": "a" * 64,
            "candidate_matrix_sha256": "b" * 64,
            "staging_host": {
                "status": "PASS",
                "workflow_run_id": "12345",
                "workflow_source_sha": "1" * 40,
                "provider_resource_id": "provider-123",
                "private_ip": "10.40.0.50",
                "ssh_host_key_fingerprint": "SHA256:fixture",
                "configuration_checksum": "c" * 64,
            },
            "artifacts": {
                "status": "PASS",
                "all_exact_digest": True,
                "all_signed": True,
                "all_sbom_verified": True,
                "all_provenance_verified": True,
                "all_vulnerability_gates_pass": True,
            },
            "workloads": [self.complete_workload(index) for index in range(64)],
            "business_apis": [self.complete_api(index) for index in range(15)],
            "gateway": {
                "expected_route_count": 29,
                "routes": [self.complete_route(index) for index in range(29)],
            },
            "staging": {
                "status": "PASS",
                "candidate_unchanged": True,
                "cross_business_denial": "PASS",
                "secrets_in_logs": 0,
                "high_cardinality_sensitive_labels": 0,
                "unhealthy_containers": 0,
                "restarting_containers": 0,
                "down_prometheus_targets": 0,
                "actionable_alerts": 0,
                "failed_systemd_units": 0,
            },
            "backup_restore": {
                "status": "PASS",
                "database_backup": "PASS",
                "off_host_copy": "PASS",
                "odoo_filestore_backup": "PASS",
                "configuration_backup": "PASS",
                "openbao_snapshot": "PASS",
                "isolated_restore": "PASS",
                "data_integrity": "PASS",
                "rto_seconds": 120,
                "rpo_seconds": 0,
                "residual_resources": 0,
            },
            "rollback": {
                "status": "PASS",
                "previous_candidate_id": "candidate-previous",
                "source_and_digest_verified": True,
                "health_readback": "PASS",
                "readiness_readback": "PASS",
                "version_readback": "PASS",
                "data_integrity": "PASS",
                "rto_seconds": 180,
            },
            "production_canary": {
                "status": "PASS",
                "traffic_percent": 1,
                "allowed_methods": ["GET", "HEAD"],
                "observed_write_requests": 0,
                "source_mismatch": 0,
                "digest_mismatch": 0,
                "unexpected_404": 0,
                "unexpected_5xx": 0,
                "cross_business_leaks": 0,
                "call_delta": 0,
                "email_delta": 0,
                "sms_delta": 0,
                "provider_effect_delta": 0,
                "automatic_rollback_ready": True,
            },
            "soak": {
                "status": "PASS",
                "duration_seconds": 7200,
                "minimum_duration_seconds": 3600,
                "unhealthy_containers": 0,
                "restarting_containers": 0,
                "down_prometheus_targets": 0,
                "actionable_alerts": 0,
                "failed_systemd_units": 0,
                "disk_headroom_pass": True,
                "wal_backlog_bounded": True,
                "source_runtime_drift": 0,
            },
            "safety": {key: False for key in self.template["safety"]},
            "production_certified": True,
        }
        return document

    def test_repository_template_is_valid_and_fail_closed(self) -> None:
        self.assertEqual(MODULE.validate_template(self.template), [])

    def test_complete_synthetic_evidence_passes(self) -> None:
        self.assertEqual(MODULE.validate_complete(self.complete_document()), [])

    def test_canary_above_one_percent_fails(self) -> None:
        document = self.complete_document()
        document["production_canary"]["traffic_percent"] = 1.01  # type: ignore[index]
        blockers = MODULE.validate_complete(document)
        self.assertTrue(any("no more than 1 percent" in item for item in blockers))

    def test_write_request_and_external_effect_fail(self) -> None:
        document = self.complete_document()
        document["production_canary"]["observed_write_requests"] = 1  # type: ignore[index]
        document["production_canary"]["email_delta"] = 1  # type: ignore[index]
        blockers = MODULE.validate_complete(document)
        self.assertTrue(any("observed_write_requests" in item for item in blockers))
        self.assertTrue(any("email_delta" in item for item in blockers))

    def test_runtime_identity_mismatch_fails(self) -> None:
        document = self.complete_document()
        document["workloads"][0]["runtime_source_sha"] = "9" * 40  # type: ignore[index]
        blockers = MODULE.validate_complete(document)
        self.assertTrue(any("runtime source differs" in item for item in blockers))

    def test_gateway_404_fails(self) -> None:
        document = self.complete_document()
        document["gateway"]["routes"][0]["http_status"] = 404  # type: ignore[index]
        blockers = MODULE.validate_complete(document)
        self.assertTrue(any("404/5xx" in item for item in blockers))

    def test_production_certified_cannot_hide_blockers(self) -> None:
        document = self.complete_document()
        document["business_apis"] = []
        blockers = MODULE.validate_complete(document)
        self.assertTrue(any("exactly 15" in item for item in blockers))
        self.assertTrue(any("production_certified" in item for item in blockers))


if __name__ == "__main__":
    unittest.main()
