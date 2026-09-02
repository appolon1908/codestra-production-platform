#!/usr/bin/env python3
"""Publish and read back the exact financial-governance commit status."""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PACKAGE = Path(__file__).resolve().parents[1] / "database-certification"
sys.path.insert(0, str(DB_PACKAGE))
from runtime_contract import (  # noqa: E402
    ContractError,
    atomic_write_json,
    require_executable,
    run_command,
    validate_protected_file,
    write_prometheus_textfile,
)

REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
CONTEXT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,99}$")
ALLOWED_STATES = {"error", "failure", "pending", "success"}
DEFAULT_METRICS = Path("/var/lib/node_exporter/textfile_collector/codestra_financial_governance.prom")
DEFAULT_EVIDENCE = Path("/opt/codestra/evidence/server-a-certification/governance/LAST_RESULT.json")


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ContractError(f"required governance configuration is missing: {name}")
    if "\n" in value or "\r" in value:
        raise ContractError(f"governance configuration contains a newline: {name}")
    return value


def regular_file(path: Path) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise ContractError(f"governance input is unavailable: {path}: {exc}") from exc
    if path.is_symlink() or not path.is_file() or info.st_size > 65536:
        raise ContractError(f"governance input must be a bounded regular file: {path}")
    if info.st_mode & 0o022:
        raise ContractError(f"governance input must not be group/other writable: {path}")


def read_sha(path: Path) -> str:
    regular_file(path)
    value = path.read_text(encoding="utf-8").strip()
    if not SHA_RE.fullmatch(value):
        raise ContractError("governance target SHA must be an exact lowercase 40-character commit")
    return value


