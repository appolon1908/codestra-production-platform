from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/resolve_platform_source_gate.py"
SPEC = importlib.util.spec_from_file_location("resolve_platform_source_gate", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def git(repository: Path, *arguments: str) -> str:
    return subprocess.check_output(
        ["git", *arguments], cwd=repository, text=True
    ).strip()


def repository_with_two_commits(tmp_path: Path) -> tuple[Path, str, str]:
    repository = tmp_path / "repository"
    repository.mkdir()
    git(repository, "init", "-q")
    git(repository, "config", "user.name", "Source Gate Test")
    git(repository, "config", "user.email", "source-gate@example.invalid")
    tracked = repository / "tracked.txt"
    tracked.write_text("base\n", encoding="utf-8")
    git(repository, "add", "tracked.txt")
    git(repository, "commit", "-qm", "base")
    base = git(repository, "rev-parse", "HEAD")
    tracked.write_text("head\n", encoding="utf-8")
    git(repository, "commit", "-qam", "head")
    head = git(repository, "rev-parse", "HEAD")
    return repository, base, head


def resolve(
    repository: Path,
    *,
    event_name: str,
    payload: dict,
    github_sha: str,
    checked_out_sha: str,
    github_ref: str = "refs/heads/release/production-activation",
):
    return MODULE.resolve_context(
        event_name=event_name,
        payload=payload,
        github_sha=github_sha,
        github_ref=github_ref,
        checked_out_sha=checked_out_sha,
        protected_branch="release/production-activation",
        git=MODULE.Git(repository),
    )


def test_pull_request_uses_exact_head_and_merge_base(tmp_path: Path) -> None:
    repository, base, head = repository_with_two_commits(tmp_path)
    result = resolve(
        repository,
        event_name="pull_request",
        payload={"pull_request": {"base": {"sha": base}, "head": {"sha": head}}},
        github_sha="f" * 40,
        checked_out_sha=head,
        github_ref="refs/pull/1/merge",
    )
    assert result.target_sha == head
    assert result.comparison_mode == "pull-request-merge-base"
    assert result.diff_spec == f"{base}..{head}"
    assert result.gitleaks_log_opts == result.diff_spec


def test_pull_request_with_advanced_base_uses_common_ancestor(tmp_path: Path) -> None:
    repository, base, head = repository_with_two_commits(tmp_path)
    git(repository, "checkout", "-qb", "advanced-base", base)
    (repository / "base-only.txt").write_text("advanced\n", encoding="utf-8")
    git(repository, "add", "base-only.txt")
    git(repository, "commit", "-qm", "advance base")
    advanced_base = git(repository, "rev-parse", "HEAD")
    git(repository, "checkout", "-q", head)

    result = resolve(
        repository,
        event_name="pull_request",
        payload={
            "pull_request": {
                "base": {"sha": advanced_base},
                "head": {"sha": head},
            }
        },
        github_sha="f" * 40,
        checked_out_sha=head,
        github_ref="refs/pull/1/merge",
    )

    assert result.comparison_base_sha == base
    assert result.comparison_mode == "pull-request-merge-base"
    assert result.diff_spec == f"{base}..{head}"


def test_pull_request_with_unrelated_base_fails(tmp_path: Path) -> None:
    repository, _, head = repository_with_two_commits(tmp_path)
    git(repository, "checkout", "--orphan", "unrelated")
    git(repository, "rm", "-qf", "tracked.txt")
    (repository / "unrelated.txt").write_text("unrelated\n", encoding="utf-8")
    git(repository, "add", "unrelated.txt")
    git(repository, "commit", "-qm", "unrelated base")
    unrelated = git(repository, "rev-parse", "HEAD")

    with pytest.raises(MODULE.SourceGateError, match="merge-base"):
        resolve(
            repository,
            event_name="pull_request",
            payload={
                "pull_request": {
                    "base": {"sha": unrelated},
                    "head": {"sha": head},
                }
            },
            github_sha="f" * 40,
            checked_out_sha=head,
            github_ref="refs/pull/1/merge",
        )


@pytest.mark.parametrize("base", ["", "0" * 40, "a" * 40])
def test_pull_request_missing_zero_or_unavailable_base_fails(
    tmp_path: Path, base: str
) -> None:
    repository, _, head = repository_with_two_commits(tmp_path)
    with pytest.raises(MODULE.SourceGateError):
        resolve(
            repository,
            event_name="pull_request",
            payload={"pull_request": {"base": {"sha": base}, "head": {"sha": head}}},
            github_sha="f" * 40,
            checked_out_sha=head,
            github_ref="refs/pull/1/merge",
        )


def test_protected_push_uses_before_sha(tmp_path: Path) -> None:
    repository, base, head = repository_with_two_commits(tmp_path)
    result = resolve(
        repository,
        event_name="push",
        payload={"before": base, "after": head},
        github_sha=head,
        checked_out_sha=head,
    )
    assert result.comparison_mode == "push-before"
    assert result.diff_spec == f"{base}..{head}"


@pytest.mark.parametrize(
    ("before", "reason"),
    [
        ("", "push-base-missing-or-zero"),
        ("0" * 40, "push-base-missing-or-zero"),
        ("a" * 40, "push-base-unavailable-or-non-ancestor"),
    ],
)
def test_protected_push_falls_back_to_full_security_scan(
    tmp_path: Path, before: str, reason: str
) -> None:
    repository, _, head = repository_with_two_commits(tmp_path)
    result = resolve(
        repository,
        event_name="push",
        payload={"before": before, "after": head},
        github_sha=head,
        checked_out_sha=head,
    )
    assert result.comparison_mode == f"full-history:{reason}"
    assert result.comparison_base_sha is None
    assert result.diff_spec.endswith(f"..{head}")
    assert result.gitleaks_log_opts == head


def test_manual_exact_head_defaults_to_first_parent(tmp_path: Path) -> None:
    repository, base, head = repository_with_two_commits(tmp_path)
    result = resolve(
        repository,
        event_name="workflow_dispatch",
        payload={"inputs": {"expected_head_sha": head, "comparison_base_sha": ""}},
        github_sha=head,
        checked_out_sha=head,
    )
    assert result.comparison_mode == "manual-first-parent"
    assert result.diff_spec == f"{base}..{head}"


def test_manual_wrong_expected_head_fails(tmp_path: Path) -> None:
    repository, base, head = repository_with_two_commits(tmp_path)
    with pytest.raises(MODULE.SourceGateError, match="does not match workflow commit"):
        resolve(
            repository,
            event_name="workflow_dispatch",
            payload={"inputs": {"expected_head_sha": base, "comparison_base_sha": ""}},
            github_sha=head,
            checked_out_sha=head,
        )


def test_manual_unavailable_explicit_base_fails(tmp_path: Path) -> None:
    repository, _, head = repository_with_two_commits(tmp_path)
    with pytest.raises(MODULE.SourceGateError, match="comparison base is unavailable"):
        resolve(
            repository,
            event_name="workflow_dispatch",
            payload={"inputs": {"expected_head_sha": head, "comparison_base_sha": "a" * 40}},
            github_sha=head,
            checked_out_sha=head,
        )


def test_manual_root_commit_uses_full_history(tmp_path: Path) -> None:
    repository, root, _ = repository_with_two_commits(tmp_path)
    git(repository, "checkout", "-q", root)
    result = resolve(
        repository,
        event_name="workflow_dispatch",
        payload={"inputs": {"expected_head_sha": root, "comparison_base_sha": "0" * 40}},
        github_sha=root,
        checked_out_sha=root,
    )
    assert result.comparison_mode == "full-history:manual-root-commit"
    assert result.gitleaks_log_opts == root


def test_push_or_manual_wrong_branch_fails(tmp_path: Path) -> None:
    repository, _, head = repository_with_two_commits(tmp_path)
    with pytest.raises(MODULE.SourceGateError, match="must run from"):
        resolve(
            repository,
            event_name="push",
            payload={"before": "0" * 40, "after": head},
            github_sha=head,
            checked_out_sha=head,
            github_ref="refs/heads/main",
        )
