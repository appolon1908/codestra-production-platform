#!/usr/bin/env python3
"""Issue the Server A verdict only from hashed, inspectable gate evidence."""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

DB_PACKAGE = Path(__file__).resolve().parents[1] / "database-certification"
sys.path.insert(0, str(DB_PACKAGE))
from runtime_contract import ContractError, atomic_write_json, load_json, sha256_file  # noqa: E402

ALLOWED_STATUS = {"PASS", "WARNING", "FAIL", "N/A"}
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
FORBIDDEN_PLACEHOLDERS = ("NOT VERIFIED", "UNKNOWN", "ASSUMED", "REPLACE_")
DEFAULT_CONTRACT = Path(__file__).resolve().with_name("certification-gates.json")
DEFAULT_OUTPUT = Path(
    "/opt/codestra/evidence/server-a-certification/final/FINAL-CERTIFICATION.json"
)
DEFAULT_EVIDENCE_ROOTS = (
    Path("/opt/codestra/evidence"),
    Path("/opt/codestra/backups"),
    Path("/opt/codestra/rollback"),
)


def configured_evidence_roots() -> tuple[Path, ...]:
    raw = os.environ.get("CODESTRA_CERTIFICATION_EVIDENCE_ROOTS", "").strip()
    roots = DEFAULT_EVIDENCE_ROOTS if not raw else tuple(Path(value) for value in raw.split(":"))
    resolved: list[Path] = []
    for root in roots:
        if not root.is_absolute():
            raise ContractError("certification evidence roots must be absolute")
        resolved.append(root.resolve())
    return tuple(resolved)


