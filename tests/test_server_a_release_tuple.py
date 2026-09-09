import json
from pathlib import Path


def test_release_tuple_has_distinct_authorities_and_fails_closed() -> None:
    manifest = json.loads(
        Path("config/server-a-production-release-manifest.json.example").read_text()
    )
    assert manifest["orchestration"]["repository"] == (
        "appolon1908-hue/codestra-production-platform"
    )
    assert manifest["middleware"]["repository"] == "appolon1908-hue/Middleware-"
    assert manifest["middleware"]["production_signature_verified"] is False
    assert manifest["middleware"]["production_provenance_verified"] is False
    assert all(value is False for value in manifest["required_false_flags"].values())


def test_staging_only_digest_is_not_production_manifest_authority() -> None:
    manifest = Path(
        "config/server-a-production-release-manifest.json.example"
    ).read_text()
    staging_digest = (
        "2e15399387967c02d78cc56565157412f0cc2cb9ad6393695d17c39a88cdd2ff"
    )
    assert staging_digest not in manifest


def test_protected_release_gate_requires_current_signed_middleware_tuple() -> None:
    workflow = Path(".github/workflows/protected-release.yml").read_text()
    builder = Path("tools/build_release_bundle.py").read_text()

    # The run and artifact names come from the committed, exact release tuple.
    for name in (
        "CODESTRA_MIDDLEWARE_RELEASE_READ_TOKEN",
        "config/production-release-tuple.json",
        "MIDDLEWARE_RELEASE_RUN_ID",
        "MIDDLEWARE_RELEASE_ARTIFACT",
        "EXPECTED_ARTIFACT_DIGEST",
    ):
        assert name in workflow

    # The current signed bundle is verified before any platform release is built.
    assert "tools/verify_middleware_release_evidence.py" in workflow
    for argument in (
        "--tuple config/production-release-tuple.json",
        '--run-id "${MIDDLEWARE_RELEASE_RUN_ID}"',
        '--artifact "${MIDDLEWARE_RELEASE_ARTIFACT}"',
        '--artifact-digest "${artifact_digest}"',
        '--cosign "${RUNNER_TEMP}/cosign"',
        "--derived-provenance-output middleware-derived-provenance.json",
        "--derived-openvex-output middleware-derived-openvex.json",
    ):
        assert argument in workflow

    # Image signature, provenance, SBOM, source label and exact migration head are enforced.
    assert '"${RUNNER_TEMP}/cosign" verify' in workflow
    assert "verify-attestation --type slsaprovenance1" in workflow
    assert "verify-attestation --type spdxjson" in workflow
    assert workflow.count("--certificate-identity") == 3
    assert workflow.count("--certificate-oidc-issuer") == 3
    assert "tools/verify_signed_release_attestations.py" in workflow
    for argument in (
        "--manifest middleware-release/release-manifest.v1.json",
        "--sbom middleware-release/middleware.spdx.json",
        "--provenance-verification middleware-provenance-verification.json",
        "--sbom-verification middleware-sbom-verification.json",
        '--expected-source "$MIDDLEWARE_PROTECTED_SHA"',
        '--expected-digest "$MIDDLEWARE_IMAGE_DIGEST"',
    ):
        assert argument in workflow
    assert "docker image inspect" in workflow
    assert "org.opencontainers.image.revision" in workflow
    assert "tools/detect_alembic_head.py" in workflow
    assert "/app/migrations/versions" in workflow
    assert 'test "${#migration_heads[@]}" -eq 1' in workflow
    assert "EXPECTED_MIGRATION_REVISION: 0057_platform_service_catalog" in workflow
    assert 'test "$MIDDLEWARE_MIGRATION_REVISION" = "$EXPECTED_MIGRATION_REVISION"' in workflow
    assert 'test "${migration_heads[0]}" = "$EXPECTED_MIGRATION_REVISION"' in workflow
    assert 'test "${migration_heads[0]}" = "$MIDDLEWARE_MIGRATION_REVISION"' in workflow
    assert "MIDDLEWARE_MIGRATION_REVISION=%s" in workflow

    # The protected release retains the exact files present in the canonical signed v1
    # evidence bundle plus deterministic verification of those inputs.
    for retained_evidence in (
        "dist/middleware-signature-verification.json",
        "dist/middleware-provenance-verification.json",
        "dist/middleware-sbom-verification.json",
        "dist/middleware-release-manifest.v1.json",
        "dist/middleware-release-manifest.v1.sigstore.json",
        "dist/middleware.spdx.json",
        "dist/middleware.grype.json",
        "dist/middleware-derived-provenance.json",
        "dist/middleware-derived-openvex.json",
    ):
        assert retained_evidence in workflow

    # Workflow actions are immutable, and production release construction remains fail closed.
    assert "actions/checkout@v4" not in workflow
    assert "actions/setup-python@v5" not in workflow
    assert "actions/upload-artifact@v4" not in workflow
    assert "staging-only middleware digest is prohibited" in builder
    assert '"release_tuple"' in builder
