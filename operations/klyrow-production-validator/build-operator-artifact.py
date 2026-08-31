#!/usr/bin/python3
"""Build a deterministic, runtime-dependency-free Klyrow validator bundle."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.metadata
import io
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path


PAYLOAD_FILES = (
    "klyrow-production-validator",
    "klyrow-production-validator-root",
    "klyrow-production-validator-actions",
    "klyrow_validator_core.py",
    "kpv_probe_core.py",
    "probe-authorization-tests",
    "probe-no-effect-tests",
    "probe-callback-tests",
    "probe-smtp-no-data",
    "command-contract.json",
    "klyrow-production-validator.sudoers",
    "authorized_keys.template",
    "requirements.lock",
    "install-klyrow-production-validator.py",
    "install_klyrow_production_validator_compat.py",
    "remove-klyrow-production-validator.py",
    "revoke-klyrow-validator-key.py",
    "validate-klyrow-production-validator.py",
    "README.md",
)
BANDIT_VERSION = "1.9.4"
SOURCE_SCAN_FILES = (
    "build-operator-artifact.py",
    "klyrow-production-validator",
    "klyrow-production-validator-root",
    "klyrow-production-validator-actions",
    "klyrow_validator_core.py",
    "kpv_probe_core.py",
    "probe-authorization-tests",
    "probe-no-effect-tests",
    "probe-callback-tests",
    "probe-smtp-no-data",
    "install-klyrow-production-validator.py",
    "install_klyrow_production_validator_compat.py",
    "remove-klyrow-production-validator.py",
    "revoke-klyrow-validator-key.py",
    "validate-klyrow-production-validator.py",
)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def canonical_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def source_vulnerability_report(source: Path, source_sha: str) -> dict[str, object]:
    try:
        installed_version = importlib.metadata.version("bandit")
    except importlib.metadata.PackageNotFoundError as exc:
        raise SystemExit("pinned Bandit source scanner is required") from exc
    if installed_version != BANDIT_VERSION:
        raise SystemExit("unexpected Bandit source scanner version")
    targets = [source / name for name in SOURCE_SCAN_FILES]
    if any(not path.is_file() or path.is_symlink() for path in targets):
        raise SystemExit("unsafe or missing source-scan target")
    result = subprocess.run(
        [sys.executable, "-m", "bandit", "-f", "json", *(str(path) for path in targets)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
        check=False,
        env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C", "LC_ALL": "C"},
    )
    if result.returncode not in {0, 1} or len(result.stdout) > 8 * 1024 * 1024:
        raise SystemExit("Bandit source scan failed")
    try:
        raw = json.loads(result.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit("Bandit source report invalid") from exc
    if not isinstance(raw, dict) or raw.get("errors") != []:
        raise SystemExit("Bandit source scan errors present")
    findings = raw.get("results")
    metrics = raw.get("metrics")
    if not isinstance(findings, list) or not isinstance(metrics, dict):
        raise SystemExit("Bandit source report schema rejected")
    expected_metric_paths = {str(path) for path in targets}
    if set(metrics) - {"_totals"} != expected_metric_paths:
        raise SystemExit("Bandit source scan coverage mismatch")
    severities = {"LOW": 0, "MEDIUM": 0, "HIGH": 0}
    for finding in findings:
        if not isinstance(finding, dict) or finding.get("issue_severity") not in severities:
            raise SystemExit("Bandit finding schema rejected")
        severities[str(finding["issue_severity"])] += 1
    report = {
        "schema_version": "2.0.0",
        "source_sha": source_sha,
        "dependency_lock": "requirements.lock",
        "dependency_lock_sha256": digest(source / "requirements.lock"),
        "runtime_dependencies": 0,
        "source_scan": {
            "scanner": "bandit",
            "scanner_version": installed_version,
            "files_scanned": list(SOURCE_SCAN_FILES),
            "errors": 0,
            "findings": {
                "high": severities["HIGH"],
                "medium": severities["MEDIUM"],
                "low": severities["LOW"],
            },
        },
        "critical": "NOT_APPLICABLE_BANDIT_SEVERITY_MODEL",
        "high": severities["HIGH"],
        "gate": "PASS" if severities["HIGH"] == 0 else "FAIL",
    }
    if report["gate"] != "PASS":
        raise SystemExit("source vulnerability gate failed")
    return report


def build_archive(source: Path, destination: Path, source_sha: str) -> None:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for name in PAYLOAD_FILES:
            path = source / name
            if not path.is_file() or path.is_symlink():
                raise SystemExit(f"unsafe or missing payload: {name}")
            data = path.read_bytes()
            info = tarfile.TarInfo(f"klyrow-production-validator-{source_sha}/{name}")
            info.size = len(data)
            info.mode = 0o755 if name.endswith(".py") or name.startswith(("klyrow-", "install-", "remove-", "validate-", "build-")) else 0o444
            if name.endswith((".json", ".lock", ".template", ".sudoers", ".md")):
                info.mode = 0o444
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            info.mtime = 0
            archive.addfile(info, io.BytesIO(data))
    with destination.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            compressed.write(buffer.getvalue())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--workflow-run", default="local-untrusted")
    args = parser.parse_args()
    if len(args.source_sha) != 40 or any(char not in "0123456789abcdef" for char in args.source_sha):
        raise SystemExit("source SHA must be 40 lowercase hexadecimal characters")
    source = Path(__file__).resolve().parent
    output = args.output.resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    vulnerability_report = source_vulnerability_report(source, args.source_sha)
    archive = output / f"klyrow-production-validator-{args.source_sha}.tar.gz"
    build_archive(source, archive, args.source_sha)
    payload_hashes = {name: digest(source / name) for name in PAYLOAD_FILES}
    artifact_sha = digest(archive)
    canonical_json(
        output / "installation-manifest.json",
        {
            "schema_version": "1.0.0",
            "source_repository": "appolon1908-hue/codestra-production-platform",
            "source_sha": args.source_sha,
            "artifact": archive.name,
            "artifact_sha256": artifact_sha,
            "payload_sha256": payload_hashes,
            "install_root": f"/opt/codestra/operators/klyrow-production-validator/{args.source_sha}",
            "stable_entrypoints": [
                "/usr/local/libexec/codestra/klyrow-production-validator",
                "/usr/local/libexec/codestra/klyrow-production-validator-root",
                "/usr/local/libexec/codestra/klyrow-production-validator-actions"
            ],
            "application_runtime_mutations": 0,
        },
    )
    canonical_json(
        output / "sbom.spdx.json",
        {
            "SPDXID": "SPDXRef-DOCUMENT",
            "spdxVersion": "SPDX-2.3",
            "dataLicense": "CC0-1.0",
            "name": f"klyrow-production-validator-{args.source_sha}",
            "documentNamespace": f"https://codestra.co/sbom/klyrow-production-validator/{args.source_sha}",
            "creationInfo": {
                "created": "1970-01-01T00:00:00Z",
                "creators": ["Tool: build-operator-artifact.py"]
            },
            "packages": [
                {
                    "SPDXID": "SPDXRef-Package-klyrow-validator",
                    "name": "klyrow-production-validator",
                    "versionInfo": args.source_sha,
                    "downloadLocation": "NOASSERTION",
                    "filesAnalyzed": True,
                    "licenseConcluded": "NOASSERTION",
                    "licenseDeclared": "NOASSERTION",
                    "copyrightText": "NOASSERTION",
                    "checksums": [{"algorithm": "SHA256", "checksumValue": artifact_sha}],
                    "externalRefs": []
                }
            ],
            "files": [
                {
                    "SPDXID": f"SPDXRef-File-{index}",
                    "fileName": name,
                    "licenseConcluded": "NOASSERTION",
                    "copyrightText": "NOASSERTION",
                    "checksums": [{"algorithm": "SHA256", "checksumValue": value}]
                }
                for index, (name, value) in enumerate(sorted(payload_hashes.items()), start=1)
            ]
        },
    )
    canonical_json(
        output / "provenance.json",
        {
            "_type": "https://in-toto.io/Statement/v1",
            "subject": [{"name": archive.name, "digest": {"sha256": artifact_sha}}],
            "predicateType": "https://slsa.dev/provenance/v1",
            "predicate": {
                "buildDefinition": {
                    "buildType": "https://codestra.co/build/klyrow-production-validator/v1",
                    "externalParameters": {"source_sha": args.source_sha},
                    "resolvedDependencies": [
                        {
                            "uri": "git+https://github.com/appolon1908-hue/codestra-production-platform",
                            "digest": {"gitCommit": args.source_sha}
                        }
                    ]
                },
                "runDetails": {
                    "builder": {"id": ".github/workflows/klyrow-production-validator.yml"},
                    "metadata": {"invocationId": args.workflow_run}
                }
            }
        },
    )
    canonical_json(
        output / "vulnerability-report.json",
        vulnerability_report,
    )
    checksummed = [archive, output / "installation-manifest.json", output / "sbom.spdx.json", output / "provenance.json", output / "vulnerability-report.json"]
    (output / "SHA256SUMS").write_text(
        "".join(f"{digest(path)}  {path.name}\n" for path in sorted(checksummed)),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
