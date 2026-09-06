from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "verify_production_certification_evidence.py"
spec = importlib.util.spec_from_file_location("production_evidence", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class ProductionEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.policy = {
            "schema_version": 1,
            "runtime_matrix": {
                "expected_workloads": 2,
                "deployment_authorized_required": True,
            },
            "source_lock": {"required_status": "PASS"},
            "forbidden_evidence_values": [
                "UNKNOWN", "PENDING", "NOT_STARTED", "NOT_RUN", "NONE",
                "TBD", "TODO", "REPLACE_ME", "UNRESOLVED", "UNVERIFIED"
            ],
        }
        self.policy_path = self.root / "policy.json"
        self.policy_path.write_text(json.dumps(self.policy), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_yaml(self, name: str, value: object) -> Path:
        path = self.root / name
        path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
        return path

    def good_lock(self) -> dict:
        return {
            "status": "PASS",
            "components": [
                {
                    "repository": "example/alpha",
                    "branch": "production",
                    "source_sha": "a" * 40,
                },
                {
                    "repository": "example/beta",
                    "branch": "production",
                    "source_sha": "b" * 40,
                },
            ],
        }

    def good_matrix(self) -> dict:
        return {
            "deployment_authorized": True,
            "workloads": [
                {
                    "workload_id": "alpha-api",
                    "repository": "example/alpha",
                    "source_sha": "a" * 40,
                    "image": "ghcr.io/example/alpha@sha256:" + "1" * 64,
                    "image_digest": "sha256:" + "1" * 64,
                    "signature": "oci://ghcr.io/example/alpha-signature@sha256:" + "2" * 64,
                    "sbom": "oci://ghcr.io/example/alpha-sbom@sha256:" + "3" * 64,
                    "provenance": "oci://ghcr.io/example/alpha-provenance@sha256:" + "4" * 64,
                    "rollback_digest": "sha256:" + "5" * 64,
                },
                {
                    "workload_id": "beta-worker",
                    "repository": "example/beta",
                    "source_sha": "b" * 40,
                    "image": "ghcr.io/example/beta@sha256:" + "6" * 64,
                    "image_digest": "sha256:" + "6" * 64,
                    "signature": "oci://ghcr.io/example/beta-signature@sha256:" + "7" * 64,
                    "sbom": "oci://ghcr.io/example/beta-sbom@sha256:" + "8" * 64,
                    "provenance": "oci://ghcr.io/example/beta-provenance@sha256:" + "9" * 64,
                    "rollback_digest": "sha256:" + "0" * 64,
                },
            ],
        }

    def verify(self, lock: dict, matrix: dict):
        return module.verify(
            self.write_yaml("lock.yaml", lock),
            self.write_yaml("matrix.yaml", matrix),
            self.policy_path,
            verify_github=False,
            require_pass=True,
        )

    def test_complete_evidence_passes(self) -> None:
        report = self.verify(self.good_lock(), self.good_matrix())
        self.assertEqual(report.status, "PASS")
        self.assertEqual(report.findings, [])
        self.assertEqual(len(report.workload_evidence), 2)

    def test_source_lock_fail_status_blocks(self) -> None:
        lock = self.good_lock()
        lock["status"] = "FAIL"
        report = self.verify(lock, self.good_matrix())
        self.assertEqual(report.status, "BLOCKED")
        self.assertIn("SOURCE_LOCK_NOT_PASS", {item.code for item in report.findings})

    def test_unknown_source_sha_blocks(self) -> None:
        lock = self.good_lock()
        lock["components"][0]["source_sha"] = "UNKNOWN"
        report = self.verify(lock, self.good_matrix())
        codes = {item.code for item in report.findings}
        self.assertIn("UNRESOLVED_VALUE", codes)
        self.assertIn("INVALID_SOURCE_SHA", codes)

    def test_mutable_latest_image_blocks(self) -> None:
        matrix = self.good_matrix()
        matrix["workloads"][0]["image"] = "ghcr.io/example/alpha:latest"
        report = self.verify(self.good_lock(), matrix)
        codes = {item.code for item in report.findings}
        self.assertIn("MUTABLE_IMAGE_REFERENCE", codes)
        self.assertIn("WORKLOAD_IMAGE_MUTABLE", codes)

    def test_workload_count_mismatch_blocks(self) -> None:
        matrix = self.good_matrix()
        matrix["workloads"].pop()
        report = self.verify(self.good_lock(), matrix)
        self.assertIn("WORKLOAD_COUNT_MISMATCH", {item.code for item in report.findings})

    def test_missing_supply_chain_evidence_blocks(self) -> None:
        matrix = self.good_matrix()
        matrix["workloads"][0]["signature"] = "PENDING"
        matrix["workloads"][0]["sbom"] = None
        matrix["workloads"][0]["provenance"] = "UNVERIFIED"
        report = self.verify(self.good_lock(), matrix)
        codes = {item.code for item in report.findings}
        self.assertIn("WORKLOAD_SIGNATURE_MISSING", codes)
        self.assertIn("WORKLOAD_SBOM_MISSING", codes)
        self.assertIn("WORKLOAD_PROVENANCE_MISSING", codes)

    def test_deployment_authorization_must_be_true(self) -> None:
        matrix = self.good_matrix()
        matrix["deployment_authorized"] = False
        report = self.verify(self.good_lock(), matrix)
        self.assertIn("MATRIX_NOT_AUTHORIZED", {item.code for item in report.findings})

    def test_rollback_digest_must_be_exact(self) -> None:
        matrix = self.good_matrix()
        matrix["workloads"][0]["rollback_digest"] = "NONE"
        report = self.verify(self.good_lock(), matrix)
        self.assertIn("WORKLOAD_ROLLBACK_INVALID", {item.code for item in report.findings})


if __name__ == "__main__":
    unittest.main()
