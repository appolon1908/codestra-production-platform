#!/usr/bin/env python3
"""Bind an exact signed Middleware release into the production authority.

This utility is intentionally repository-only. It updates active release authority,
source-lock identity slots, tests, and a decision record. It never deploys or
contacts a production runtime.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import yaml

OLD_REPOSITORY = "Codestra-SRL/codestra-middleware"
NEW_REPOSITORY = "appolon1908-hue/Middleware-"
OLD_IMAGE = "ghcr.io/codestra-srl/codestra-middleware"
NEW_IMAGE = "ghcr.io/appolon1908-hue/codestra-middleware"
OLD_WORKFLOW = ".github/workflows/exact-main-production-release.yml"
NEW_WORKFLOW = ".github/workflows/release.yml"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class MigrationError(RuntimeError):
    """Raised when an authority migration cannot be proven safe."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_release_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        key, separator, value = line.partition("=")
        if not separator or not key or key in values:
            raise MigrationError("Middleware RELEASE.env is malformed")
        values[key] = value
    required = {"SOURCE_SHA", "IMAGE_REFERENCE", "IMAGE_DIGEST", "SBOM_SHA256"}
    if set(values) != required:
        raise MigrationError("Middleware RELEASE.env fields are not exact")
    if not SHA_RE.fullmatch(values["SOURCE_SHA"]):
        raise MigrationError("Middleware source SHA is invalid")
    if not DIGEST_RE.fullmatch(values["IMAGE_DIGEST"]):
        raise MigrationError("Middleware image digest is invalid")
    expected_reference = f'{NEW_IMAGE}@{values["IMAGE_DIGEST"]}'
    if values["IMAGE_REFERENCE"] != expected_reference:
        raise MigrationError("Middleware image authority is not Appolon exact-digest authority")
    if values["SBOM_SHA256"] != sha256(path.parent / "sbom.cdx.json"):
        raise MigrationError("Middleware SBOM hash differs from RELEASE.env")
    return values


def provenance_builder(provenance: dict[str, Any]) -> str:
    direct = provenance.get("runDetails", {}).get("builder", {}).get("id")
    predicate = (
        provenance.get("predicate", {})
        .get("runDetails", {})
        .get("builder", {})
        .get("id")
    )
    builder = direct or predicate
    if not isinstance(builder, str):
        raise MigrationError("Middleware provenance builder is missing")
    expected = (
        f"https://github.com/{NEW_REPOSITORY}/{NEW_WORKFLOW}"
        "@refs/heads/main"
    )
    if builder != expected:
        raise MigrationError(
            f"Middleware provenance builder is unauthorized: {builder!r}"
        )
    return builder


def replace_active_authority(path: Path, builder: str) -> bool:
    text = path.read_text()
    changed = text.replace(OLD_REPOSITORY, NEW_REPOSITORY)
    changed = changed.replace(OLD_IMAGE, NEW_IMAGE)
    changed = changed.replace(OLD_WORKFLOW, NEW_WORKFLOW)
    old_builder = (
        f"https://github.com/{OLD_REPOSITORY}/{OLD_WORKFLOW}@refs/heads/main"
    )
    changed = changed.replace(old_builder, builder)
    if changed == text:
        return False
    path.write_text(changed)
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


def scalar_token(original: str, value: str) -> str:
    stripped = original.strip()
    if stripped.startswith('"') and stripped.endswith('"'):
        return json.dumps(value)
    if stripped.startswith("'") and stripped.endswith("'"):
        return "'" + value.replace("'", "''") + "'"
    return value


def direct_repository(mapping: yaml.MappingNode) -> str | None:
    for key_node, value_node in mapping.value:
        if not isinstance(key_node, yaml.ScalarNode):
            continue
        if key_node.value.lower() not in {
            "repository",
            "repo",
            "source_repository",
            "github_repository",
        }:
            continue
        if isinstance(value_node, yaml.ScalarNode):
            if value_node.value in {OLD_REPOSITORY, NEW_REPOSITORY}:
                return value_node.value
    return None


def collect_mappings(node: yaml.Node, matches: list[yaml.MappingNode]) -> None:
    if isinstance(node, yaml.MappingNode):
        if direct_repository(node) is not None:
            matches.append(node)
        for key_node, value_node in node.value:
            collect_mappings(key_node, matches)
            collect_mappings(value_node, matches)
    elif isinstance(node, yaml.SequenceNode):
        for child in node.value:
            collect_mappings(child, matches)


