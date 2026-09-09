from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "validate_staging_readonly_authority.py"
AUTHORITY = ROOT / "config" / "staging-readonly-authority.v1.json"
TEMPLATE = ROOT / "config" / "staging-readonly-endpoint-manifest.template.v1.json"
WORKFLOW = ROOT / ".github" / "workflows" / "staging-readonly-certification.yml"

SPEC = importlib.util.spec_from_file_location("staging_readonly_authority", SCRIPT)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


class StagingReadonlyAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.authority = VALIDATOR.load_json(AUTHORITY)
        self.template = VALIDATOR.load_json(TEMPLATE)

    def materialized_manifest(self) -> dict:
        manifest = copy.deepcopy(self.template)
        digest = "sha256:" + "2" * 64
        previous_digest = "sha256:" + "3" * 64
        component = {
            "name": "integration-control-plane",
            "repository": "appolon1908-hue/codestra-production-platform",
            "source_sha": "1" * 40,
            "image": "ghcr.io/appolon1908-hue/integration-control-plane",
            "image_digest": digest,
            "rebuild_allowed": False,
            "retag_allowed": False,
        }
        previous_component = {
            **component,
            "source_sha": "4" * 40,
            "image_digest": previous_digest,
        }
        manifest.update(template=False)
        manifest["candidate"] = {
            "release_id": "codestra-staging-20260903-1",
            "platform_source_sha": "1" * 40,
            "source_lock_sha256": "5" * 64,
            "candidate_manifest_sha256": "6" * 64,
            "components": [component],
        }
        manifest["previous_candidate"] = {
            "release_id": "codestra-staging-20260902-1",
            "components": [previous_component],
        }
        manifest["identity"] = {
            "issuer": "https://auth-staging.codestra.co/realms/codestra",
            "discovery_path": "/.well-known/openid-configuration",
            "expected_http_status": 200,
        }
        manifest["targets"] = [
            {
                "id": "platform",
                "base_url": "https://api-staging.codestra.co",
                "health_path": "/healthz",
                "readiness_path": "/readyz",
                "version_path": "/version",
                "capabilities_path": "/api/v1/platform/capabilities",
                "metrics_path": "/metrics",
                "allowed_methods": ["GET", "HEAD"],
            }
        ]
        manifest["kong"] = {
            "base_url": "https://api-staging.codestra.co",
            "route_count": 29,
            "routes": [
                {
                    "id": f"route-{index:02d}",
                    "method": "GET",
                    "path": f"/readonly-smoke/{index:02d}",
                    "expected_status": [200, 401, 403, 404],
                }
                for index in range(1, 30)
            ],
        }
        manifest["database"] = {
            "migration_evidence_endpoint": "https://api-staging.codestra.co/internal/readiness/migrations",
            "expected_heads": ["0057_platform_service_catalog"],
        }
        manifest["backups"]["off_host_uri"] = "s3://codestra-staging-backups/candidate"
        return manifest

    def test_committed_policy_is_valid_and_blocked_honestly(self) -> None:
        self.assertEqual(VALIDATOR.validate_authority(self.authority), [])
        self.assertEqual(self.authority["execution_status"], "BLOCKED")
        self.assertFalse(self.authority["deployment_authorized"])
        self.assertFalse(self.authority["production_canary_authorized"])

    def test_committed_manifest_remains_a_non_executable_template(self) -> None:
        self.assertEqual(
            VALIDATOR.validate_manifest(
                self.template,
                self.authority,
                allow_template=True,
            ),
            [],
        )
        self.assertTrue(self.template["template"])
        self.assertEqual(self.template["candidate"]["components"], [])

    def test_complete_materialized_manifest_is_structurally_valid(self) -> None:
        manifest = self.materialized_manifest()
        self.assertEqual(
            VALIDATOR.validate_manifest(
                manifest,
                self.authority,
                allow_template=False,
            ),
            [],
        )

    def test_one_live_effect_flag_blocks_the_manifest(self) -> None:
        manifest = self.materialized_manifest()
        manifest["safety_controls"]["LIVE_EMAIL_DELIVERY"] = True
        errors = VALIDATOR.validate_manifest(
            manifest,
            self.authority,
            allow_template=False,
        )
        self.assertTrue(any("LIVE_EMAIL_DELIVERY must remain false" in error for error in errors))

    def test_kong_requires_all_29_read_only_routes(self) -> None:
        manifest = self.materialized_manifest()
        manifest["kong"]["routes"].pop()
        errors = VALIDATOR.validate_manifest(
            manifest,
            self.authority,
            allow_template=False,
        )
        self.assertTrue(any("exactly 29 routes" in error for error in errors))

    def test_environment_evidence_names_missing_inputs_without_values(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            errors, evidence = VALIDATOR.validate_environment(self.authority, None)
        self.assertTrue(errors)
        self.assertEqual(evidence["status"], "BLOCKED")
        self.assertFalse(evidence["secret_values_recorded"])
        self.assertEqual(
            set(evidence["missing_secrets"]),
            VALIDATOR.REQUIRED_SECRETS,
        )
        rendered = json.dumps(evidence)
        self.assertNotIn("PRIVATE KEY", rendered)
        self.assertNotIn("Bearer ", rendered)

    def test_environment_cannot_override_failed_source_authority(self) -> None:
        manifest = self.materialized_manifest()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "endpoint-manifest.json"
            payload = json.dumps(manifest, sort_keys=True).encode("utf-8")
            path.write_bytes(payload)
            environment = {
                "CODESTRA_STAGING_OPERATOR_HOST": "192.0.2.10",
                "CODESTRA_STAGING_OPERATOR_USER": "codestra_stage",
                "CODESTRA_STAGING_OPERATOR_PORT": "22",
                "CODESTRA_STAGING_CANDIDATE_ID": manifest["candidate"]["release_id"],
                "CODESTRA_STAGING_CANDIDATE_MANIFEST_SHA256": manifest["candidate"]["candidate_manifest_sha256"],
                "CODESTRA_STAGING_ENDPOINT_MANIFEST_SHA256": hashlib.sha256(payload).hexdigest(),
                "CODESTRA_STAGING_KEYCLOAK_ISSUER": manifest["identity"]["issuer"],
                "CODESTRA_STAGING_OFF_HOST_BACKUP_URI": "s3://codestra-staging-backups/candidate",
                "CODESTRA_STAGING_CANARY_MAX_PERCENT": "1",
                "CODESTRA_STAGING_KONG_ROUTE_COUNT": "29",
                **{
                    f"HAS_{name}": "true"
                    for name in VALIDATOR.REQUIRED_SECRETS
                },
            }
            with patch.dict(os.environ, environment, clear=True):
                errors, evidence = VALIDATOR.validate_environment(
                    self.authority,
                    path,
                )
        self.assertTrue(any("source lock is not PASS" in error for error in errors))
        self.assertTrue(any("runtime candidate is not deployment-authorized" in error for error in errors))
        self.assertTrue(any("staging host is not created" in error for error in errors))
        self.assertEqual(evidence["status"], "BLOCKED")
        self.assertTrue(evidence["endpoint_manifest_valid"])

    def test_secret_backed_preflight_is_release_branch_only(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertNotIn("- ops/staging-readonly-authority-20260903", workflow)
        self.assertIn("\n  pull_request:\n", workflow)
        self.assertIn("\n  push:\n", workflow)
        self.assertIn("\n      - release/production-activation\n", workflow)
        self.assertIn(
            "github.ref == 'refs/heads/release/production-activation'",
            workflow,
        )
        self.assertIn("github.actor == github.repository_owner", workflow)
        self.assertIn("environment:\n      name: staging-readonly", workflow)
        self.assertEqual(
            workflow.count(
                "STAGING_ENDPOINT_MANIFEST_JSON: "
                "${{ secrets.CODESTRA_STAGING_READONLY_ENDPOINT_MANIFEST }}"
            ),
            1,
        )


if __name__ == "__main__":
    unittest.main()
