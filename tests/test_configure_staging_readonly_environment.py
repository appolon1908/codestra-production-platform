from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "configure_staging_readonly_environment.py"
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
        self.assertEqual(payload["wait_timer"], 0)
        self.assertFalse(payload["prevent_self_review"])
        self.assertIsNone(payload["reviewers"])
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
        payload = CONFIGURATOR.extract_protection_settings(
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
        self.assertIsNone(payload["reviewers"])


if __name__ == "__main__":
    unittest.main()
