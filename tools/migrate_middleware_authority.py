#!/usr/bin/env python3
"""Bind the exact signed Appolon Middleware release into platform authority.

This is repository-only. It validates the real v1 signed-release artifact,
derives deterministic provenance and OpenVEX evidence, updates the protected
release tuple and active source authorities, and preserves the former
Codestra-SRL tuple solely as rollback history. It never contacts a runtime.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
from signed_middleware_release import canonical_json, validate_signed_release  # noqa: E402

OLD_REPOSITORY = "Codestra-SRL/codestra-middleware"
NEW_REPOSITORY = "appolon1908-hue/Middleware-"
OLD_IMAGE = "ghcr.io/codestra-srl/codestra-middleware"
NEW_IMAGE = "ghcr.io/appolon1908-hue/codestra-middleware"
OLD_WORKFLOW = ".github/workflows/exact-main-production-release.yml"
NEW_WORKFLOW = ".github/workflows/release.yml"
NEW_BUILDER = (
    "https://github.com/appolon1908-hue/Middleware-/"
    ".github/workflows/release.yml@refs/heads/main"
)
EXPECTED_SOURCE_SHA = "1aa4d505846b7494aff94bec3d7ea68c895e2dd3"
EXPECTED_IMAGE_DIGEST = (
    "sha256:cec8b5a1b0e713857be1dbc94b73780bf9ae1a200d0901f95cb62193b9c2f504"
)
EXPECTED_MIGRATION_HEAD = "0009_observability_incidents"
EXPECTED_RELEASE_RUN = "33767657962"
EXPECTED_ARTIFACT_DIGEST = (
    "sha256:cfd5ef83132da1683c0c053e7025739aa4c2747344aa7fc1feed48bf838a566a"
)
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class MigrationError(RuntimeError):
    """Raised when an authority migration cannot be proven safe."""


def replace_active_authority(path: Path, builder: str) -> bool:
    text = path.read_text(encoding="utf-8")
    changed = text.replace(OLD_REPOSITORY, NEW_REPOSITORY)
    changed = changed.replace(OLD_IMAGE, NEW_IMAGE)
    changed = changed.replace(OLD_WORKFLOW, NEW_WORKFLOW)
    old_builder = (
        f"https://github.com/{OLD_REPOSITORY}/{OLD_WORKFLOW}@refs/heads/main"
    )
    changed = changed.replace(old_builder, builder)
    if changed == text:
        return False
    path.write_text(changed, encoding="utf-8")
    return True


def swap_authority_strings(text: str) -> str:
    placeholders = {
        "__OLD_REPOSITORY__": OLD_REPOSITORY,
        "__OLD_IMAGE__": OLD_IMAGE,
        "__OLD_WORKFLOW__": OLD_WORKFLOW,
    }
    changed = text
    for placeholder, value in placeholders.items():
        changed = changed.replace(value, placeholder)
    changed = changed.replace(NEW_REPOSITORY, OLD_REPOSITORY)
    changed = changed.replace(NEW_IMAGE, OLD_IMAGE)
    changed = changed.replace(NEW_WORKFLOW, OLD_WORKFLOW)
    changed = changed.replace("__OLD_REPOSITORY__", NEW_REPOSITORY)
    changed = changed.replace("__OLD_IMAGE__", NEW_IMAGE)
    changed = changed.replace("__OLD_WORKFLOW__", NEW_WORKFLOW)
    return changed


def _require_mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise MigrationError(f"{label} must be a mapping")
    return value


def migrate_source_lock(path: Path, release: dict[str, object]) -> None:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise MigrationError("Production source lock cannot be loaded") from exc
    root = _require_mapping(value, "Production source lock")
    authorities = _require_mapping(root.get("middleware_authorities"), "middleware authorities")
    current = _require_mapping(
        authorities.get("protected_production_tuple"), "protected production tuple"
    )
    candidate = _require_mapping(
        authorities.get("appolon_n8n_gap_candidate"), "Appolon candidate"
    )
    if current.get("repository") != OLD_REPOSITORY:
        raise MigrationError("former protected Middleware authority is unexpected")
    if candidate.get("repository") != NEW_REPOSITORY:
        raise MigrationError("Appolon candidate authority is unexpected")
    if candidate.get("source_sha") != release["source_sha"]:
        raise MigrationError("source-lock Appolon source SHA differs from signed release")
    if candidate.get("image_digest") != release["image_digest"]:
        raise MigrationError("source-lock Appolon image digest differs from signed release")
    if candidate.get("migration_head") != release["migration_head"]:
        raise MigrationError("source-lock Appolon migration head differs from signed release")
    if candidate.get("release_artifact_digest") != release["artifact_digest"]:
        raise MigrationError("source-lock artifact digest differs from signed release")

    former = dict(current)
    former.update(
        {
            "authority_state": "FORMER_PRODUCTION_AUTHORITY_RETAINED_FOR_ROLLBACK_ONLY",
            "runtime_state": "NOT_SELECTED_FOR_NEW_DEPLOYMENT",
            "deployment_authorized": False,
        }
    )
    protected = dict(candidate)
    protected.update(
        {
            "authority_state": "CANONICAL_SOURCE_AUTHORITY_PENDING_STAGING_CERTIFICATION",
            "authority_classification": "CANONICAL_SIGNED_SOURCE_AUTHORITY",
            "promotion_decision": "STAGING_RESTORE_ROLLBACK_AND_READONLY_CANARY_REQUIRED",
            "runtime_state": "SIGNED_IMMUTABLE_CANDIDATE_NOT_DEPLOYED",
            "external_effects_default": "DISABLED",
            "deployment_authorized": False,
        }
    )
    authorities["protected_production_tuple"] = protected
    authorities.pop("appolon_n8n_gap_candidate", None)
    authorities["former_codestra_srl_authority"] = former
    decision = _require_mapping(authorities.get("authority_decision"), "authority decision")
    decision.update(
        {
            "status": "RESOLVED_TO_APPOLON_SIGNED_AUTHORITY_PENDING_STAGING_CERTIFICATION",
            "preferred_path": "CERTIFY_EXACT_APPOLON_DIGEST_IN_PROTECTED_STAGING",
            "alternate_path": "ROLL_BACK_TO_RECORDED_CODESTRA_SRL_AUTHORITY_ON_ANY_GATE_FAILURE",
            "prohibited_path": "DEPLOY_WITHOUT_EXACT_DIGEST_BACKUP_RESTORE_AND_ROLLBACK_EVIDENCE",
            "reason": (
                "The exact Appolon release manifest, Sigstore identity, SPDX SBOM, "
                "Grype result, source SHA, image digest, and migration head are now "
                "bound as source authority. Runtime deployment remains unauthorized "
                "until protected staging, restore, rollback, and canary evidence pass."
            ),
        }
    )

    blockers = root.get("blockers")
    if not isinstance(blockers, list):
        raise MigrationError("Production source-lock blockers must be a list")
    root["blockers"] = [
        item
        for item in blockers
        if not (
            isinstance(item, dict)
            and item.get("id")
            in {"middleware-authority-split", "canonical-middleware-actions-budget"}
        )
    ]
    root["generated_at"] = "2026-09-03T17:00:00Z"
    root["status"] = "FAIL"
    path.write_text(
        yaml.safe_dump(root, sort_keys=False, width=1000, allow_unicode=False),
        encoding="utf-8",
    )


def write_derived_evidence(root: Path, release: dict[str, object]) -> dict[str, str]:
    evidence_dir = root / "evidence" / "middleware-authority"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    suffix = str(release["source_sha"])
    provenance_path = evidence_dir / f"appolon-middleware-provenance-{suffix}.json"
    openvex_path = evidence_dir / f"appolon-middleware-openvex-{suffix}.json"
    binding_path = evidence_dir / f"appolon-middleware-binding-{suffix}.json"
    provenance_path.write_bytes(canonical_json(release["provenance"]))
    openvex_path.write_bytes(canonical_json(release["openvex"]))
    binding = {
        "schema_version": "codestra.middleware-authority-binding.v1",
        "repository": NEW_REPOSITORY,
        "source_sha": release["source_sha"],
        "git_tree_id": release["git_tree_id"],
        "image_reference": release["image_reference"],
        "image_digest": release["image_digest"],
        "migration_head": release["migration_head"],
        "release_id": release["release_id"],
        "release_run_id": release["run_id"],
        "release_artifact": release["artifact"],
        "release_artifact_digest": release["artifact_digest"],
        "release_manifest_sha256": release["release_manifest_sha256"],
        "sigstore_bundle_sha256": release["sigstore_bundle_sha256"],
        "sbom_sha256": release["sbom_sha256"],
        "vulnerability_report_sha256": release["vulnerability_report_sha256"],
        "derived_provenance_sha256": release["provenance_sha256"],
        "derived_openvex_sha256": release["openvex_sha256"],
        "builder": release["builder"],
        "external_effects_default": "DISABLED",
        "deployment_authorized": False,
        "production_changed": False,
    }
    binding_path.write_bytes(canonical_json(binding))
    return {
        "provenance_path": provenance_path.relative_to(root).as_posix(),
        "openvex_path": openvex_path.relative_to(root).as_posix(),
        "binding_path": binding_path.relative_to(root).as_posix(),
    }


def write_decision_record(
    root: Path,
    *,
    release: dict[str, object],
    evidence_paths: dict[str, str],
) -> None:
    path = root / "docs" / "APPOLON_MIDDLEWARE_PRODUCTION_AUTHORITY_MIGRATION_20260903.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""# Appolon Middleware production authority migration — 2026-09-03

## Decision

Select `{NEW_REPOSITORY}` as the canonical Middleware **source authority** for the next protected release. Retain `{OLD_REPOSITORY}` only as the exact former rollback authority. Runtime deployment is still prohibited until protected staging, backup/restore, rollback rehearsal, and read-only canary gates pass.

## Exact signed candidate

- Source: `{NEW_REPOSITORY}@{release['source_sha']}`
- Git tree: `{release['git_tree_id']}`
- Image: `{release['image_reference']}`
- Migration head: `{release['migration_head']}`
- Signed release run: `{release['run_id']}`
- Signed evidence artifact: `{release['artifact']}`
- Artifact digest: `{release['artifact_digest']}`
- Provenance builder: `{release['builder']}`
- Release manifest SHA-256: `{release['release_manifest_sha256']}`
- Sigstore bundle SHA-256: `{release['sigstore_bundle_sha256']}`
- SPDX SBOM SHA-256: `{release['sbom_sha256']}`
- Grype report SHA-256: `{release['vulnerability_report_sha256']}`
- Grype vulnerability matches: `0`
- Derived provenance SHA-256: `{release['provenance_sha256']}`
- Derived OpenVEX SHA-256: `{release['openvex_sha256']}`

The upstream artifact contains the canonical signed release manifest, Sigstore bundle, SPDX SBOM, and Grype report. It does **not** contain the legacy `RELEASE.env`, CycloneDX SBOM, standalone provenance JSON, or upstream OpenVEX files. The platform derives deterministic provenance and an empty-statement OpenVEX document from the signed manifest and zero-match Grype report; it does not mislabel unrelated files.

## Durable repository evidence

- Binding: `{evidence_paths['binding_path']}`
- Derived provenance: `{evidence_paths['provenance_path']}`
- Derived OpenVEX: `{evidence_paths['openvex_path']}`

## Safety boundary

This migration changes repository source authority and release verification only. It does not deploy a container, run a database migration, alter SSH, route production traffic, enable business writes, or enable any provider effect. `PRODUCTION-SOURCE-LOCK.yaml` remains `FAIL` until the remaining runtime and staging blockers are closed.
""",
        encoding="utf-8",
    )


