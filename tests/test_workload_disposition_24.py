from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/validate_workload_disposition_24.py"
SPEC = importlib.util.spec_from_file_location("workload_disposition_24", SCRIPT)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


class WorkloadDisposition24Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = VALIDATOR.load(VALIDATOR.SOURCE)
        self.document = VALIDATOR.load(VALIDATOR.DISPOSITION)

    def assert_rejected(self, mutation) -> None:
        candidate = copy.deepcopy(self.document)
        mutation(candidate)
        with self.assertRaises(ValueError):
            VALIDATOR.validate(self.source, candidate)

    def test_current_disposition_is_valid_and_honestly_blocked(self) -> None:
        VALIDATOR.validate(self.source, self.document)
        self.assertEqual(self.document["status"], "BLOCKED")
        self.assertFalse(self.document["production_changed"])
        self.assertFalse(self.document["runtime_contacted"])

    def test_exact_24_record_coverage_is_required(self) -> None:
        self.assert_rejected(lambda data: data["records"].pop())

    def test_current_runtime_identity_cannot_drift(self) -> None:
        self.assert_rejected(
            lambda data: data["records"][0].__setitem__(
                "current_image_id", "sha256:" + "0" * 64
            )
        )

    def test_ready_candidate_requires_exact_digest(self) -> None:
        row = next(
            index
            for index, value in enumerate(self.document["records"])
            if value.get("candidate_state") == "READY"
        )
        self.assert_rejected(
            lambda data: data["records"][row].__setitem__(
                "candidate_image_digest", "latest"
            )
        )

    def test_blocked_candidate_cannot_be_mislabeled_ready(self) -> None:
        row = next(
            index
            for index, value in enumerate(self.document["records"])
            if value.get("candidate_state") == "BLOCKED"
        )
        self.assert_rejected(
            lambda data: data["records"][row].__setitem__("candidate_state", "READY")
        )

    def test_live_effect_flag_cannot_be_enabled(self) -> None:
        self.assert_rejected(
            lambda data: data["safety_controls"].__setitem__(
                "LIVE_EMAIL_DELIVERY", True
            )
        )

    def test_pass_cannot_be_claimed_while_authorities_are_blocked(self) -> None:
        self.assert_rejected(lambda data: data.__setitem__("status", "PASS"))

    def test_retirement_cannot_claim_an_image_replacement(self) -> None:
        row = next(
            index
            for index, value in enumerate(self.document["records"])
            if value["disposition"] == "RETIRE_FROM_PRODUCTION"
        )
        self.assert_rejected(
            lambda data: data["records"][row].__setitem__(
                "candidate_image_digest", "sha256:" + "1" * 64
            )
        )


if __name__ == "__main__":
    unittest.main()
