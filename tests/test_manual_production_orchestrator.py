from __future__ import annotations

import copy
import base64
import hashlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import yaml

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
        controller = next(
            component
            for component in candidate["components"]
            if component["repository"] == "appolon1908-hue/codestra-production-platform"
        )
        controller["source_sha"] = candidate["controller_sha"]
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

    def test_missing_live_effect_control_is_rejected(self) -> None:
        candidate = self.executable_candidate()
        del candidate["safety"]["payment_execution"]
        with self.assertRaisesRegex(MODULE.PolicyError, "safety controls are incomplete"):
            MODULE.validate_candidate(self.catalog, candidate, phase="plan")

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

    def test_incomplete_rollback_image_set_is_rejected(self) -> None:
        candidate = self.executable_candidate()
        component = next(item for item in candidate["components"] if item["images"])
        component["previous_images"] = []
        with self.assertRaises(MODULE.PolicyError):
            MODULE.validate_candidate(self.catalog, candidate, phase="plan")

    def test_controller_component_uses_non_self_referential_policy_base(self) -> None:
        candidate = self.executable_candidate()
        controller = next(
            item
            for item in candidate["components"]
            if item["repository"] == self.catalog["authority_policy"]["controller"]
        )
        controller["source_sha"] = "f" * 40
        with self.assertRaisesRegex(MODULE.PolicyError, "controller component source_sha"):
            MODULE.validate_candidate(self.catalog, candidate, phase="plan")

    def test_authority_policy_rejects_legacy_or_contradictory_canonical_role(self) -> None:
        catalog = copy.deepcopy(self.catalog)
        middleware = next(
            item
            for item in catalog["repositories"]
            if item["repository"] == "appolon1908-hue/Middleware-"
        )
        middleware["role"] = "transitional-middleware"
        with self.assertRaisesRegex(MODULE.PolicyError, "canonical Middleware catalog role"):
            MODULE.validate_catalog(catalog)

        catalog = copy.deepcopy(self.catalog)
        catalog["authority_policy"]["canonical_middleware"] = "Codestra-SRL/codestra-middleware"
        with self.assertRaisesRegex(MODULE.PolicyError, "canonical Middleware authority"):
            MODULE.validate_catalog(catalog)

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

    def test_incorrect_candidate_file_hash_is_rejected_before_dispatch(self) -> None:
        candidate = self.executable_candidate()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidate.json"
            path.write_text(json.dumps(candidate) + "\n", encoding="utf-8")
            arguments = SimpleNamespace(
                catalog=str(CATALOG),
                candidate=str(path),
                phase="plan",
                candidate_sha256="f" * 64,
                prior_evidence_sha256=MODULE.ZERO64,
                output=str(Path(directory) / "output.json"),
            )
            with self.assertRaisesRegex(MODULE.PolicyError, "candidate file SHA-256 mismatch"):
                MODULE.command_dispatch_intents(arguments)

    def preflight_fixture(
        self,
    ) -> tuple[dict, dict, dict, dict, dict, bytes, dict]:
        expected = copy.deepcopy(
            next(
                item
                for item in self.catalog["repositories"]
                if item["repository"] == "appolon1908-hue/Middleware-"
            )
        )
        catalog = {
            "repositories": [expected],
            "contract_path": ".codestra/production-orchestrator-contract.v1.json",
            "authority_policy": {
                "controller": "appolon1908-hue/codestra-production-platform"
            },
            "check_policy": {
                "default_app_id": 15368,
                "require_protected_branch_binding": True,
            },
        }
        source_sha = "a" * 40
        image = "ghcr.io/appolon1908-hue/codestra-middleware@sha256:" + "b" * 64
        rollback = "ghcr.io/appolon1908-hue/codestra-middleware@sha256:" + "c" * 64
        candidate = {
            "release_id": "codestra-release-test",
            "controller_sha": "d" * 40,
            "components": [
                {
                    "repository": expected["repository"],
                    "source_sha": source_sha,
                    "contract_sha256": "",
                    "images": [image],
                    "previous_images": [rollback],
                }
            ],
        }
        contract = {
            "schema_version": MODULE.CONTRACT_SCHEMA,
            "repository": expected["repository"],
            "repository_id": expected["repository_id"],
            "default_branch": expected["default_branch"],
            "role": expected["role"],
            "release_intent_workflow": MODULE.INTENT_WORKFLOW,
            "deployment_authority": False,
            "require_verified_commit": True,
            "required_checks": ["validate"],
            "supported_phases": ["plan"],
            "artifact_policy": {
                "minimum_images": 1,
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
        contract_bytes = (json.dumps(contract, sort_keys=True) + "\n").encode()
        candidate["components"][0]["contract_sha256"] = hashlib.sha256(contract_bytes).hexdigest()
        branch = {
            "protected": True,
            "commit": {"sha": source_sha},
        }
        status_policy = {
            "contexts": ["validate"],
            "checks": [{"context": "validate", "app_id": 15368}],
        }
        check = {
            "name": "validate",
            "app": {"id": 15368},
            "status": "completed",
            "conclusion": "success",
            "completed_at": "2026-09-08T00:00:00Z",
        }
        return (
            catalog,
            candidate,
            contract,
            branch,
            status_policy,
            contract_bytes,
            check,
        )

    def run_preflight(
        self,
        tmp_path: Path,
        *,
        candidate: dict,
        catalog: dict,
        contract_bytes: bytes,
        branch: dict,
        status_policy: dict | None,
        checks: list[dict],
        rules_policy: list[dict] | None = None,
    ) -> dict:
        repository = catalog["repositories"][0]["repository"]

        class FakeGitHub:
            def __init__(self, _token: str):
                pass

            def get(self, path: str):
                if path == f"/repos/{repository}":
                    expected = catalog["repositories"][0]
                    return {
                        "id": expected["repository_id"],
                        "archived": False,
                        "disabled": False,
                        "default_branch": expected["default_branch"],
                    }
                if "/branches/" in path:
                    return branch
                if "/contents/" in path:
                    return {
                        "encoding": "base64",
                        "content": base64.b64encode(contract_bytes).decode(),
                    }
                if "/commits/" in path:
                    return {"commit": {"verification": {"verified": True}}}
                raise AssertionError(f"unexpected GitHub path: {path}")

            def get_paginated(self, path: str, *, items_key=None):
                if "/check-runs" in path and items_key == "check_runs":
                    return checks
                if "/rules/branches/" in path:
                    return [] if rules_policy is None else rules_policy
                raise AssertionError(f"unexpected paginated GitHub path: {path}")

            def get_optional(self, path: str):
                if path.endswith("/protection/required_status_checks"):
                    return status_policy
                raise AssertionError(f"unexpected optional GitHub path: {path}")

        output = tmp_path / "preflight.json"
        with mock.patch.object(MODULE, "GitHub", FakeGitHub), mock.patch.dict(
            os.environ, {"CODESTRA_ORCHESTRATOR_TOKEN": "test-token"}
        ):
            return MODULE.verify_github(
                catalog,
                candidate,
                phase="plan",
                candidate_file_sha256="e" * 64,
                output=output,
            )

    def test_preflight_rejects_missing_required_check(self) -> None:
        catalog, candidate, _, branch, status_policy, contract_bytes, _ = self.preflight_fixture()
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(
            MODULE.PolicyError, "required exact-head checks not successful"
        ):
            self.run_preflight(
                Path(directory),
                candidate=candidate,
                catalog=catalog,
                contract_bytes=contract_bytes,
                branch=branch,
                status_policy=status_policy,
                checks=[],
            )

    def test_preflight_uses_authoritative_app_bound_status_policy(self) -> None:
        catalog, candidate, _, branch, status_policy, contract_bytes, check = self.preflight_fixture()
        with tempfile.TemporaryDirectory() as directory:
            evidence = self.run_preflight(
                Path(directory),
                candidate=candidate,
                catalog=catalog,
                contract_bytes=contract_bytes,
                branch=branch,
                status_policy=status_policy,
                checks=[check],
            )

        self.assertEqual(
            evidence["repositories"][0]["required_check_apps"],
            {"validate": 15368},
        )

    def test_preflight_accepts_ruleset_only_app_bound_status_policy(self) -> None:
        catalog, candidate, _, branch, _, contract_bytes, check = self.preflight_fixture()
        rules_policy = [
            {
                "type": "required_status_checks",
                "parameters": {
                    "required_status_checks": [
                        {"context": "validate", "integration_id": 15368}
                    ]
                },
            }
        ]
        with tempfile.TemporaryDirectory() as directory:
            evidence = self.run_preflight(
                Path(directory),
                candidate=candidate,
                catalog=catalog,
                contract_bytes=contract_bytes,
                branch=branch,
                status_policy=None,
                checks=[check],
                rules_policy=rules_policy,
            )

        self.assertEqual(
            evidence["repositories"][0]["required_check_apps"],
            {"validate": 15368},
        )

    def test_preflight_rejects_wrong_ruleset_check_app(self) -> None:
        catalog, candidate, _, branch, _, contract_bytes, check = self.preflight_fixture()
        rules_policy = [
            {
                "type": "required_status_checks",
                "parameters": {
                    "required_status_checks": [
                        {"context": "validate", "integration_id": 999}
                    ]
                },
            }
        ]
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(
            MODULE.PolicyError, "bound to the wrong app"
        ):
            self.run_preflight(
                Path(directory),
                candidate=candidate,
                catalog=catalog,
                contract_bytes=contract_bytes,
                branch=branch,
                status_policy=None,
                checks=[check],
                rules_policy=rules_policy,
            )

    def test_preflight_rejects_conflicting_classic_and_ruleset_apps(self) -> None:
        catalog, candidate, _, branch, status_policy, contract_bytes, check = self.preflight_fixture()
        rules_policy = [
            {
                "type": "required_status_checks",
                "parameters": {
                    "required_status_checks": [
                        {"context": "validate", "integration_id": 999}
                    ]
                },
            }
        ]
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(
            MODULE.PolicyError, "conflicting app bindings"
        ):
            self.run_preflight(
                Path(directory),
                candidate=candidate,
                catalog=catalog,
                contract_bytes=contract_bytes,
                branch=branch,
                status_policy=status_policy,
                checks=[check],
                rules_policy=rules_policy,
            )

    def test_optional_github_read_only_swallows_not_found(self) -> None:
        error = urllib.error.HTTPError(
            "https://api.github.test/missing", 404, "not found", {}, io.BytesIO(b"{}")
        )
        with mock.patch.object(MODULE.GitHub, "_open", side_effect=error):
            self.assertIsNone(MODULE.GitHub("token").get_optional("/missing"))

    def test_optional_github_read_fails_on_forbidden(self) -> None:
        error = urllib.error.HTTPError(
            "https://api.github.test/forbidden", 403, "forbidden", {}, io.BytesIO(b"{}")
        )
        with mock.patch.object(MODULE.GitHub, "_open", side_effect=error), self.assertRaisesRegex(
            MODULE.PolicyError, "HTTP 403"
        ):
            MODULE.GitHub("token").get_optional("/forbidden")

    def test_github_paginated_read_includes_later_required_rules(self) -> None:
        class Response(io.BytesIO):
            def __init__(self, value: object, link: str = ""):
                super().__init__(json.dumps(value).encode())
                self.headers = {"Link": link}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                self.close()

        later_rule = {
            "type": "required_status_checks",
            "parameters": {
                "required_status_checks": [
                    {"context": "page-two-check", "integration_id": 15368}
                ]
            },
        }
        first = Response([], '<https://api.github.com/rules?page=2>; rel="next"')
        second = Response([later_rule])
        with mock.patch.object(
            MODULE.GitHub, "_open", side_effect=[first, second]
        ) as request:
            rules = MODULE.GitHub("token").get_paginated("/rules?per_page=100")

        self.assertEqual(rules, [later_rule])
        self.assertEqual(request.call_count, 2)

    def test_preflight_rejects_wrong_required_check_app(self) -> None:
        catalog, candidate, _, branch, status_policy, contract_bytes, check = self.preflight_fixture()
        status_policy["checks"][0]["app_id"] = 999
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(
            MODULE.PolicyError, "bound to the wrong app"
        ):
            self.run_preflight(
                Path(directory),
                candidate=candidate,
                catalog=catalog,
                contract_bytes=contract_bytes,
                branch=branch,
                status_policy=status_policy,
                checks=[check],
            )

    def test_preflight_rejects_context_without_app_binding(self) -> None:
        catalog, candidate, _, branch, status_policy, contract_bytes, check = self.preflight_fixture()
        status_policy["checks"] = []
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(
            MODULE.PolicyError, "not bound by branch protection"
        ):
            self.run_preflight(
                Path(directory),
                candidate=candidate,
                catalog=catalog,
                contract_bytes=contract_bytes,
                branch=branch,
                status_policy=status_policy,
                checks=[check],
            )

    def test_preflight_rejects_success_from_unbound_check_app(self) -> None:
        catalog, candidate, _, branch, status_policy, contract_bytes, check = self.preflight_fixture()
        check["app"]["id"] = 999
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(
            MODULE.PolicyError, "required exact-head checks not successful"
        ):
            self.run_preflight(
                Path(directory),
                candidate=candidate,
                catalog=catalog,
                contract_bytes=contract_bytes,
                branch=branch,
                status_policy=status_policy,
                checks=[check],
            )

    def test_preflight_rejects_stale_source_head(self) -> None:
        catalog, candidate, _, branch, status_policy, contract_bytes, check = self.preflight_fixture()
        branch["commit"]["sha"] = "f" * 40
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(
            MODULE.PolicyError, "not the exact protected branch head"
        ):
            self.run_preflight(
                Path(directory),
                candidate=candidate,
                catalog=catalog,
                contract_bytes=contract_bytes,
                branch=branch,
                status_policy=status_policy,
                checks=[check],
            )

    def test_preflight_rejects_contract_mismatch(self) -> None:
        catalog, candidate, contract, branch, status_policy, _, check = self.preflight_fixture()
        contract["role"] = "transitional-middleware"
        contract_bytes = (json.dumps(contract, sort_keys=True) + "\n").encode()
        candidate["components"][0]["contract_sha256"] = hashlib.sha256(contract_bytes).hexdigest()
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(
            MODULE.PolicyError, "contract role mismatch"
        ):
            self.run_preflight(
                Path(directory),
                candidate=candidate,
                catalog=catalog,
                contract_bytes=contract_bytes,
                branch=branch,
                status_policy=status_policy,
                checks=[check],
            )

    def test_authority_declarations_agree_with_protected_migration(self) -> None:
        canonical = self.catalog["authority_policy"]["canonical_middleware"]
        legacy = self.catalog["authority_policy"]["legacy_middleware_rollback_only"]
        repositories = {item["repository"]: item for item in self.catalog["repositories"]}
        template_repositories = {item["repository"] for item in self.template["components"]}
        source_lock = yaml.safe_load((ROOT / "PRODUCTION-SOURCE-LOCK.yaml").read_text())

        self.assertEqual(repositories[canonical]["role"], "canonical-middleware")
        self.assertNotIn(legacy, repositories)
        self.assertIn(canonical, template_repositories)
        self.assertNotIn(legacy, template_repositories)
        self.assertEqual(
            source_lock["middleware_authorities"]["protected_production_tuple"]["repository"],
            canonical,
        )

        runbooks = "\n".join(
            (ROOT / path).read_text(encoding="utf-8")
            for path in (
                "docs/MANUAL-ONE-CLICK-PRODUCTION-ORCHESTRATOR.md",
                "docs/ONE-CLICK-GO-LIVE.md",
                "docs/SERVER_A_PRODUCTION_RELEASE_TUPLE.md",
            )
        )
        self.assertIn(f"`{canonical}` is the canonical forward Middleware", runbooks)
        self.assertNotIn(f"`{legacy}` remains the canonical Middleware", runbooks)
        self.assertNotIn(f"canonical `{legacy}`", runbooks)

        token_runbook = (
            ROOT / "docs/MANUAL-ONE-CLICK-PRODUCTION-ORCHESTRATOR.md"
        ).read_text(encoding="utf-8")
        self.assertIn("Administration: read", token_runbook)
        self.assertIn("Do not grant repository\nadministration write", token_runbook)

    def test_controller_plan_intent_dispatches_and_waits_on_validated_head(self) -> None:
        expected = copy.deepcopy(
            next(
                item
                for item in self.catalog["repositories"]
                if item["repository"] == self.catalog["authority_policy"]["controller"]
            )
        )
        policy_base = "a" * 40
        workflow_head = "b" * 40
        catalog = {
            "repositories": [expected],
            "contract_path": ".codestra/production-orchestrator-contract.v1.json",
            "authority_policy": {"controller": expected["repository"]},
        }
        candidate = {
            "release_id": "codestra-controller-intent-test",
            "components": [
                {
                    "repository": expected["repository"],
                    "source_sha": policy_base,
                    "images": [],
                    "previous_images": [],
                }
            ],
        }
        contract = json.loads(
            (ROOT / ".codestra/production-orchestrator-contract.v1.json").read_text()
        )
        contract_bytes = (json.dumps(contract) + "\n").encode()
        posts: list[tuple[str, dict]] = []
        waited: list[str] = []

        class FakeGitHub:
            def __init__(self, _token: str):
                pass

            def get(self, path: str):
                if "/branches/" in path:
                    return {"protected": True, "commit": {"sha": workflow_head}}
                if "/compare/" in path:
                    return {"status": "ahead"}
                if "/contents/" in path:
                    return {
                        "encoding": "base64",
                        "content": base64.b64encode(contract_bytes).decode(),
                    }
                if "/artifacts" in path:
                    return {
                        "artifacts": [
                            {
                                "id": 99,
                                "name": f"codestra-release-intent-plan-{workflow_head}",
                                "expired": False,
                                "digest": "sha256:" + "c" * 64,
                            }
                        ]
                    }
                raise AssertionError(f"unexpected GitHub path: {path}")

            def post(self, path: str, payload: dict):
                posts.append((path, payload))

        def fake_wait(_github, _repository, _workflow, _branch, source_sha, *_args):
            waited.append(source_sha)
            return {"id": 42, "run_attempt": 1}

        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            MODULE, "GitHub", FakeGitHub
        ), mock.patch.object(MODULE, "wait_for_dispatch_run", fake_wait), mock.patch.dict(
            os.environ,
            {
                "CODESTRA_ORCHESTRATOR_TOKEN": "test-token",
                "GITHUB_SHA": workflow_head,
            },
        ):
            evidence = MODULE.dispatch_intents(
                catalog,
                candidate,
                phase="plan",
                candidate_file_sha256="d" * 64,
                prior_evidence_sha256=MODULE.ZERO64,
                output=Path(directory) / "evidence.json",
            )

        self.assertEqual(posts[0][1]["inputs"]["source_sha"], workflow_head)
        self.assertEqual(waited, [workflow_head])
        self.assertEqual(evidence["runs"][0]["source_sha"], workflow_head)
        self.assertEqual(
            evidence["runs"][0]["controller_policy_base_sha"], policy_base
        )

class GitHubOriginSecurityTests(unittest.TestCase):
    def test_rejects_untrusted_absolute_pagination_before_network(self):
        for url in ["https://attacker.invalid/page", "https://api.github.com.attacker.invalid/",
                    "https://user@api.github.com/", "https://api.github.com:444/",
                    "https://api.github.com/path#fragment"]:
            with self.subTest(url=url), mock.patch.object(MODULE.GitHub, '_open') as request:
                with self.assertRaises(MODULE.PolicyError):
                    MODULE.GitHub('synthetic-token').get(url)
                request.assert_not_called()

    def test_redirects_are_rejected(self):
        with self.assertRaisesRegex(MODULE.PolicyError, 'redirects are forbidden'):
            MODULE.NoGitHubRedirect().redirect_request(None, None, 302, '', {}, 'https://attacker.invalid')

    def test_pagination_is_bounded(self):
        pages = [([], f'https://api.github.com/rules?page={n}') for n in range(2, 103)]
        with mock.patch.object(MODULE.GitHub, '_request_page', side_effect=pages) as request:
            with self.assertRaisesRegex(MODULE.PolicyError, 'pagination limit'):
                MODULE.GitHub('synthetic-token').get_paginated('/rules')
            self.assertEqual(request.call_count, 100)


    def test_check_runs_on_later_pages_are_included(self):
        later_check = {"name": "validate", "app": {"id": 15368}, "conclusion": "success"}
        pages = [({"check_runs": []}, "https://api.github.com/check-runs?page=2"),
                 ({"check_runs": [later_check]}, None)]
        with mock.patch.object(MODULE.GitHub, "_request_page", side_effect=pages):
            checks = MODULE.GitHub("synthetic-token").get_paginated(
                "/check-runs?per_page=100", items_key="check_runs"
            )
        self.assertEqual(MODULE.latest_check_conclusions(checks), {("validate", 15368): "success"})

    def test_malformed_check_run_pages_are_rejected(self):
        for page in [[], {}, {"check_runs": None}, {"check_runs": {}}]:
            with self.subTest(page=page), mock.patch.object(
                MODULE.GitHub, "_request_page", return_value=(page, None)
            ), self.assertRaises(MODULE.PolicyError):
                MODULE.GitHub("synthetic-token").get_paginated("/check-runs", items_key="check_runs")

    def test_pagination_loop_is_rejected(self):
        with mock.patch.object(MODULE.GitHub, "_request_page", return_value=([], "/rules")) as request:
            with self.assertRaisesRegex(MODULE.PolicyError, "pagination loop"):
                MODULE.GitHub("synthetic-token").get_paginated("/rules")
            self.assertEqual(request.call_count, 1)


if __name__ == "__main__":
    unittest.main()
