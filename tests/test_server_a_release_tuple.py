import json
from pathlib import Path


def test_release_tuple_has_distinct_authorities_and_fails_closed() -> None:
    manifest = json.loads(
        Path("config/server-a-production-release-manifest.json.example").read_text()
    )
    assert manifest["orchestration"]["repository"] == (
        "appolon1908-hue/codestra-production-platform"
    )
    assert manifest["middleware"]["repository"] == (
        "Codestra-SRL/codestra-middleware"
    )
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


def test_protected_release_gate_requires_completed_middleware_tuple() -> None:
    workflow = Path(".github/workflows/protected-release.yml").read_text()
    builder = Path("tools/build_release_bundle.py").read_text()
    for name in (
        "CODESTRA_MIDDLEWARE_RELEASE_READ_TOKEN",
        "CODESTRA_MIDDLEWARE_PRODUCTION_RELEASE_RUN_ID",
        "CODESTRA_MIDDLEWARE_PRODUCTION_RELEASE_ARTIFACT",
    ):
        assert name in workflow
    assert "cosign\" verify" in workflow
    assert "verify-attestation --type slsaprovenance1" in workflow
    assert "alembic heads" in workflow
    assert 'test "${#migration_heads[@]}" -eq 1' in workflow
    assert 'migration_revision="${migration_heads[0]}"' in workflow
    assert "dist/middleware-signature-verification.json" in workflow
    assert "dist/middleware-provenance-verification.json" in workflow
    assert "dist/middleware-sbom-verification.json" in workflow
    assert "dist/middleware-sbom.cdx.json" in workflow
    assert "verify_attestation_predicate.py" in workflow
    assert "actions/checkout@v4" not in workflow
    assert "actions/setup-python@v5" not in workflow
    assert "actions/upload-artifact@v4" not in workflow
    assert "staging-only middleware digest is prohibited" in builder
    assert '"release_tuple"' in builder
