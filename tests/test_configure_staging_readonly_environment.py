from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "configure_staging_readonly_environment.py"
WORKFLOW = ROOT / ".github" / "workflows" / "configure-staging-readonly-environment.yml"
SPEC = importlib.util.spec_from_file_location(
    "configure_staging_readonly_environment",
    SCRIPT,
)
assert SPEC and SPEC.loader
CONFIGURATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONFIGURATOR)


class ConfigureStagingReadonlyEnvironmentTests(unittest.TestCase):
    def test_constants_are_exact_and_read_only(self) -> None:
        self.assertEqual(CONFIGURATOR.ENVIRONMENT, "staging-readonly")
        self.assertEqual(
            CONFIGURATOR.ALLOWED_BRANCH,
            "release/production-activation",
        )
        self.assertEqual(
            CONFIGURATOR.SAFE_VARIABLES,
            {
                "CODESTRA_STAGING_CANARY_MAX_PERCENT": "1",
                "CODESTRA_STAGING_KONG_ROUTE_COUNT": "29",
            },
        )

    def test_empty_environment_enables_only_custom_branch_policies(self) -> None:
        payload = CONFIGURATOR.extract_protection_settings({})
        self.assertEqual(set(payload), {"deployment_branch_policy"})
        self.assertEqual(
            payload["deployment_branch_policy"],
            {
                "protected_branches": False,
                "custom_branch_policies": True,
            },
        )

    def test_existing_wait_timer_and_reviewers_are_preserved(self) -> None:
        payload = CONFIGURATOR.extract_protection_settings(
            {
                "protection_rules": [
                    {"type": "wait_timer", "wait_timer": 17},
                    {
                        "type": "required_reviewers",
                        "prevent_self_review": True,
                        "reviewers": [
                            {
                                "type": "User",
                                "reviewer": {"id": 77101516, "type": "User"},
                            },
                            {
                                "type": "Team",
                                "reviewer": {"id": 42, "type": "Team"},
                            },
                        ],
                    },
                ]
            }
        )
        self.assertEqual(payload["wait_timer"], 17)
        self.assertTrue(payload["prevent_self_review"])
        self.assertEqual(
            payload["reviewers"],
            [
                {"type": "User", "id": 77101516},
                {"type": "Team", "id": 42},
            ],
        )

    def test_malformed_reviewers_are_not_forwarded(self) -> None:
        with self.assertRaises(CONFIGURATOR.ConfigurationError):
            CONFIGURATOR.extract_protection_settings(
                {
                    "protection_rules": [
                        {
                            "type": "required_reviewers",
                            "reviewers": [
                                {"type": "User", "reviewer": {"id": "not-an-int"}},
                                {"type": "Unknown", "reviewer": {"id": 7}},
                                "not-an-object",
                            ],
                        }
                    ]
                }
            )

    def test_branch_only_environment_does_not_request_paid_rules(self) -> None:
        payload = CONFIGURATOR.extract_protection_settings(
            {"protection_rules": [{"type": "branch_policy"}]}
        )
        self.assertEqual(set(payload), {"deployment_branch_policy"})

    def test_malformed_timer_cannot_be_replaced_by_zero(self) -> None:
        with self.assertRaises(CONFIGURATOR.ConfigurationError):
            CONFIGURATOR.extract_protection_settings(
                {"protection_rules": [{"type": "wait_timer", "wait_timer": "17"}]}
            )

    def test_malformed_rules_fail_before_any_mutation(self) -> None:
        from unittest.mock import patch
        cases = [None, {}, [None], [{}],
                 [{"type": "wait_timer", "wait_timer": 17}, {"type": "wait_timer", "wait_timer": 0}],
                 [{"type": "required_reviewers", "prevent_self_review": "false",
                   "reviewers": [{"type": "User", "id": 1}]}],
                 [{"type": "required_reviewers", "reviewers": [{"type": "User", "id": -1}]}]]
        for rules in cases:
            with self.subTest(rules=rules), patch.object(CONFIGURATOR, "api_request", return_value=(200, {"protection_rules": rules})) as api:
                with self.assertRaises(CONFIGURATOR.ConfigurationError):
                    CONFIGURATOR.configure("synthetic-test-only")
                self.assertEqual(api.call_count, 1)
                self.assertEqual(api.call_args.args[0], "GET")

    def test_lost_timer_in_readback_cannot_report_pass(self) -> None:
        from unittest.mock import patch
        before = {"protection_rules": [{"type": "wait_timer", "wait_timer": 17}]}
        after = {"protection_rules": [], "deployment_branch_policy": {
            "protected_branches": False, "custom_branch_policies": True}}
        policies = {"branch_policies": [{"id": 1, "name": CONFIGURATOR.ALLOWED_BRANCH, "type": "branch"}]}
        with patch.object(CONFIGURATOR, "api_request", side_effect=[
            (200, before), (200, {}), (200, policies), (200, after)
        ]), patch.object(CONFIGURATOR, "upsert_environment_variable"):
            with self.assertRaisesRegex(CONFIGURATOR.ConfigurationError, "not preserved"):
                CONFIGURATOR.configure("synthetic-test-only")

    def test_admin_token_is_never_exposed_to_feature_branch_pushes(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("\n  pull_request:\n", workflow)
        self.assertIn("\n  workflow_dispatch:\n", workflow)
        self.assertNotIn("\n  push:\n", workflow)
        self.assertIn(
            "github.ref == 'refs/heads/release/production-activation'",
            workflow,
        )
        self.assertIn("github.actor == github.repository_owner", workflow)
        self.assertIn("name: repository-administration", workflow)
        self.assertEqual(
            workflow.count(
                "\n          CODESTRA_REPOSITORY_ADMIN_TOKEN: "
                "${{ secrets.CODESTRA_REPOSITORY_ADMIN_TOKEN }}"
            ),
            1,
        )
        self.assertNotIn(
            "\n    env:\n      CODESTRA_REPOSITORY_ADMIN_TOKEN:",
            workflow,
        )


if __name__ == "__main__":
    unittest.main()
