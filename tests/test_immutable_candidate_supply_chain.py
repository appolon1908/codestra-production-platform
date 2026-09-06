from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "immutable-candidate-build.yml"


class ImmutableCandidateSupplyChainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_workflow_is_regular_source(self) -> None:
        self.assertTrue(WORKFLOW.is_file())
        self.assertFalse(WORKFLOW.is_symlink())

    def test_protected_release_is_only_push_publication_branch(self) -> None:
        self.assertIn("push:\n    branches: [release/production-activation]", self.text)
        self.assertNotIn("pull_request_target:", self.text)

    def test_least_privilege_signing_permissions(self) -> None:
        self.assertIn("contents: read", self.text)
        self.assertIn("packages: write", self.text)
        self.assertIn("id-token: write", self.text)
        self.assertNotIn("contents: write", self.text)

    def test_every_release_action_is_pinned(self) -> None:
        for action in (
            "actions/checkout@11d5960a326750d5838078e36cf38b85af677262",
            "docker/setup-buildx-action@8d2750c68a42422c14e847fe6c8ac0403b4cbd6f",
            "docker/build-push-action@10e90e3645eae34f1e60eeb005ba3a3d33f178e8",
            "docker/login-action@c94ce9fb468520275223c153574b00df6fe4bcc9",
            "aquasecurity/trivy-action@ed142fd0673e97e23eac54620cfb913e5ce36c25",
            "sigstore/cosign-installer@6f9f17788090df1f26f669e9d70d6ae9567deba6",
            "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
        ):
            self.assertIn(action, self.text)

    def test_publication_uses_exact_source_tag_and_digest_subject(self) -> None:
        self.assertIn("ghcr.io/${{ github.repository_owner }}/${{ matrix.component }}:${{ github.sha }}", self.text)
        self.assertIn('image="${image_repository}@${DIGEST}"', self.text)
        self.assertNotIn(":latest", self.text)

    def test_local_scan_precedes_registry_publication(self) -> None:
        scan = self.text.index("Reject fixable HIGH or CRITICAL findings before publication")
        publish = self.text.index("Publish exact-source image with SBOM and provenance")
        self.assertLess(scan, publish)
        self.assertIn("ignore-unfixed: true", self.text)
        self.assertIn("exit-code: '1'", self.text)

    def test_build_emits_sbom_and_provenance(self) -> None:
        self.assertIn("provenance: mode=max", self.text)
        self.assertIn("sbom: true", self.text)
        self.assertIn("imagetools inspect \"$image\" --format '{{ json .SBOM }}'", self.text)
        self.assertIn("imagetools inspect \"$image\" --format '{{ json .Provenance }}'", self.text)

    def test_digest_is_keyless_signed_and_verified(self) -> None:
        self.assertIn("cosign sign --yes \"$image\"", self.text)
        self.assertIn("--certificate-identity \"$workflow_identity\"", self.text)
        self.assertIn("--certificate-oidc-issuer \"$issuer\"", self.text)
        self.assertIn("https://token.actions.githubusercontent.com", self.text)

    def test_oci_source_revision_and_version_are_read_back(self) -> None:
        self.assertIn('.["org.opencontainers.image.source"] == $source', self.text)
        self.assertIn('.["org.opencontainers.image.revision"] == $sha', self.text)
        self.assertIn('.["org.opencontainers.image.version"] == $sha', self.text)

    def test_evidence_is_checksum_bound_and_retained(self) -> None:
        self.assertIn("sha256sum --check --strict SHA256SUMS", self.text)
        self.assertIn("signature-verification.json", self.text)
        self.assertIn("candidate.json", self.text)
        self.assertIn("retention-days: 90", self.text)
        self.assertIn("if-no-files-found: error", self.text)

    def test_candidate_remains_uncertified_and_undeployed(self) -> None:
        self.assertIn('"deployment_authorized": False', self.text)
        self.assertIn('"production_certified": False', self.text)
        self.assertIn("DEPLOYMENT_AUTHORIZED=NO", self.text)
        self.assertIn("PRODUCTION_CERTIFIED=NO", self.text)

    def test_no_direct_runtime_deployment_capability(self) -> None:
        forbidden = (
            "docker compose up",
            "docker-compose up",
            "ssh ",
            "tofu apply",
            "terraform apply",
            "kubectl apply",
            "enable-production-web-traffic",
        )
        lower = self.text.lower()
        for fragment in forbidden:
            self.assertNotIn(fragment, lower)

    def test_exact_four_component_matrix(self) -> None:
        components = re.findall(r"^          - component: ([a-z0-9-]+)$", self.text, re.MULTILINE)
        self.assertEqual(
            components,
            ["integration-control-plane", "email-reseller", "mail-api", "reseller-portal"],
        )


if __name__ == "__main__":
    unittest.main()