def read_state(path: Path) -> dict[str, str]:
    regular_file(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ContractError("governance state file is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ContractError("governance state file must be a JSON object")
    state = str(payload.get("state", "")).strip()
    if state not in ALLOWED_STATES:
        raise ContractError("governance state is not supported by the GitHub status API")
    description = str(payload.get("description", "")).strip()
    if not description or len(description) > 140 or "\n" in description:
        raise ContractError("governance status description must contain 1-140 single-line characters")
    target_url = str(payload.get("target_url", "")).strip()
    if target_url:
        parsed = urllib.parse.urlsplit(target_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ContractError("governance target_url must be an absolute credential-free HTTPS URL")
    return {"state": state, "description": description, "target_url": target_url}


def gh_json(args: list[str], *, token: str, input_payload: dict[str, Any] | None = None, check: bool = True) -> Any:
    environment = os.environ.copy()
    environment["GH_TOKEN"] = token
    environment["GH_PAGER"] = "cat"
    input_bytes = None
    if input_payload is not None:
        input_bytes = (json.dumps(input_payload, separators=(",", ":")) + "\n").encode()
    result = run_command(
        ["gh", "api", *args],
        input_bytes=input_bytes,
        env=environment,
        timeout=45,
        check=check,
    )
    if not result.stdout:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ContractError("GitHub CLI returned non-JSON output") from exc


def status_matches(item: dict[str, Any], *, context: str, state: dict[str, str]) -> bool:
    return all(
        (
            item.get("context") == context,
            item.get("state") == state["state"],
            item.get("description") == state["description"],
            (item.get("target_url") or "") == state["target_url"],
        )
    )


def publish_once(*, repository: str, sha: str, context: str, state: dict[str, str], token: str) -> dict[str, Any]:
    commit = gh_json([f"repos/{repository}/commits/{sha}"], token=token)
    if not isinstance(commit, dict) or commit.get("sha") != sha:
        raise ContractError("target commit is not present in the configured repository")
    statuses = gh_json([f"repos/{repository}/commits/{sha}/statuses?per_page=100"], token=token)
    if not isinstance(statuses, list):
        raise ContractError("GitHub status readback returned an unexpected response")
    existing = next(
        (item for item in statuses if isinstance(item, dict) and status_matches(item, context=context, state=state)),
        None,
    )
    created_new = existing is None
    if existing is None:
        payload: dict[str, str] = {
            "state": state["state"],
            "context": context,
            "description": state["description"],
        }
        if state["target_url"]:
            payload["target_url"] = state["target_url"]
        created = gh_json(
            ["--method", "POST", f"repos/{repository}/statuses/{sha}", "--input", "-"],
            token=token,
            input_payload=payload,
        )
        if not isinstance(created, dict) or not status_matches(created, context=context, state=state):
            raise ContractError("created GitHub status does not match the requested contract")
    else:
        created = existing
    status_id = created.get("id")
    if not isinstance(status_id, int):
        raise ContractError("GitHub status response has no numeric status id")
    readback = gh_json([f"repos/{repository}/commits/{sha}/statuses?per_page=100"], token=token)
    if not isinstance(readback, list):
        raise ContractError("GitHub status readback returned an unexpected response")
    confirmed = next(
        (item for item in readback if isinstance(item, dict) and item.get("id") == status_id),
        None,
    )
    if confirmed is None or not status_matches(confirmed, context=context, state=state):
        raise ContractError("GitHub status readback did not confirm the exact status id")
    return {
        "status_id": status_id,
        "created_new": created_new,
        "created_at": confirmed.get("created_at"),
        "updated_at": confirmed.get("updated_at"),
        "state": confirmed.get("state"),
        "context": confirmed.get("context"),
        "target_url": confirmed.get("target_url"),
    }


def publish_metrics(path: Path, *, success: bool, state: str, timestamp: int) -> None:
    state_value = 1 if state == "success" else 0
    write_prometheus_textfile(
        path,
        [
            "# HELP codestra_financial_governance_publish_success Whether the last status publish and readback succeeded.",
            "# TYPE codestra_financial_governance_publish_success gauge",
            f"codestra_financial_governance_publish_success {1 if success else 0}",
            "# HELP codestra_financial_governance_state_success Whether the published governance state is success.",
            "# TYPE codestra_financial_governance_state_success gauge",
            f"codestra_financial_governance_state_success {state_value}",
            "# HELP codestra_financial_governance_last_publish_timestamp_seconds Unix timestamp of the last successful publish.",
            "# TYPE codestra_financial_governance_last_publish_timestamp_seconds gauge",
            f"codestra_financial_governance_last_publish_timestamp_seconds {timestamp if success else 0}",
        ],
    )


def main() -> int:
    metrics = Path(os.environ.get("CODESTRA_GOVERNANCE_METRICS_FILE", str(DEFAULT_METRICS)))
    evidence = Path(os.environ.get("CODESTRA_GOVERNANCE_EVIDENCE_FILE", str(DEFAULT_EVIDENCE)))
    token = ""
    state_name = "error"
    try:
        require_executable("gh")
        repository = required("CODESTRA_GOVERNANCE_REPOSITORY")
        if not REPOSITORY_RE.fullmatch(repository):
            raise ContractError("governance repository must use owner/name form")
        context = os.environ.get("CODESTRA_GOVERNANCE_CONTEXT", "codestra/financial-governance").strip()
        if not CONTEXT_RE.fullmatch(context):
            raise ContractError("governance context is invalid")
        sha = read_sha(Path(required("CODESTRA_GOVERNANCE_SHA_FILE")))
        state = read_state(Path(required("CODESTRA_GOVERNANCE_STATE_FILE")))
        state_name = state["state"]
        token_path = Path(required("CODESTRA_GOVERNANCE_TOKEN_FILE"))
        validate_protected_file(token_path, owner_uid=0)
        token = token_path.read_text(encoding="utf-8").strip()
        if len(token) < 20 or "\n" in token or "\r" in token:
            raise ContractError("governance token file is empty or malformed")
        attempts = int(os.environ.get("CODESTRA_GOVERNANCE_MAX_ATTEMPTS", "4"))
        if attempts < 1 or attempts > 6:
            raise ContractError("governance retry count must be between 1 and 6")
        last_error: Exception | None = None
        created: dict[str, Any] | None = None
        for attempt in range(1, attempts + 1):
            try:
                created = publish_once(repository=repository, sha=sha, context=context, state=state, token=token)
                break
            except (ContractError, OSError) as exc:
                last_error = exc
                if attempt == attempts:
                    break
                time.sleep(min(8, 2 ** (attempt - 1)))
        if created is None:
            raise ContractError(f"GitHub status publishing failed after {attempts} attempts: {last_error}")
        payload = {
            "schema": "codestra.financial-governance-publish-result.v1",
            "status": "PASS",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "repository": repository,
            "sha": sha,
            "requested_state": state_name,
            "context": context,
            "readback": created,
        }
        atomic_write_json(evidence, payload)
        publish_metrics(metrics, success=True, state=state_name, timestamp=int(datetime.now(timezone.utc).timestamp()))
        print(json.dumps(payload, sort_keys=True))
        return 0
    except (ContractError, OSError, ValueError, json.JSONDecodeError) as exc:
        sanitized = str(exc)
        if token:
            sanitized = sanitized.replace(token, "[REDACTED]")
        try:
            atomic_write_json(
                evidence,
                {
                    "schema": "codestra.financial-governance-publish-result.v1",
                    "status": "FAIL",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "error": sanitized[:1000],
                },
            )
            publish_metrics(metrics, success=False, state=state_name, timestamp=0)
        except Exception:
            pass
        print(f"FINANCIAL_GOVERNANCE_PUBLISHER=FAIL:{sanitized[:1000]}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
