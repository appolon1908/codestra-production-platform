from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/manual_production_orchestrator.py"
CATALOG = ROOT / "config/manual-production-orchestrator.catalog.v1.json"
TEMPLATE = ROOT / "config/manual-production-candidate.template.v1.json"

SPEC = importlib.util.spec_from_file_location("manual_production_orchestrator", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ManualProductionOrchestratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = json.loads(CATALOG.read_text())
        self.template = json.loads(TEMPLATE.read_text())

    def executable_candidate(self) -> dict:
        candidate = copy.deepcopy(self.template)
        candidate["template"] = False
        candidate["release_id"] = "codestra-20260903-portfolio-001"
        candidate["controller_sha"] = "1" * 40
        candidate["source_lock_sha"] = "2" * 40
        candidate["runtime_candidate_sha256"] = "3" * 64
        candidate["created_at"] = "2026-09-03T18:00:00Z"
        for index, component in enumerate(candidate["components"], 1):
            component["source_sha"] = f"{index:040x}"[-40:]
            component["contract_sha256"] = f"{index + 100:064x}"[-64:]
            if component["repository"] not in {
                "appolon1908-hue/Infustruction-repo",
                "appolon1908-hue/Keycloak",
                "appolon1908-hue/codestra-production-platform",
            }:
                slug = component["repository"].lower().replace("_", "-")
                prefix = f"ghcr.io/{slug}@sha256:"
                component["images"] = [prefix + f"{index:064x}"[-64:]]
                component["previous_images"] = [
                    prefix + f"{index + 200:064x}"[-64:]
                ]
        return candidate

    def test_committed_catalog_and_template_are_valid(self) -> None:
        MODULE.validate_catalog(self.catalog)
        MODULE.validate_candidate(
            self.catalog,
            self.template,
            phase="plan",
            allow_template=True,
        )

    def test_template_cannot_execute(self) -> None:
        with self.assertRaises(MODULE.PolicyError):
            MODULE.validate_candidate(self.catalog, self.template, phase="plan")

    def test_complete_candidate_is_valid_for_all_phases(self) -> None:
        candidate = self.executable_candidate()
        for phase in MODULE.PHASES:
            MODULE.validate_candidate(self.catalog, candidate, phase=phase)

    def test_live_effect_activation_is_rejected(self) -> None:
        candidate = self.executable_candidate()
        candidate["safety"]["live_email_delivery"] = True
        with self.assertRaises(MODULE.PolicyError):
            MODULE.validate_candidate(self.catalog, candidate, phase="production")

    def test_mutable_image_tag_is_rejected(self) -> None:
        candidate = self.executable_candidate()
        candidate["components"][4]["images"] = [
            "ghcr.io/appolon1908-hue/codestra:latest"
        ]
        with self.assertRaises(MODULE.PolicyError):
            MODULE.validate_candidate(self.catalog, candidate, phase="staging")

    def test_repository_coverage_is_exact(self) -> None:
        candidate = self.executable_candidate()
        candidate["components"].pop()
        with self.assertRaises(MODULE.PolicyError):
            MODULE.validate_candidate(self.catalog, candidate, phase="plan")

    def test_non_deployment_contract_cannot_claim_production(self) -> None:
        expected = next(
            item
            for item in self.catalog["repositories"]
            if item["repository"] == "appolon1908-hue/scrapper"
        )
        contract = {
            "schema_version": MODULE.CONTRACT_SCHEMA,
            "repository": expected["repository"],
            "repository_id": expected["repository_id"],
            "default_branch": expected["default_branch"],
            "role": expected["role"],
            "release_intent_workflow": MODULE.INTENT_WORKFLOW,
            "deployment_authority": False,
            "required_checks": ["validate"],
            "supported_phases": ["plan", "production"],
            "artifact_policy": {
                "minimum_images": 0,
                "maximum_images": 1,
                "require_digest": True,
                "allow_rebuild_after_staging": False,
                "allow_retag_after_staging": False,
            },
            "environments": {},
            "safety": {
                "external_effects_default": False,
                "live_email_delivery": False,
                "live_sms_delivery": False,
                "live_pstn_dialing": False,
                "odoo_write": False,
                "n8n_external_delivery": False,
                "live_trading": False,
                "payment_execution": False,
            },
        }
        with self.assertRaises(MODULE.PolicyError):
            MODULE.validate_contract(contract, expected)


if __name__ == "__main__":
    unittest.main()
