#!/usr/bin/env python3
"""Resolve a fail-closed validation target and Git comparison range.

The platform source gate uses this helper for pull requests, protected-branch
pushes, and manual exact-head validation.  It never treats an unavailable
operator-supplied base as an empty range.  Pushes without a usable predecessor
fall back to a full-tree diff and a full reachable-history Gitleaks scan.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


HEX40 = re.compile(r"^[0-9a-f]{40}$")
ZERO40 = "0" * 40


class SourceGateError(ValueError):
    """Raised when an event cannot be bound to a safe validation range."""


@dataclass(frozen=True)
class ValidationContext:
    event_name: str
    target_sha: str
    comparison_base_sha: str | None
    comparison_mode: str
    diff_spec: str
    gitleaks_log_opts: str


class Git:
    def __init__(self, repository: Path):
        self.repository = repository

    def run(self, *arguments: str) -> str:
        try:
            return subprocess.check_output(
                ["git", *arguments],
                cwd=self.repository,
                text=True,
                stderr=subprocess.PIPE,
            ).strip()
        except subprocess.CalledProcessError as error:
            detail = error.stderr.strip() or str(error)
            raise SourceGateError(f"git {' '.join(arguments)} failed: {detail}") from error

    def commit_available(self, sha: str) -> bool:
        return subprocess.run(
            ["git", "cat-file", "-e", f"{sha}^{{commit}}"],
            cwd=self.repository,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode == 0

    def is_ancestor(self, base: str, target: str) -> bool:
        return subprocess.run(
            ["git", "merge-base", "--is-ancestor", base, target],
            cwd=self.repository,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode == 0

    def merge_base(self, left: str, right: str) -> str:
        base = self.run("merge-base", left, right)
        return require_sha(base, "resolved merge base")

    def first_parent(self, target: str) -> str | None:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", f"{target}^"],
            cwd=self.repository,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else None

    def empty_tree(self) -> str:
        return self.run("hash-object", "-t", "tree", "/dev/null")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SourceGateError(message)


def require_sha(value: object, label: str, *, allow_zero: bool = False) -> str:
    require(
        isinstance(value, str) and HEX40.fullmatch(value) is not None,
        f"{label} must be a lowercase 40-hex SHA",
    )
    if not allow_zero:
        require(value != ZERO40, f"{label} must not be the zero SHA")
    return value


def nested(payload: dict[str, Any], *keys: str) -> object:
    value: object = payload
    for key in keys:
        require(isinstance(value, dict) and key in value, f"event payload is missing {'.'.join(keys)}")
        value = value[key]
    return value


def exact_range(
    git: Git,
    *,
    event_name: str,
    target: str,
    base: str,
    mode: str,
) -> ValidationContext:
    require_sha(base, "comparison base")
    require(git.commit_available(base), f"comparison base is unavailable: {base}")
    require(git.is_ancestor(base, target), f"comparison base is not an ancestor of target: {base}")
    revision = f"{base}..{target}"
    return ValidationContext(event_name, target, base, mode, revision, revision)


def full_history_range(
    git: Git,
    *,
    event_name: str,
    target: str,
    reason: str,
) -> ValidationContext:
    empty_tree = git.empty_tree()
    return ValidationContext(
        event_name,
        target,
        None,
        f"full-history:{reason}",
        f"{empty_tree}..{target}",
        target,
    )


def resolve_context(
    *,
    event_name: str,
    payload: dict[str, Any],
    github_sha: str,
    github_ref: str,
    checked_out_sha: str,
    protected_branch: str,
    git: Git,
) -> ValidationContext:
    require_sha(github_sha, "GITHUB_SHA")
    require_sha(checked_out_sha, "checked-out SHA")

    if event_name == "pull_request":
        target = require_sha(nested(payload, "pull_request", "head", "sha"), "pull-request head")
        base = require_sha(nested(payload, "pull_request", "base", "sha"), "pull-request base")
        require(checked_out_sha == target, "checkout is not the exact pull-request head")
        require(git.commit_available(base), f"pull-request base is unavailable: {base}")
        comparison_base = git.merge_base(base, target)
        return exact_range(
            git,
            event_name=event_name,
            target=target,
            base=comparison_base,
            mode="pull-request-merge-base",
        )

    expected_ref = f"refs/heads/{protected_branch}"
    require(github_ref == expected_ref, f"{event_name} must run from {expected_ref}")

    if event_name == "push":
        target = require_sha(nested(payload, "after"), "push after SHA")
        require(target == github_sha, "push after SHA does not match GITHUB_SHA")
        require(checked_out_sha == target, "checkout is not the exact pushed commit")
        before = nested(payload, "before") if "before" in payload else ""
        if isinstance(before, str) and HEX40.fullmatch(before) and before != ZERO40:
            if git.commit_available(before) and git.is_ancestor(before, target):
                return exact_range(
                    git,
                    event_name=event_name,
                    target=target,
                    base=before,
                    mode="push-before",
                )
            return full_history_range(
                git,
                event_name=event_name,
                target=target,
                reason="push-base-unavailable-or-non-ancestor",
            )
        return full_history_range(
            git,
            event_name=event_name,
            target=target,
            reason="push-base-missing-or-zero",
        )

    if event_name == "workflow_dispatch":
        expected = require_sha(nested(payload, "inputs", "expected_head_sha"), "manual expected head")
        require(expected == github_sha, "manual expected head does not match workflow commit")
        require(checked_out_sha == expected, "checkout is not the exact manual expected head")
        supplied_base = nested(payload, "inputs", "comparison_base_sha") if "comparison_base_sha" in payload.get("inputs", {}) else ""
        if supplied_base not in (None, "", ZERO40):
            base = require_sha(supplied_base, "manual comparison base")
            return exact_range(
                git,
                event_name=event_name,
                target=expected,
                base=base,
                mode="manual-supplied-base",
            )
        parent = git.first_parent(expected)
        if parent is not None:
            return exact_range(
                git,
                event_name=event_name,
                target=expected,
                base=parent,
                mode="manual-first-parent",
            )
        return full_history_range(
            git,
            event_name=event_name,
            target=expected,
            reason="manual-root-commit",
        )

    raise SourceGateError(f"unsupported event: {event_name}")


def write_github_output(path: Path, context: ValidationContext) -> None:
    values = asdict(context)
    with path.open("a", encoding="utf-8") as stream:
        for key in (
            "target_sha",
            "comparison_base_sha",
            "comparison_mode",
            "diff_spec",
            "gitleaks_log_opts",
        ):
            value = values[key]
            stream.write(f"{key}={'' if value is None else value}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--event-path", type=Path, required=True)
    parser.add_argument("--github-sha", required=True)
    parser.add_argument("--github-ref", required=True)
    parser.add_argument("--checked-out-sha", required=True)
    parser.add_argument("--protected-branch", required=True)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--github-output", type=Path, required=True)
    return parser


def main() -> int:
    arguments = build_parser().parse_args()
    try:
        payload = json.loads(arguments.event_path.read_text(encoding="utf-8"))
        require(isinstance(payload, dict), "event payload must be a JSON object")
        context = resolve_context(
            event_name=arguments.event_name,
            payload=payload,
            github_sha=arguments.github_sha,
            github_ref=arguments.github_ref,
            checked_out_sha=arguments.checked_out_sha,
            protected_branch=arguments.protected_branch,
            git=Git(arguments.repository),
        )
        arguments.output.write_text(json.dumps(asdict(context), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        write_github_output(arguments.github_output, context)
        print(
            f"source validation context: target={context.target_sha} "
            f"mode={context.comparison_mode} diff={context.diff_spec}"
        )
        return 0
    except (OSError, json.JSONDecodeError, SourceGateError) as error:
        print(f"source validation context: FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
