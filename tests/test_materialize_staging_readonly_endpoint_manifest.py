from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "materialize_staging_readonly_endpoint_manifest.py"
spec = importlib.util.spec_from_file_location("staging_manifest", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class StagingManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.policy = {
            "schema_version": 1,
            "runtime_matrix": {
                "repository": "example/runtime",
                "branch": "main",
                "path": "IMMUTABLE-CANDIDATE-MATRIX.yaml",
                "expected_workloads": 64,
                "deployment_authorized_required": True,
            },
            "source_lock": {"path": "lock.yaml", "required_status": "PASS"},
            "forbidden_evidence_values": [
                "UNKNOWN", "PENDING", "NOT_STARTED", "NOT_RUN", "NONE",
                "TBD", "TODO", "REPLACE_ME", "UNRESOLVED", "UNVERIFIED"
            ],
        }
        self.policy_path = self.root / "policy.json"
        self.policy_path.write_text(json.dumps(self.policy), encoding="utf-8")
        self.source_lock_path = self.root / "source-lock.yaml"
        self.matrix_path = self.root / "matrix.yaml"
        self.catalog_path = self.root / "catalog.json"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_inputs(self, source_lock=None, matrix=None, catalog=None) -> None:
        self.source_lock_path.write_text(
            yaml.safe_dump(source_lock or self.source_lock(), sort_keys=False),
            encoding="utf-8",
        )
        self.matrix_path.write_text(
            yaml.safe_dump(matrix or self.matrix(), sort_keys=False),
            encoding="utf-8",
        )
        self.catalog_path.write_text(
            json.dumps(catalog or self.catalog(), indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def source_lock() -> dict:
        return {
            "status": "PASS",
            "components": [
                {
                    "repository": "example/platform",
                    "branch": "production",
                    "source_sha": "a" * 40,
                }
            ],
        }

    @staticmethod
    def workload(index: int) -> dict:
        marker = f"{index % 16:x}"
        digest = "sha256:" + marker * 64
        rollback_marker = f"{(index + 1) % 16:x}"
        return {
            "workload_id": f"workload-{index:02d}",
            "repository": f"example/workload-{index:02d}",
            "source_sha": marker * 40,
            "image": f"ghcr.io/example/workload-{index:02d}@{digest}",
            "image_digest": digest,
            "signature": f"oci://signature/workload-{index:02d}/{marker * 16}",
            "sbom": f"oci://sbom/workload-{index:02d}/{marker * 16}",
            "provenance": f"oci://provenance/workload-{index:02d}/{marker * 16}",
            "rollback_digest": "sha256:" + rollback_marker * 64,
        }

    def matrix(self) -> dict:
        return {
            "deployment_authorized": True,
            "workloads": [self.workload(index) for index in range(64)],
        }

    @staticmethod
    def endpoint(path: str, authentication: str = "bearer") -> dict:
        return {
            "method": "GET",
            "path": path,
            "expected_statuses": [200, 401, 403],
            "authentication": authentication,
            "write_effect_allowed": False,
        }

    def business_api(self, index: int) -> dict:
        application = f"business-{index:02d}"
        marker = f"{index % 16:x}"
        return {
            "application": application,
            "repository": f"example/{application}",
            "source_sha": marker * 40,
            "image_digest": "sha256:" + marker * 64,
            "base_url": f"https://{application}.staging.example.invalid",
            "health": self.endpoint("/health", "public-health"),
            "readiness": self.endpoint("/ready"),
            "version": self.endpoint("/version"),
            "capabilities": self.endpoint("/capabilities"),
            "openapi": self.endpoint("/openapi.json"),
            "runtime_attribution": {
                "source_sha_field": "source_sha",
                "image_digest_field": "image_digest",
            },
        }

    def route(self, index: int) -> dict:
        return {
            "name": f"business-route-{index:02d}",
            "application": f"business-{index % 15:02d}",
            "method": "GET" if index % 2 == 0 else "HEAD",
            "path": f"/api/read-only/{index:02d}",
            "expected_statuses": [200, 401, 403],
            "write_effect_allowed": False,
        }

    def catalog(self) -> dict:
        safety_names = {
            "LIVE_WRITE", "ODOO_WRITE", "ENABLE_EXTERNAL_DELIVERY",
            "N8N_DELIVERY_ENABLED", "LIVE_EMAIL_DELIVERY",
            "LIVE_SMS_DELIVERY", "LIVE_PSTN_DIALING", "PRODUCTION_DIALING",
            "CAMPAIGN_ACTIVATION", "PROVIDER_DELIVERY",
            "ADVERTISING_ACTIVATION", "PAYMENT_EXECUTION", "FINANCIAL_TRADING"
        }
        return {
            "schema_version": 1,
            "previous_candidate": {
                "release_id": "previous-release-001",
                "components": [
                    {"workload": "workload-00", "image_digest": "sha256:" + "f" * 64}
                ],
            },
            "identity": {
                "issuer": "https://auth.staging.example.invalid/realms/codestra",
                "discovery_path": "/.well-known/openid-configuration",
                "expected_http_status": 200,
            },
            "business_apis": [self.business_api(index) for index in range(15)],
            "kong": {
                "base_url": "https://api.staging.example.invalid",
                "route_count": 29,
                "routes": [self.route(index) for index in range(29)],
            },
            "database": {
                "migration_evidence_endpoint": "https://database-evidence.staging.example.invalid/read-only",
                "expected_heads": ["20260903_001"],
            },
            "counters": {
                name: {"baseline": 0, "maximum_delta": 0}
                for name in ("calls", "emails", "sms", "provider_effects")
            },
            "backups": {
                "database_required": True,
                "odoo_filestore_required": True,
                "configuration_required": True,
                "off_host_copy_required": True,
                "off_host_uri": "env:CODESTRA_STAGING_OFF_HOST_BACKUP_URI",
                "credential_ref": "CODESTRA_STAGING_OFF_HOST_BACKUP_CREDENTIAL",
            },
            "rollback": {
                "rto_seconds_limit": 1800,
                "rpo_seconds_limit": 86400,
                "health_readback_required": True,
                "readiness_readback_required": True,
                "version_readback_required": True,
                "data_integrity_required": True,
            },
            "safety_controls": {name: False for name in safety_names},
        }

    def build(self, *, source_lock=None, matrix=None, catalog=None):
        self.write_inputs(source_lock, matrix, catalog)
        return module.build_manifest(
            self.source_lock_path,
            self.matrix_path,
            self.policy_path,
            self.catalog_path,
            "candidate-release-001",
            "c" * 40,
        )

    def test_complete_authorities_materialize_deterministically(self) -> None:
        first = self.build()
        second = self.build()
        self.assertEqual(first, second)
        self.assertEqual(len(first["candidate"]["components"]), 64)
        self.assertEqual(len(first["business_apis"]), 15)
        self.assertEqual(len(first["kong"]["routes"]), 29)
        self.assertEqual(first["canary"]["allowed_methods"], ["GET", "HEAD"])
        self.assertTrue(all(value is False for value in first["safety_controls"].values()))

    def test_blocked_source_lock_cannot_materialize(self) -> None:
        source_lock = self.source_lock()
        source_lock["status"] = "FAIL"
        with self.assertRaisesRegex(module.ManifestError, "source lock or immutable matrix"):
            self.build(source_lock=source_lock)

    def test_unauthorized_matrix_cannot_materialize(self) -> None:
        matrix = self.matrix()
        matrix["deployment_authorized"] = False
        with self.assertRaisesRegex(module.ManifestError, "source lock or immutable matrix"):
            self.build(matrix=matrix)

    def test_exactly_fifteen_business_apis_are_required(self) -> None:
        catalog = self.catalog()
        catalog["business_apis"].pop()
        with self.assertRaisesRegex(module.ManifestError, "exactly 15"):
            self.build(catalog=catalog)

    def test_exactly_twenty_nine_routes_are_required(self) -> None:
        catalog = self.catalog()
        catalog["kong"]["routes"].pop()
        with self.assertRaisesRegex(module.ManifestError, "exactly 29"):
            self.build(catalog=catalog)

    def test_404_cannot_be_an_expected_route_result(self) -> None:
        catalog = self.catalog()
        catalog["kong"]["routes"][0]["expected_statuses"] = [404]
        with self.assertRaisesRegex(module.ManifestError, "unsafe status"):
            self.build(catalog=catalog)

    def test_write_method_cannot_enter_route_catalog(self) -> None:
        catalog = self.catalog()
        catalog["kong"]["routes"][0]["method"] = "POST"
        with self.assertRaisesRegex(module.ManifestError, "GET or HEAD"):
            self.build(catalog=catalog)

    def test_embedded_url_credentials_are_rejected(self) -> None:
        catalog = self.catalog()
        catalog["business_apis"][0]["base_url"] = "https://user:password@business.invalid"
        with self.assertRaisesRegex(module.ManifestError, "credential-free HTTPS"):
            self.build(catalog=catalog)

    def test_live_effect_counter_delta_must_be_zero(self) -> None:
        catalog = self.catalog()
        catalog["counters"]["emails"]["maximum_delta"] = 1
        with self.assertRaisesRegex(module.ManifestError, "maximum_delta must be zero"):
            self.build(catalog=catalog)

    def test_safety_control_cannot_be_enabled(self) -> None:
        catalog = self.catalog()
        catalog["safety_controls"]["LIVE_WRITE"] = True
        with self.assertRaisesRegex(module.ManifestError, "must remain false"):
            self.build(catalog=catalog)

    def test_previous_release_must_differ(self) -> None:
        catalog = self.catalog()
        catalog["previous_candidate"]["release_id"] = "candidate-release-001"
        with self.assertRaisesRegex(module.ManifestError, "may not equal"):
            self.build(catalog=catalog)


if __name__ == "__main__":
    unittest.main()
