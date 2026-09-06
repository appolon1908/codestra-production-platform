from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "validate_openai_provider_runtime_contract.py"
COMPOSE = ROOT / "deploy" / "middleware" / "compose.openai-provider.yaml"
LOCK = ROOT / "deploy" / "middleware" / "openai-provider-release-lock.json"
APPROVED_LOCK = ROOT / "deploy" / "middleware" / "approved-release-lock.json"
WORKFLOW = ROOT / ".github" / "workflows" / "openai-provider-runtime-contract.yml"

SPEC = importlib.util.spec_from_file_location(
    "validate_openai_provider_runtime_contract",
    SCRIPT,
)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


class OpenAIProviderRuntimeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.compose, cls.compose_text = VALIDATOR.load_yaml(COMPOSE)
        cls.release_lock = VALIDATOR.load_json(LOCK)
        cls.approved_lock = VALIDATOR.load_json(APPROVED_LOCK)

    def validate(
        self,
        *,
        compose: dict | None = None,
        compose_text: str | None = None,
        release_lock: dict | None = None,
        approved_lock: dict | None = None,
    ) -> list[str]:
        return VALIDATOR.validate_contract(
            copy.deepcopy(compose if compose is not None else self.compose),
            self.compose_text if compose_text is None else compose_text,
            copy.deepcopy(
                release_lock if release_lock is not None else self.release_lock
            ),
            copy.deepcopy(
                approved_lock if approved_lock is not None else self.approved_lock
            ),
        )

    def service(self, compose: dict) -> dict:
        return compose["services"][VALIDATOR.SERVICE]

    def test_committed_contract_is_fail_closed_and_valid(self) -> None:
        self.assertEqual(self.validate(), [])

    def test_provider_cannot_be_enabled_in_base_contract(self) -> None:
        compose = copy.deepcopy(self.compose)
        self.service(compose)["environment"]["OPENAI_PROVIDER_ENABLED"] = "true"
        errors = self.validate(compose=compose)
        self.assertIn("environment OPENAI_PROVIDER_ENABLED mismatch", errors)

    def test_raw_api_key_environment_entry_is_rejected(self) -> None:
        compose = copy.deepcopy(self.compose)
        self.service(compose)["environment"]["OPENAI_API_KEY"] = "not-a-real-key"
        errors = self.validate(
            compose=compose,
            compose_text=self.compose_text + "\n      OPENAI_API_KEY: forbidden\n",
        )
        self.assertIn(
            "raw secret environment key forbidden: OPENAI_API_KEY",
            errors,
        )
        self.assertIn("raw OPENAI_API_KEY environment entry is forbidden", errors)
        self.assertNotIn("not-a-real-key", "\n".join(errors))

    def test_mutable_or_mismatched_image_is_rejected(self) -> None:
        compose = copy.deepcopy(self.compose)
        self.service(compose)["image"] = (
            "ghcr.io/codestra-srl/codestra-middleware:latest"
        )
        errors = self.validate(
            compose=compose,
            compose_text=self.compose_text + "\n# latest\n",
        )
        self.assertIn("service image mismatch", errors)
        self.assertIn("mutable latest reference is forbidden", errors)

    def test_profile_and_network_are_mandatory(self) -> None:
        compose = copy.deepcopy(self.compose)
        self.service(compose)["profiles"] = []
        self.service(compose)["networks"] = ["default"]
        errors = self.validate(compose=compose)
        self.assertIn("service profile mismatch", errors)
        self.assertIn("service must use only middleware_backend", errors)

    def test_ports_privilege_and_host_path_creation_are_rejected(self) -> None:
        compose = copy.deepcopy(self.compose)
        service = self.service(compose)
        service["ports"] = ["8080:8080"]
        service["privileged"] = True
        service["volumes"][0]["bind"]["create_host_path"] = True
        errors = self.validate(compose=compose)
        self.assertIn("service must not define ports", errors)
        self.assertIn("service must not define privileged", errors)
        self.assertTrue(
            any("must disable host-path creation" in error for error in errors)
        )

    def test_source_and_image_must_match_approved_middleware_lock(self) -> None:
        release_lock = copy.deepcopy(self.release_lock)
        release_lock["source_revision"] = "1" * 40
        release_lock["image"] = (
            "ghcr.io/codestra-srl/codestra-middleware@sha256:" + "2" * 64
        )
        errors = self.validate(release_lock=release_lock)
        self.assertIn("OpenAI source revision binding mismatch", errors)
        self.assertIn("OpenAI image binding mismatch", errors)

    def test_activation_lock_cannot_claim_pass_or_commit_an_overlay(self) -> None:
        release_lock = copy.deepcopy(self.release_lock)
        release_lock["activation"]["status"] = "PASS"
        release_lock["activation"]["activation_overlay_committed"] = True
        release_lock["activation"]["production_effect_on_merge"] = True
        errors = self.validate(release_lock=release_lock)
        self.assertIn("activation status mismatch", errors)
        self.assertIn("activation activation_overlay_committed mismatch", errors)
        self.assertIn("activation production_effect_on_merge mismatch", errors)

    def test_egress_and_rollback_evidence_cannot_be_removed(self) -> None:
        release_lock = copy.deepcopy(self.release_lock)
        evidence = release_lock["activation"]["required_evidence"]
        evidence.remove("TLS egress restricted to api.openai.com:443")
        evidence.remove("rollback to the previously certified Qwen worker")
        errors = self.validate(release_lock=release_lock)
        self.assertIn("activation required evidence set mismatch", errors)

    def test_secret_mounts_are_exact_read_only_and_non_creating(self) -> None:
        compose = copy.deepcopy(self.compose)
        mount = self.service(compose)["volumes"][1]
        mount["source"] = "/tmp/openai-key"
        mount["read_only"] = False
        errors = self.validate(compose=compose)
        self.assertTrue(any("must be read-only" in error for error in errors))
        self.assertIn("service protected bind-mount set mismatch", errors)

    def test_model_values_are_not_overridden_before_runtime_probe(self) -> None:
        compose = copy.deepcopy(self.compose)
        self.service(compose)["environment"]["OPENAI_CHAT_MODEL"] = "unverified"
        errors = self.validate(compose=compose)
        self.assertIn(
            "model identifiers must remain source-locked and be runtime-probed",
            errors,
        )

    def test_workflow_is_secret_free_and_exact_source_bound(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertNotIn("secrets.", workflow)
        self.assertNotIn("OPENAI_API_KEY", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertIn("github.event.pull_request.head.sha", workflow)
        self.assertIn("git rev-parse HEAD", workflow)
        self.assertIn("docker compose --profile openai-provider", workflow)

    def test_evidence_never_contains_secret_values(self) -> None:
        payload = {
            "schema_version": 1,
            "status": "PASS",
            "component": VALIDATOR.SERVICE,
            "production_changed": False,
            "provider_enabled": False,
            "secret_values_read": False,
            "secret_values_recorded": False,
            "runtime_contacted": False,
            "blockers": [],
        }
        rendered = json.dumps(payload)
        self.assertNotIn("api-key", rendered)
        self.assertNotIn("safety-salt", rendered)


if __name__ == "__main__":
    unittest.main()