def replacement_for_scalar(
    key_hint: str,
    value: str,
    *,
    to_new: bool,
    old_sha: str,
    old_digest: str,
    new_sha: str,
    new_digest: str,
    builder: str,
) -> str:
    if to_new:
        changed = value.replace(OLD_REPOSITORY, NEW_REPOSITORY)
        changed = changed.replace(OLD_IMAGE, NEW_IMAGE)
        changed = changed.replace(OLD_WORKFLOW, NEW_WORKFLOW)
        changed = changed.replace(old_sha, new_sha).replace(old_digest, new_digest)
        if "builder" in key_hint and OLD_REPOSITORY.lower() in value.lower():
            changed = builder
        if any(
            token in key_hint
            for token in ("source_sha", "protected_sha", "git_sha", "commit_sha")
        ) and SHA_RE.fullmatch(changed):
            changed = new_sha
        if "digest" in key_hint and DIGEST_RE.fullmatch(changed):
            changed = new_digest
        return changed

    changed = value.replace(NEW_REPOSITORY, OLD_REPOSITORY)
    changed = changed.replace(NEW_IMAGE, OLD_IMAGE)
    changed = changed.replace(NEW_WORKFLOW, OLD_WORKFLOW)
    changed = changed.replace(new_sha, old_sha).replace(new_digest, old_digest)
    if "builder" in key_hint and NEW_REPOSITORY.lower() in value.lower():
        changed = (
            f"https://github.com/{OLD_REPOSITORY}/{OLD_WORKFLOW}"
            "@refs/heads/main"
        )
    if any(
        token in key_hint
        for token in ("source_sha", "protected_sha", "git_sha", "commit_sha")
    ) and SHA_RE.fullmatch(changed):
        changed = old_sha
    if "digest" in key_hint and DIGEST_RE.fullmatch(changed):
        changed = old_digest
    return changed


def mapping_edits(
    mapping: yaml.MappingNode,
    source: str,
    *,
    to_new: bool,
    old_sha: str,
    old_digest: str,
    new_sha: str,
    new_digest: str,
    builder: str,
) -> list[tuple[int, int, str]]:
    edits: list[tuple[int, int, str]] = []

    def walk(node: yaml.Node, key_hint: str = "") -> None:
        if isinstance(node, yaml.MappingNode):
            for key_node, value_node in node.value:
                hint = key_node.value.lower() if isinstance(key_node, yaml.ScalarNode) else ""
                walk(value_node, hint)
        elif isinstance(node, yaml.SequenceNode):
            for child in node.value:
                walk(child, key_hint)
        elif isinstance(node, yaml.ScalarNode):
            changed = replacement_for_scalar(
                key_hint,
                node.value,
                to_new=to_new,
                old_sha=old_sha,
                old_digest=old_digest,
                new_sha=new_sha,
                new_digest=new_digest,
                builder=builder,
            )
            if changed != node.value:
                start, end = node.start_mark.index, node.end_mark.index
                edits.append((start, end, scalar_token(source[start:end], changed)))

    walk(mapping)
    return edits


def migrate_source_lock(
    path: Path,
    *,
    old_sha: str,
    old_digest: str,
    new_sha: str,
    new_digest: str,
    builder: str,
) -> None:
    source = path.read_text()
    node = yaml.compose(source)
    if node is None:
        raise MigrationError("Production source lock is empty")
    mappings: list[yaml.MappingNode] = []
    collect_mappings(node, mappings)
    old_slots = [item for item in mappings if direct_repository(item) == OLD_REPOSITORY]
    new_slots = [item for item in mappings if direct_repository(item) == NEW_REPOSITORY]
    if len(old_slots) != 1 or len(new_slots) != 1:
        raise MigrationError(
            "Production source-lock Middleware slots are ambiguous: "
            f"old={len(old_slots)} new={len(new_slots)}"
        )
    edits = mapping_edits(
        old_slots[0],
        source,
        to_new=True,
        old_sha=old_sha,
        old_digest=old_digest,
        new_sha=new_sha,
        new_digest=new_digest,
        builder=builder,
    )
    edits.extend(
        mapping_edits(
            new_slots[0],
            source,
            to_new=False,
            old_sha=old_sha,
            old_digest=old_digest,
            new_sha=new_sha,
            new_digest=new_digest,
            builder=builder,
        )
    )
    if not edits:
        raise MigrationError("Production source lock did not require an identity swap")
    for start, end, replacement in sorted(edits, reverse=True):
        source = source[:start] + replacement + source[end:]
    # Parse again and require exactly one slot for each authority after the swap.
    reparsed = yaml.compose(source)
    if reparsed is None:
        raise MigrationError("Production source lock became empty")
    post: list[yaml.MappingNode] = []
    collect_mappings(reparsed, post)
    if sum(direct_repository(item) == NEW_REPOSITORY for item in post) != 1:
        raise MigrationError("Appolon canonical source-lock identity is not unique")
    if sum(direct_repository(item) == OLD_REPOSITORY for item in post) != 1:
        raise MigrationError("Former rollback source-lock identity is not unique")
    path.write_text(source)


