from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "validate_staging_readonly_manifest_hardening.py"
WORKFLOW = ROOT / ".github" / "workflows" / "staging-readonly-certification.yml"

SPEC = importlib.util.spec_from_file_location(
    "staging_readonly_manifest_hardening",
    SCRIPT,
)
assert SPEC and SPEC.loader
HARDENING = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HARDENING)


class StagingReadonlyManifestHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source_lock = Path(self.directory.name) / "PRODUCTION-SOURCE-LOCK.yaml"
        self.source_lock.write_text("status: PASS\n", encoding="utf-8")
        self.platform_sha = "1" * 40
        self.off_host_uri = "s3://codestra-staging-backups/candidate"

    def component(
        self,
        *,
        source_sha: str,
        digest_character: str,
        image: str = "ghcr.io/appolon1908-hue/integration-control-plane",
        repository: str = "appolon1908-hue/codestra-production-platform",
    ) -> dict:
        return {
            "name": "integration-control-plane",
            "repository": repository,
            "source_sha": source_sha,
            "image": image,
            "image_digest": "sha256:" + digest_character * 64,
            "rebuild_allowed": False,
            "retag_allowed": False,
        }

    def manifest(self) -> dict:
        return {
            "schema_version": 1,
            "template": False,
            "environment": "staging-readonly",
            "candidate": {
                "release_id": "candidate-20260903",
                "platform_source_sha": self.platform_sha,
                "source_lock_sha256": HARDENING.file_sha256(self.source_lock),
                "candidate_manifest_sha256": "4" * 64,
                "components": [
                    self.component(source_sha="2" * 40, digest_character="5")
                ],
            },
            "previous_candidate": {
                "release_id": "candidate-20260902",
                "components": [
                    self.component(source_sha="3" * 40, digest_character="6")
                ],
            },
            "kong": {
                "route_count": 29,
                "routes": [
                    {
                        "id": f"route-{index:02d}",
                        "method": "GET",
                        "path": f"/readonly-smoke/{index:02d}",
                        "expected_status": [200, 401, 403],
                    }
                    for index in range(1, 30)
                ],
            },
            "backups": {
                "database_required": True,
                "odoo_filestore_required": True,
                "configuration_required": True,
                "off_host_copy_required": True,
                "off_host_uri": self.off_host_uri,
                "credential_ref": "CODESTRA_STAGING_OFF_HOST_BACKUP_CREDENTIAL",
            },
            "credential_policy": {
                "credentials_embedded": False,
                "bearer_credential_ref": "CODESTRA_STAGING_READONLY_BEARER_TOKEN",
                "metrics_credential_ref": "CODESTRA_STAGING_METRICS_BEARER_TOKEN",
            },
        }

    def validate(self, manifest: dict) -> list[str]:
        errors, _ = HARDENING.validate_manifest(
            manifest,
            source_lock_path=self.source_lock,
            expected_platform_sha=self.platform_sha,
            expected_off_host_uri=self.off_host_uri,
        )
        return errors

    def test_complete_manifest_passes_hardening(self) -> None:
        self.assertEqual(self.validate(self.manifest()), [])

    def test_route_smoke_cannot_accept_not_found_or_server_error(self) -> None:
        for status in (404, 500):
            with self.subTest(status=status):
                manifest = self.manifest()
                manifest["kong"]["routes"][0]["expected_status"] = [status]
                errors = self.validate(manifest)
                self.assertTrue(
                    any("may contain only 200, 204, 401, or 403" in error for error in errors)
                )

    def test_source_lock_hash_must_match_committed_bytes(self) -> None:
        manifest = self.manifest()
        manifest["candidate"]["source_lock_sha256"] = "7" * 64
        errors = self.validate(manifest)
        self.assertIn(
            "candidate.source_lock_sha256 does not match PRODUCTION-SOURCE-LOCK.yaml",
            errors,
        )

    def test_platform_sha_must_match_protected_workflow_sha(self) -> None:
        manifest = self.manifest()
        manifest["candidate"]["platform_source_sha"] = "8" * 40
        errors = self.validate(manifest)
        self.assertIn(
            "candidate.platform_source_sha does not match the protected workflow SHA",
            errors,
        )

    def test_tagged_or_empty_image_reference_is_rejected(self) -> None:
        for image in (
            "",
            "ghcr.io/appolon1908-hue/integration-control-plane:latest",
            "ghcr.io/appolon1908-hue/integration-control-plane:v1",
            "not-a-registry",
        ):
            with self.subTest(image=image):
                manifest = self.manifest()
                manifest["candidate"]["components"][0]["image"] = image
                errors = self.validate(manifest)
                self.assertTrue(
                    any("lowercase untagged registry repository" in error for error in errors)
                )

    def test_rollback_cannot_change_repository_or_image_authority(self) -> None:
        manifest = self.manifest()
        manifest["previous_candidate"]["components"][0][
            "repository"
        ] = "attacker/example"
        manifest["previous_candidate"]["components"][0][
            "image"
        ] = "ghcr.io/attacker/example"
        errors = self.validate(manifest)
        self.assertTrue(any(".repository must match candidate" in error for error in errors))
        self.assertTrue(any(".image must match candidate" in error for error in errors))

    def test_rollback_candidate_must_be_distinct(self) -> None:
        manifest = self.manifest()
        manifest["previous_candidate"]["release_id"] = manifest["candidate"]["release_id"]
        manifest["previous_candidate"]["components"] = json.loads(
            json.dumps(manifest["candidate"]["components"])
        )
        errors = self.validate(manifest)
        self.assertIn(
            "previous_candidate.release_id must differ from candidate.release_id",
            errors,
        )
        self.assertIn(
            "previous_candidate must differ by at least one source SHA or image digest",
            errors,
        )

    def test_off_host_backup_uri_must_match_protected_environment(self) -> None:
        manifest = self.manifest()
        manifest["backups"]["off_host_uri"] = "s3://other-bucket/candidate"
        errors = self.validate(manifest)
        self.assertIn(
            "backups.off_host_uri does not match the protected environment variable",
            errors,
        )

    def test_embedded_credentials_are_rejected_without_echoing_values(self) -> None:
        manifest = self.manifest()
        manifest["credentials"] = {
            "token": "Bearer very-secret-value",
            "private_key": "-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----",
        }
        errors = self.validate(manifest)
        rendered = "\n".join(errors)
        self.assertIn("must not embed credential material", rendered)
        self.assertIn("must not embed a bearer credential", rendered)
        self.assertIn("must not embed a private key", rendered)
        self.assertNotIn("very-secret-value", rendered)
        self.assertNotIn("BEGIN PRIVATE KEY", rendered)

    def test_workflow_scopes_manifest_secret_to_materialization_step(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        job = workflow.split("\n  environment-preflight:\n", 1)[1]
        before_steps, steps = job.split("\n    steps:\n", 1)
        secret_binding = (
            "STAGING_ENDPOINT_MANIFEST_JSON: "
            "${{ secrets.CODESTRA_STAGING_READONLY_ENDPOINT_MANIFEST }}"
        )
        self.assertNotIn(secret_binding, before_steps)
        self.assertEqual(steps.count(secret_binding), 1)
        self.assertIn(
            "- name: Materialize protected endpoint manifest\n"
            "        env:\n"
            "          " + secret_binding,
            steps,
        )


if __name__ == "__main__":
    unittest.main()
