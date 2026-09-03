import json
from pathlib import Path


def test_release_tuple_has_distinct_authorities_and_fails_closed() -> None:
    manifest = json.loads(
        Path("config/server-a-production-release-manifest.json.example").read_text()
    )
    assert manifest["orchestration"]["repository"] == (
        "appolon1908-hue/codestra-production-platform"
    )
    middleware = manifest["middleware"]
    assert middleware["repository"] == "appolon1908-hue/Middleware-"
    assert middleware["protected_merge_sha"] == "1aa4d505846b7494aff94bec3d7ea68c895e2dd3"
    assert middleware["source_tree"] == "f67ed2eb19afc67dbe51624b5ba6298ec5dc5e32"
    assert middleware["image"] == "ghcr.io/appolon1908-hue/codestra-middleware"
    assert middleware["image_digest"] == "sha256:cec8b5a1b0e713857be1dbc94b73780bf9ae1a200d0901f95cb62193b9c2f504"
    assert middleware["migration_head"] == "0009_observability_incidents"
    assert middleware["image_signature_verified"] is False
    assert middleware["image_provenance_verified"] is False
    assert middleware["sbom_attestation_verified"] is False
    assert middleware["release_manifest_signature_verified"] is False
    assert middleware["production_deployment_authorized"] is False
    assert all(value is False for value in manifest["required_false_flags"].values())


def test_staging_only_and_superseded_digests_are_not_selected() -> None:
    manifest = Path("config/server-a-production-release-manifest.json.example").read_text()
    assert "2e15399387967c02d78cc56565157412f0cc2cb9ad6393695d17c39a88cdd2ff" not in manifest
    assert "ec2cf4ca73ff072fbdd48bda108a60f103526cb3e97a721abdf38435b010908b" not in manifest


def test_protected_release_gate_requires_exact_appolon_evidence() -> None:
    workflow = Path(".github/workflows/protected-release.yml").read_text()
    builder = Path("tools/build_release_bundle.py").read_text()
    for name in (
        "CODESTRA_MIDDLEWARE_RELEASE_READ_TOKEN",
        "MIDDLEWARE_RELEASE_ARTIFACT_ID",
        "MIDDLEWARE_ARTIFACT_ZIP_SHA256",
        "MIDDLEWARE_WORKFLOW_IDENTITY",
        "MIDDLEWARE_OIDC_ISSUER",
    ):
        assert name in workflow
    assert "actions/artifacts/${MIDDLEWARE_RELEASE_ARTIFACT_ID}/zip" in workflow
    assert "tools/verify_middleware_release_evidence.py" in workflow
    assert "cosign\" verify" in workflow
    assert "verify-attestation" in workflow
    assert "--type slsaprovenance1" in workflow
    assert "--type spdxjson" in workflow
    assert "verify-blob" in workflow
    assert "alembic heads" in workflow
    assert 'test "${#migration_heads[@]}" -eq 1' in workflow
    assert "org.opencontainers.image.revision" in workflow
    assert "org.opencontainers.image.source" in workflow
    for retained_evidence in (
        "dist/middleware-release-manifest.v1.json",
        "dist/middleware-release-manifest.v1.sigstore.json",
        "dist/middleware.spdx.json",
        "dist/middleware.grype.json",
    ):
        assert retained_evidence in workflow
    assert "ghcr.io/appolon1908-hue/codestra-middleware" in builder
    assert "Codestra-SRL/codestra-middleware" not in builder
    assert "production_deployment_authorized" in builder
    assert '"release_tuple"' in builder
    assert "actions/checkout@v4" not in workflow
    assert "actions/setup-python@v5" not in workflow
    assert "actions/upload-artifact@v4" not in workflow