def ensure_allowed_evidence_path(path: Path, roots: Iterable[Path]) -> Path:
    if not path.is_absolute():
        raise ContractError("evidence path must be absolute")
    try:
        info = path.lstat()
    except OSError as exc:
        raise ContractError(f"evidence file is unavailable: {path}: {exc}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ContractError(f"evidence must be a non-symlink regular file: {path}")
    if info.st_mode & 0o022:
        raise ContractError(f"evidence file must not be group/other writable: {path}")
    resolved = path.resolve()
    if not any(root == resolved or root in resolved.parents for root in roots):
        raise ContractError(f"evidence path is outside approved roots: {path}")
    return resolved


def json_pointer(payload: Any, pointer: str) -> Any:
    if pointer == "":
        return payload
    if not pointer.startswith("/"):
        raise ContractError("JSON pointer must be empty or begin with /")
    current = payload
    for token in pointer[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            try:
                current = current[int(token)]
            except (ValueError, IndexError) as exc:
                raise ContractError(f"JSON pointer list token is unavailable: {token}") from exc
        elif isinstance(current, dict) and token in current:
            current = current[token]
        else:
            raise ContractError(f"JSON pointer token is unavailable: {token}")
    return current


def validate_evidence_item(item: Any, *, gate: str, roots: tuple[Path, ...]) -> dict[str, str]:
    if not isinstance(item, dict):
        raise ContractError(f"gate {gate} evidence item must be an object")
    raw_path = item.get("path")
    expected_digest = item.get("sha256")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ContractError(f"gate {gate} evidence path is missing")
    if any(token in raw_path.upper() for token in FORBIDDEN_PLACEHOLDERS):
        raise ContractError(f"gate {gate} uses a forbidden evidence placeholder")
    if not isinstance(expected_digest, str) or not DIGEST_RE.fullmatch(expected_digest):
        raise ContractError(f"gate {gate} evidence SHA-256 is invalid")
    path = ensure_allowed_evidence_path(Path(raw_path), roots)
    actual_digest = sha256_file(path)
    if actual_digest != expected_digest:
        raise ContractError(f"gate {gate} evidence SHA-256 does not match: {path}")

    assertion_count = int("json_pointer" in item) + int("contains" in item)
    if assertion_count != 1:
        raise ContractError(
            f"gate {gate} evidence must define exactly one content assertion"
        )
    assertion: str
    if "json_pointer" in item:
        pointer = item.get("json_pointer")
        if not isinstance(pointer, str):
            raise ContractError(f"gate {gate} JSON pointer is invalid")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ContractError(f"gate {gate} JSON evidence is unreadable: {path}") from exc
        observed = json_pointer(payload, pointer)
        expected = item.get("equals")
        if observed != expected:
            raise ContractError(
                f"gate {gate} JSON assertion failed at {pointer}: "
                f"observed={observed!r}, expected={expected!r}"
            )
        assertion = f"json_pointer={pointer}"
    else:
        expected_text = item.get("contains")
        if not isinstance(expected_text, str) or not expected_text:
            raise ContractError(f"gate {gate} text assertion is empty")
        if any(token in expected_text.upper() for token in FORBIDDEN_PLACEHOLDERS):
            raise ContractError(f"gate {gate} text assertion uses a placeholder")
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ContractError(f"gate {gate} text evidence is unreadable: {path}") from exc
        if expected_text not in content:
            raise ContractError(f"gate {gate} text assertion is absent from {path}")
        assertion = "contains=PASS"
    return {"path": str(path), "sha256": actual_digest, "assertion": assertion}


def validate_gate_evidence(
    value: Any, *, gate: str, roots: tuple[Path, ...]
) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise ContractError(f"gate {gate} has no inspectable evidence")
    return [validate_evidence_item(item, gate=gate, roots=roots) for item in value]


def evaluate(
    contract: dict[str, Any],
    certification: dict[str, Any],
    *,
    evidence_roots: tuple[Path, ...] | None = None,
) -> dict[str, Any]:
    if contract.get("schema") != "codestra.server-a-certification-gates.v1":
        raise ContractError("unsupported certification-gate contract")
    if certification.get("schema") != "codestra.server-a-certification-input.v2":
        raise ContractError("unsupported certification input schema")
    if certification.get("target_server") != contract.get("target_server"):
        raise ContractError("certification target does not match the gate contract")
    source_commit = str(certification.get("source_commit", ""))
    installed_commit = str(certification.get("installed_commit", ""))
    if not SHA_RE.fullmatch(source_commit) or not SHA_RE.fullmatch(installed_commit):
        raise ContractError("source and installed commits must be exact lowercase Git SHAs")
    if source_commit != installed_commit:
        raise ContractError("source commit and installed commit do not match")
    roots = evidence_roots or configured_evidence_roots()
    gates = certification.get("gates")
    if not isinstance(gates, dict):
        raise ContractError("certification input gates must be an object")
    required_pass = contract.get("required_pass")
    required_warning = contract.get("required_warning")
    if not isinstance(required_pass, list) or not isinstance(required_warning, dict):
        raise ContractError("certification gate contract is incomplete")
    contract_names = set(required_pass) | set(required_warning)
    if set(gates) != contract_names:
        missing = sorted(contract_names - set(gates))
        extra = sorted(set(gates) - contract_names)
        raise ContractError(f"certification gate set mismatch: missing={missing}, extra={extra}")

    validated_evidence: dict[str, list[dict[str, str]]] = {}
    failures: list[str] = []
    for name in required_pass:
        gate = gates[name]
        if not isinstance(gate, dict) or gate.get("status") not in ALLOWED_STATUS:
            raise ContractError(f"gate {name} has an invalid status object")
        if gate.get("status") != "PASS":
            failures.append(name)
            continue
        validated_evidence[name] = validate_gate_evidence(
            gate.get("evidence"), gate=name, roots=roots
        )

    warning_results: dict[str, str] = {}
    for name, required_exception in required_warning.items():
        gate = gates[name]
        if not isinstance(gate, dict) or gate.get("status") not in ALLOWED_STATUS:
            raise ContractError(f"warning gate {name} has an invalid status object")
        if gate.get("status") != "WARNING" or gate.get("exception") != required_exception:
            failures.append(name)
            continue
        validated_evidence[name] = validate_gate_evidence(
            gate.get("evidence"), gate=name, roots=roots
        )
        warning_results[name] = required_exception

    verdict = (
        "PRODUCTION_CERTIFIED_WITH_ACCEPTED_SSH_SECURITY_EXCEPTION"
        if not failures
        else "NOT_CERTIFIED"
    )
    return {
        "schema": "codestra.server-a-certification-result.v2",
        "status": "PASS" if not failures else "FAIL",
        "target_server": contract["target_server"],
        "source_commit": source_commit,
        "installed_commit": installed_commit,
        "verdict": verdict,
        "failed_gates": failures,
        "required_pass_gate_count": len(required_pass),
        "accepted_warnings": warning_results,
        "validated_evidence": validated_evidence,
        "production_business_writes_executed": False,
        "ssh_changed": False,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = evaluate(load_json(args.contract), load_json(args.input))
        atomic_write_json(args.output, result)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] == "PASS" else 1
    except (ContractError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        failure = {
            "schema": "codestra.server-a-certification-result.v2",
            "status": "FAIL",
            "target_server": "65.109.65.169",
            "verdict": "NOT_CERTIFIED",
            "error": str(exc)[:1000],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            atomic_write_json(args.output, failure)
        except Exception:
            pass
        print(f"SERVER_A_CERTIFICATION=FAIL:{str(exc)[:1000]}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
