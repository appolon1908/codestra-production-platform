#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "reconcile_production_certification.py"
SPEC = importlib.util.spec_from_file_location("production_certification", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ProductionCertificationAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.forbidden = {
            "UNKNOWN",
            "PENDING",
            "NOT_STARTED",
            "NOT_RUN",
            "REPLACE_ME",
            "REPLACE_WITH_EXACT_VALUE",
            "TBD",
            "TODO",
        }

    def complete_workload(self) -> dict[str, object]:
        return {
            "name": "example",
            "repository": "owner/repository",
            "protected_source_sha": "1" * 40,
            "image": "ghcr.io/owner/example@sha256:" + "2" * 64,
            "signature_reference": "oci://ghcr.io/owner/example@sha256:" + "2" * 64,
            "sbom_reference": "artifact://sbom/example.spdx.json",
            "provenance_reference": "artifact://provenance/example.intoto.jsonl",
            "configuration_checksum": "3" * 64,
            "runtime_source_readback": "1" * 40,
            "runtime_digest_readback": "sha256:" + "2" * 64,
            "rollback_source_sha": "4" * 40,
            "rollback_image_digest": "sha256:" + "5" * 64,
        }

    def complete_api(self) -> dict[str, object]:
        return {
            "application": "example",
            "health": "PASS",
            "readiness": "PASS",
            "version": "PASS",
            "capabilities": "PASS",
            "openapi_alignment": "PASS",
            "gateway_alignment": "PASS",
            "runtime_attribution": "PASS",
            "source_sha": "1" * 40,
            "image_digest": "sha256:" + "2" * 64,
        }

    def test_complete_workload_passes(self) -> None:
        self.assertEqual(
            MODULE.validate_workload(self.complete_workload(), 0, self.forbidden),
            [],
        )

    def test_mutable_image_and_missing_runtime_readback_fail(self) -> None:
        record = self.complete_workload()
        record["image"] = "ghcr.io/owner/example:latest"
        record["runtime_digest_readback"] = "UNKNOWN"
        blockers = MODULE.validate_workload(record, 0, self.forbidden)
        self.assertTrue(any("immutable OCI digest" in item for item in blockers))
        self.assertTrue(any("mutable latest" in item for item in blockers))
        self.assertTrue(any("runtime digest readback" in item for item in blockers))

    def test_identical_rollback_is_rejected(self) -> None:
        record = self.complete_workload()
        record["rollback_source_sha"] = record["protected_source_sha"]
        record["rollback_image_digest"] = record["runtime_digest_readback"]
        blockers = MODULE.validate_workload(record, 0, self.forbidden)
        self.assertTrue(any("identical" in item for item in blockers))

    def test_complete_api_passes(self) -> None:
        self.assertEqual(MODULE.validate_api_record(self.complete_api(), 0, self.forbidden), [])

    def test_api_missing_capability_and_alignment_fail(self) -> None:
        record = self.complete_api()
        record["capabilities"] = "PENDING"
        record["gateway_alignment"] = "FAIL"
        blockers = MODULE.validate_api_record(record, 0, self.forbidden)
        self.assertTrue(any("capabilities" in item for item in blockers))
        self.assertTrue(any("gateway_alignment" in item for item in blockers))

    def test_select_records_prefers_exact_count(self) -> None:
        document = {
            "other": [{"name": "one"}],
            "workloads": [self.complete_workload(), self.complete_workload()],
        }
        path, records = MODULE.select_records(document, 2, "workloads")
        self.assertEqual(path, "$.workloads")
        self.assertEqual(len(records), 2)

    def test_zero_and_named_placeholders_are_rejected(self) -> None:
        self.assertTrue(MODULE.is_placeholder("0" * 40, self.forbidden))
        self.assertTrue(MODULE.is_placeholder("UNKNOWN", self.forbidden))
        self.assertTrue(MODULE.is_placeholder("REPLACE_WITH_SHA", self.forbidden))
        self.assertFalse(MODULE.is_placeholder("owner/repository", self.forbidden))


if __name__ == "__main__":
    unittest.main()