def migrate(
    root: Path,
    evidence: Path,
    artifact: str,
    artifact_digest: str,
    run_id: str,
    cosign: str,
) -> dict[str, object]:
    if run_id != EXPECTED_RELEASE_RUN:
        raise MigrationError("Middleware release run is not the reviewed run")
    if artifact_digest != EXPECTED_ARTIFACT_DIGEST:
        raise MigrationError("Middleware artifact digest is not the reviewed digest")
    release = validate_signed_release(
        evidence,
        expected_repository=NEW_REPOSITORY,
        expected_image_repository=NEW_IMAGE,
        expected_workflow_identity=NEW_BUILDER,
        expected_source_sha=EXPECTED_SOURCE_SHA,
        expected_image_digest=EXPECTED_IMAGE_DIGEST,
        expected_run_id=run_id,
        artifact_name=artifact,
        artifact_digest=artifact_digest,
        cosign=cosign,
        verify_signature=True,
    )
    if release["migration_head"] != EXPECTED_MIGRATION_HEAD:
        raise MigrationError("Middleware migration head differs from reviewed candidate")

    tuple_path = root / "config" / "production-release-tuple.json"
    authority = json.loads(tuple_path.read_text(encoding="utf-8"))
    required_fields = {
        "change_id",
        "middleware_artifact",
        "middleware_digest",
        "middleware_openvex_sha256",
        "middleware_provenance_sha256",
        "middleware_run_id",
        "middleware_sbom_sha256",
        "middleware_source_sha",
        "release_version",
    }
    if set(authority) != required_fields:
        raise MigrationError("Protected release tuple fields are not exact")
    old_sha = authority["middleware_source_sha"]
    old_digest = authority["middleware_digest"]
    if not isinstance(old_sha, str) or SHA_RE.fullmatch(old_sha) is None:
        raise MigrationError("Former Middleware source SHA is invalid")
    if not isinstance(old_digest, str) or DIGEST_RE.fullmatch(old_digest) is None:
        raise MigrationError("Former Middleware digest is invalid")
    authority.update(
        {
            "middleware_artifact": artifact,
            "middleware_digest": release["image_digest"],
            "middleware_openvex_sha256": release["openvex_sha256"],
            "middleware_provenance_sha256": release["provenance_sha256"],
            "middleware_run_id": run_id,
            "middleware_sbom_sha256": release["sbom_sha256"],
            "middleware_source_sha": release["source_sha"],
        }
    )
    tuple_path.write_text(
        json.dumps(authority, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    active_paths = [
        ".github/workflows/protected-release.yml",
        "tools/verify_middleware_release_evidence.py",
        "tools/verify_slsa_provenance_attestation.py",
        "tools/build_release_bundle.py",
        "tools/verify_jetstream_worker_image.py",
        "config/jetstream-dlq-worker.env.example",
    ]
    missing = [relative for relative in active_paths if not (root / relative).is_file()]
    if missing:
        raise MigrationError(f"Active production authority files are missing: {missing}")
    for relative in active_paths:
        replace_active_authority(root / relative, str(release["builder"]))

    migrate_source_lock(root / "PRODUCTION-SOURCE-LOCK.yaml", release)

    for path in (root / "tests").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        changed = swap_authority_strings(text)
        old_builder = (
            f"https://github.com/{OLD_REPOSITORY}/{OLD_WORKFLOW}@refs/heads/main"
        )
        changed = changed.replace(old_builder, str(release["builder"]))
        if changed != text:
            path.write_text(changed, encoding="utf-8")

    evidence_paths = write_derived_evidence(root, release)
    write_decision_record(root, release=release, evidence_paths=evidence_paths)
    return {
        **{
            key: value
            for key, value in release.items()
            if key not in {"provenance", "openvex"}
        },
        **evidence_paths,
        "former_source_sha": old_sha,
        "former_image_digest": old_digest,
        "production_changed": False,
        "deployment_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--artifact-digest", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--cosign", default="cosign")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = migrate(
            args.root.resolve(),
            args.evidence.resolve(),
            args.artifact,
            args.artifact_digest,
            args.run_id,
            args.cosign,
        )
    except (MigrationError, OSError, ValueError) as exc:
        print(f"MIDDLEWARE_AUTHORITY_MIGRATION=BLOCKED: {exc}", file=sys.stderr)
        return 1
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