def write_decision_record(
    root: Path,
    *,
    values: dict[str, str],
    artifact: str,
    run_id: str,
    builder: str,
    sbom_hash: str,
    provenance_hash: str,
    openvex_hash: str,
) -> None:
    path = root / "docs" / "APPOLON_MIDDLEWARE_PRODUCTION_AUTHORITY_MIGRATION_20260903.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""# Appolon Middleware production authority migration — 2026-09-03

## Decision

Promote `{NEW_REPOSITORY}` as the canonical Middleware source and image authority for the next protected production release. Retain `{OLD_REPOSITORY}` only in the existing non-promotable/rollback slot until post-cutover retirement is separately reviewed.

## Exact candidate

- Source: `{NEW_REPOSITORY}@{values['SOURCE_SHA']}`
- Image: `{values['IMAGE_REFERENCE']}`
- Signed release run: `{run_id}`
- Signed evidence artifact: `{artifact}`
- Provenance builder: `{builder}`
- SBOM SHA-256: `{sbom_hash}`
- Provenance SHA-256: `{provenance_hash}`
- OpenVEX SHA-256: `{openvex_hash}`

## Safety boundary

This commit changes repository authority and release verification only. It does not deploy a container, run a migration, alter SSH, route production traffic, enable business writes, or enable any provider effect. Protected staging, backup/restore, rollback, canary, observation-window, and full-traffic gates remain mandatory.
"""
    )


def migrate(root: Path, evidence: Path, artifact: str, run_id: str) -> dict[str, str]:
    values = read_release_env(evidence / "RELEASE.env")
    provenance_path = evidence / "provenance.json"
    openvex_path = evidence / "vex" / "openvex.json"
    for required in (provenance_path, openvex_path, evidence / "sbom.cdx.json"):
        if not required.is_file():
            raise MigrationError(f"Signed evidence file is missing: {required}")
    provenance = json.loads(provenance_path.read_text())
    builder = provenance_builder(provenance)

    tuple_path = root / "config" / "production-release-tuple.json"
    authority = json.loads(tuple_path.read_text())
    old_sha = authority["middleware_source_sha"]
    old_digest = authority["middleware_digest"]
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
    sbom_hash = sha256(evidence / "sbom.cdx.json")
    provenance_hash = sha256(provenance_path)
    openvex_hash = sha256(openvex_path)
    authority.update(
        {
            "middleware_artifact": artifact,
            "middleware_digest": values["IMAGE_DIGEST"],
            "middleware_openvex_sha256": openvex_hash,
            "middleware_provenance_sha256": provenance_hash,
            "middleware_run_id": str(run_id),
            "middleware_sbom_sha256": sbom_hash,
            "middleware_source_sha": values["SOURCE_SHA"],
        }
    )
    tuple_path.write_text(json.dumps(authority, indent=2, sort_keys=True) + "\n")

    active_paths = [
        ".github/workflows/protected-release.yml",
        "tools/verify_middleware_release_evidence.py",
        "tools/verify_slsa_provenance_attestation.py",
        "tools/build_release_bundle.py",
        "tools/verify_jetstream_worker_image.py",
        "config/jetstream-dlq-worker.env.example",
    ]
    missing = [relpath for relpath in active_paths if not (root / relpath).is_file()]
    if missing:
        raise MigrationError(f"Active production authority files are missing: {missing}")
    for relpath in active_paths:
        replace_active_authority(root / relpath, builder)

    migrate_source_lock(
        root / "PRODUCTION-SOURCE-LOCK.yaml",
        old_sha=old_sha,
        old_digest=old_digest,
        new_sha=values["SOURCE_SHA"],
        new_digest=values["IMAGE_DIGEST"],
        builder=builder,
    )

    # Tests encode both the canonical and rollback slots, so swap rather than erase them.
    for path in (root / "tests").rglob("*.py"):
        text = path.read_text()
        changed = swap_authority_strings(text)
        old_builder = (
            f"https://github.com/{OLD_REPOSITORY}/{OLD_WORKFLOW}"
            "@refs/heads/main"
        )
        changed = changed.replace(old_builder, builder)
        if changed != text:
            path.write_text(changed)

    write_decision_record(
        root,
        values=values,
        artifact=artifact,
        run_id=str(run_id),
        builder=builder,
        sbom_hash=sbom_hash,
        provenance_hash=provenance_hash,
        openvex_hash=openvex_hash,
    )
    return {
        "source_sha": values["SOURCE_SHA"],
        "image_digest": values["IMAGE_DIGEST"],
        "image_reference": values["IMAGE_REFERENCE"],
        "artifact": artifact,
        "run_id": str(run_id),
        "builder": builder,
        "sbom_sha256": sbom_hash,
        "provenance_sha256": provenance_hash,
        "openvex_sha256": openvex_hash,
        "former_source_sha": old_sha,
        "former_image_digest": old_digest,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = migrate(
        args.root.resolve(),
        args.evidence.resolve(),
        args.artifact,
        args.run_id,
    )
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.write_text(encoded)
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
