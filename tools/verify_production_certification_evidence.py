#!/usr/bin/env python3
"""Fail-closed verification for the production source lock and immutable matrix.

This verifier never turns a status to PASS. It inspects committed evidence, optionally
verifies repository commits against GitHub, and writes a secret-free result. The
release gate is satisfied only when the existing authorities already contain complete,
real evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "config" / "production-certification-evidence-policy.v1.json"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")

REPOSITORY_KEYS = {
    "repository", "repo", "source_repository", "source_repo", "github_repository"
}
SHA_KEYS = {
    "source_sha", "sha", "commit", "commit_sha", "git_sha", "protected_sha",
    "exact_sha", "revision", "source_revision", "head_sha", "merge_sha"
}
BRANCH_KEYS = {"branch", "ref", "source_branch", "protected_branch"}
WORKLOAD_ID_KEYS = {"workload", "workload_id", "id", "name", "service", "component"}
IMAGE_KEYS = {"image", "image_ref", "image_reference", "oci_image", "container_image"}
DIGEST_KEYS = {"image_digest", "digest", "oci_digest", "container_digest"}
SIGNATURE_KEYS = {"signature", "signature_ref", "signature_reference", "cosign_bundle"}
SBOM_KEYS = {"sbom", "sbom_ref", "sbom_reference"}
PROVENANCE_KEYS = {"provenance", "provenance_ref", "provenance_reference", "attestation"}
ROLLBACK_KEYS = {"rollback_digest", "previous_digest", "rollback_image_digest"}
STATUS_KEYS = {"status", "overall_status", "source_lock_status"}
DEPLOYMENT_KEYS = {"deployment_authorized", "deploy_authorized", "runtime_authorized"}


class VerificationError(RuntimeError):
    """Raised for malformed verifier inputs, never for an ordinary blocked gate."""


@dataclass
class Finding:
    code: str
    path: str
    detail: str


@dataclass
class Report:
    status: str = "BLOCKED"
    findings: list[Finding] = field(default_factory=list)
    repository_evidence: list[dict[str, Any]] = field(default_factory=list)
    workload_evidence: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add(self, code: str, path: str, detail: str) -> None:
        self.findings.append(Finding(code, path, detail))

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "status": self.status,
            "metadata": self.metadata,
            "finding_count": len(self.findings),
            "findings": [finding.__dict__ for finding in self.findings],
            "repository_evidence": self.repository_evidence,
            "workload_evidence": self.workload_evidence,
            "secret_values_recorded": False,
            "runtime_contacted": False,
            "deployment_performed": False,
            "production_changed": False,
        }


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VerificationError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise VerificationError(f"JSON root must be an object: {path}")
    return value


def load_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise VerificationError(f"cannot read YAML {path}: {exc}") from exc


def normalize_key(key: Any) -> str:
    return str(key).strip().lower().replace("-", "_").replace(" ", "_")


def walk(value: Any, path: str = "$") -> Iterable[tuple[str, Any]]:
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from walk(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk(child, f"{path}[{index}]")


def first_value(mapping: dict[str, Any], aliases: set[str]) -> Any:
    for key, value in mapping.items():
        if normalize_key(key) in aliases:
            return value
    return None


def values_for(mapping: dict[str, Any], aliases: set[str]) -> list[Any]:
    return [value for key, value in mapping.items() if normalize_key(key) in aliases]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_forbidden(value: Any, forbidden: set[str]) -> bool:
    if value is None:
        return True
    if isinstance(value, bool):
        return False
    if not isinstance(value, (str, int, float)):
        return False
    text = str(value).strip().upper()
    if not text:
        return True
    return any(token == text or token in text for token in forbidden)


def find_status(document: Any) -> Any:
    if isinstance(document, dict):
        for key, value in document.items():
            if normalize_key(key) in STATUS_KEYS:
                return value
    return None


def find_deployment_authorized(document: Any) -> Any:
    values: list[Any] = []
    for _, value in walk(document):
        if isinstance(value, dict):
            values.extend(values_for(value, DEPLOYMENT_KEYS))
    bools = [item for item in values if isinstance(item, bool)]
    if True in bools:
        return True
    if False in bools:
        return False
    return None


def github_json(path: str, token: str | None) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "codestra-production-evidence-verifier",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(f"https://api.github.com{path}", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        raise VerificationError(f"GitHub API returned HTTP {exc.code} for {path}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise VerificationError(f"GitHub API transport failed for {path}: {exc}") from exc
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise VerificationError(f"GitHub API returned malformed JSON for {path}") from exc


def collect_repository_evidence(document: Any, report: Report, forbidden: set[str]) -> None:
    seen: set[tuple[str, str]] = set()
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    verify_remote = bool(report.metadata.get("verify_github"))

    for path, value in walk(document):
        if not isinstance(value, dict):
            continue
        repository = first_value(value, REPOSITORY_KEYS)
        sha = first_value(value, SHA_KEYS)
        branch = first_value(value, BRANCH_KEYS)
        if repository is None or sha is None:
            continue
        repository = str(repository).strip()
        sha = str(sha).strip().lower()
        if not REPOSITORY_RE.fullmatch(repository):
            report.add("INVALID_REPOSITORY", path, "repository must be owner/name")
            continue
        if is_forbidden(sha, forbidden) or not SHA_RE.fullmatch(sha):
            report.add("INVALID_SOURCE_SHA", path, "source SHA must be 40 lowercase hexadecimal characters")
            continue
        key = (repository, sha)
        if key in seen:
            continue
        seen.add(key)
        item: dict[str, Any] = {
            "repository": repository,
            "sha": sha,
            "branch": str(branch).strip() if branch is not None else None,
            "path": path,
            "commit_exists": None,
            "branch_head": None,
            "branch_head_matches": None,
        }
        if verify_remote:
            encoded_repo = urllib.parse.quote(repository, safe="/")
            try:
                commit = github_json(f"/repos/{encoded_repo}/commits/{sha}", token)
                item["commit_exists"] = isinstance(commit, dict) and commit.get("sha") == sha
                if not item["commit_exists"]:
                    report.add("COMMIT_NOT_VERIFIED", path, f"GitHub did not return exact commit {repository}@{sha}")
                if branch and isinstance(branch, str) and not SHA_RE.fullmatch(branch):
                    encoded_branch = urllib.parse.quote(branch, safe="")
                    reference = github_json(
                        f"/repos/{encoded_repo}/git/ref/heads/{encoded_branch}", token
                    )
                    head = ((reference or {}).get("object") or {}).get("sha")
                    item["branch_head"] = head
                    item["branch_head_matches"] = head == sha
            except VerificationError as exc:
                report.add("GITHUB_VERIFICATION_FAILED", path, str(exc))
        report.repository_evidence.append(item)

    if not report.repository_evidence:
        report.add("NO_REPOSITORY_EVIDENCE", "$", "no repository and exact source-SHA pairs were found")


def collect_workloads(matrix: Any, report: Report, policy: dict[str, Any], forbidden: set[str]) -> None:
    candidates: list[tuple[str, dict[str, Any]]] = []
    for path, value in walk(matrix):
        if not isinstance(value, dict):
            continue
        workload_id = first_value(value, WORKLOAD_ID_KEYS)
        repository = first_value(value, REPOSITORY_KEYS)
        source_sha = first_value(value, SHA_KEYS)
        image = first_value(value, IMAGE_KEYS)
        digest = first_value(value, DIGEST_KEYS)
        evidence_score = sum(
            item is not None for item in (workload_id, repository, source_sha, image, digest)
        )
        if evidence_score >= 3 and workload_id is not None:
            candidates.append((path, value))

    unique: dict[str, tuple[str, dict[str, Any]]] = {}
    for path, value in candidates:
        workload_id = str(first_value(value, WORKLOAD_ID_KEYS)).strip()
        if workload_id:
            unique.setdefault(workload_id, (path, value))

    expected = int(policy["runtime_matrix"]["expected_workloads"])
    if len(unique) != expected:
        report.add(
            "WORKLOAD_COUNT_MISMATCH",
            "$",
            f"expected exactly {expected} unique workloads, found {len(unique)}",
        )

    for workload_id, (path, value) in sorted(unique.items()):
        repository = first_value(value, REPOSITORY_KEYS)
        source_sha = first_value(value, SHA_KEYS)
        image = first_value(value, IMAGE_KEYS)
        digest = first_value(value, DIGEST_KEYS)
        signature = first_value(value, SIGNATURE_KEYS)
        sbom = first_value(value, SBOM_KEYS)
        provenance = first_value(value, PROVENANCE_KEYS)
        rollback = first_value(value, ROLLBACK_KEYS)

        if digest is None and isinstance(image, str) and "@" in image:
            digest = image.rsplit("@", 1)[-1]
        normalized = {
            "workload": workload_id,
            "repository": repository,
            "source_sha": source_sha,
            "image": image,
            "image_digest": digest,
            "signature": signature,
            "sbom": sbom,
            "provenance": provenance,
            "rollback_digest": rollback,
            "path": path,
        }
        report.workload_evidence.append(normalized)

        if not isinstance(repository, str) or not REPOSITORY_RE.fullmatch(repository.strip()):
            report.add("WORKLOAD_REPOSITORY_INVALID", path, f"{workload_id}: repository is missing or invalid")
        if not isinstance(source_sha, str) or not SHA_RE.fullmatch(source_sha.strip().lower()):
            report.add("WORKLOAD_SOURCE_SHA_INVALID", path, f"{workload_id}: source SHA is missing or invalid")
        if image is not None:
            image_text = str(image).strip()
            if ":latest" in image_text or ("@sha256:" not in image_text and not DIGEST_RE.fullmatch(str(digest or ""))):
                report.add("WORKLOAD_IMAGE_MUTABLE", path, f"{workload_id}: image is not digest-bound")
        if not isinstance(digest, str) or not DIGEST_RE.fullmatch(digest.strip().lower()):
            report.add("WORKLOAD_DIGEST_INVALID", path, f"{workload_id}: image digest is missing or invalid")
        for code, name, item in (
            ("WORKLOAD_SIGNATURE_MISSING", "signature", signature),
            ("WORKLOAD_SBOM_MISSING", "SBOM", sbom),
            ("WORKLOAD_PROVENANCE_MISSING", "provenance", provenance),
        ):
            if is_forbidden(item, forbidden):
                report.add(code, path, f"{workload_id}: {name} evidence is missing or unresolved")
        if not isinstance(rollback, str) or not DIGEST_RE.fullmatch(rollback.strip().lower()):
            report.add("WORKLOAD_ROLLBACK_INVALID", path, f"{workload_id}: rollback digest is missing or invalid")


def scan_placeholders(document: Any, report: Report, forbidden: set[str], scope: str) -> None:
    for path, value in walk(document):
        if isinstance(value, str) and is_forbidden(value, forbidden):
            report.add("UNRESOLVED_VALUE", f"{scope}{path[1:]}", "value is unresolved or placeholder-backed")
        if isinstance(value, str) and ":latest" in value:
            report.add("MUTABLE_IMAGE_REFERENCE", f"{scope}{path[1:]}", "mutable latest tag is prohibited")


def verify(
    source_lock_path: Path,
    matrix_path: Path,
    policy_path: Path,
    verify_github: bool,
    require_pass: bool,
) -> Report:
    policy = load_json(policy_path)
    source_lock = load_yaml(source_lock_path)
    matrix = load_yaml(matrix_path)
    report = Report()
    report.metadata = {
        "source_lock_path": str(source_lock_path),
        "source_lock_sha256": sha256_file(source_lock_path),
        "matrix_path": str(matrix_path),
        "matrix_sha256": sha256_file(matrix_path),
        "policy_path": str(policy_path),
        "verify_github": verify_github,
        "require_pass": require_pass,
        "expected_workloads": policy["runtime_matrix"]["expected_workloads"],
    }
    forbidden = {str(value).upper() for value in policy["forbidden_evidence_values"]}

    source_status = find_status(source_lock)
    report.metadata["source_lock_status"] = source_status
    if str(source_status).upper() != str(policy["source_lock"]["required_status"]).upper():
        report.add("SOURCE_LOCK_NOT_PASS", "$source_lock", f"observed status is {source_status!r}")

    deployment_authorized = find_deployment_authorized(matrix)
    report.metadata["matrix_deployment_authorized"] = deployment_authorized
    if policy["runtime_matrix"]["deployment_authorized_required"] and deployment_authorized is not True:
        report.add("MATRIX_NOT_AUTHORIZED", "$matrix", "deployment authorization is not true")

    scan_placeholders(source_lock, report, forbidden, "$source_lock")
    scan_placeholders(matrix, report, forbidden, "$matrix")
    collect_repository_evidence(source_lock, report, forbidden)
    collect_repository_evidence(matrix, report, forbidden)
    collect_workloads(matrix, report, policy, forbidden)

    report.status = "PASS" if not report.findings else "BLOCKED"
    if require_pass and report.status != "PASS":
        report.metadata["release_gate"] = "FAIL_CLOSED"
    else:
        report.metadata["release_gate"] = "PASS" if report.status == "PASS" else "EVIDENCE_INCOMPLETE"
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-lock", type=Path, default=ROOT / "PRODUCTION-SOURCE-LOCK.yaml")
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--evidence-output", type=Path)
    parser.add_argument("--verify-github", action="store_true")
    parser.add_argument("--require-pass", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = verify(
            args.source_lock,
            args.matrix,
            args.policy,
            args.verify_github,
            args.require_pass,
        )
    except VerificationError as exc:
        print(f"PRODUCTION_CERTIFICATION_EVIDENCE_ERROR={exc}", file=sys.stderr)
        return 1
    payload = report.as_dict()
    if args.evidence_output:
        args.evidence_output.parent.mkdir(parents=True, exist_ok=True)
        args.evidence_output.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(f"PRODUCTION_CERTIFICATION_EVIDENCE={report.status}")
    print(f"FINDINGS={len(report.findings)}")
    if args.require_pass and report.status != "PASS":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
