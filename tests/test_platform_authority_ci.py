"""Keep the authority checks and unconditional release-branch CI after merges."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/platform-source-gate.yml"


def workflow() -> dict:
    # BaseLoader preserves the Actions `on` key instead of YAML 1.1 booleans.
    return yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def required_step(name: str) -> dict:
    job = workflow()["jobs"]["validate"]
    assert "if" not in job
    assert job.get("continue-on-error", "false") == "false"
    matches = [step for step in job["steps"] if step.get("name") == name]
    assert len(matches) == 1
    step = matches[0]
    assert "if" not in step
    assert step.get("continue-on-error", "false") == "false"
    return step


def test_authority_validation_runs_for_pr_protected_push_and_manual_exact_head() -> None:
    triggers = workflow()["on"]
    assert "pull_request" in triggers
    assert triggers["pull_request"] in (None, "", {})
    assert triggers["push"]["branches"] == ["release/production-activation"]
    manual = triggers["workflow_dispatch"]["inputs"]
    assert manual["expected_head_sha"]["required"] == "true"
    assert manual["comparison_base_sha"]["required"] == "false"


def test_checkout_and_range_resolution_are_bound_to_the_event_target() -> None:
    checkout = required_step("Check out exact validation target with complete history")
    assert "github.event.pull_request.head.sha" in checkout["with"]["ref"]
    assert checkout["with"]["fetch-depth"] == "0"

    resolver = required_step("Resolve exact validation target and comparison range")["run"]
    assert "tools/resolve_platform_source_gate.py" in resolver
    assert "--github-sha" in resolver
    assert "--checked-out-sha" in resolver
    assert "--event-path" in resolver

    protected = workflow()["jobs"]["validate"]["steps"]
    matches = [step for step in protected if step.get("name") == "Verify intended protected branch head"]
    assert len(matches) == 1
    verify = matches[0]
    assert "github.event_name == 'push'" in verify["if"]
    assert "github.event_name == 'workflow_dispatch'" in verify["if"]
    assert "release%2Fproduction-activation" in verify["run"]
    assert 'test "${observed}" = "${TARGET_SHA}"' in verify["run"]


def test_all_diff_and_history_checks_use_resolved_ranges() -> None:
    for name in (
        "Validate Git whitespace",
        "Reject forbidden artifacts and customer-data paths",
        "Confirm production feature defaults remain fail closed",
    ):
        step = required_step(name)
        assert step["env"]["DIFF_SPEC"] == "${{ steps.source-context.outputs.diff_spec }}"
        assert "DIFF_SPEC" in step["run"]
        assert "github.event.pull_request.base.sha" not in step["run"]

    gitleaks = required_step("Gitleaks resolved commit range")
    assert gitleaks["env"]["GITLEAKS_LOG_OPTS"] == "${{ steps.source-context.outputs.gitleaks_log_opts }}"
    assert '--log-opts="${GITLEAKS_LOG_OPTS}"' in gitleaks["run"]


def test_validate_is_the_real_job_and_no_status_is_manually_published() -> None:
    definition = workflow()
    job = definition["jobs"]["validate"]
    assert job["name"] == "validate"
    assert definition["permissions"] == {"contents": "read"}
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "/statuses/" not in source
    assert "statuses: write" not in source
    assert "state=success" not in source


def test_schema_dependency_is_installed_before_test_collection() -> None:
    steps = workflow()["jobs"]["validate"]["steps"]
    install = required_step("Install source-test dependencies")
    suite = required_step("Run complete clean-checkout platform suite")
    assert steps.index(install) < steps.index(suite)
    assert "jsonschema" in install["run"]
    assert "-m pytest -q" in suite["run"]
    assert "set -o pipefail" in suite["run"]


def test_both_platform_authority_and_release_schema_remain_required() -> None:
    run = required_step("Validate control-plane contracts and deployment")["run"]
    assert "release/platform-release-manifest.v1.schema.json" in run
    assert "Draft202012Validator.check_schema(platform_release_schema)" in run
    assert "python scripts/validate_platform_authority.py" in run
    assert "|| true" not in run


def test_secret_scans_and_architecture_checks_remain_required() -> None:
    for name in ("Gitleaks candidate tree", "Gitleaks resolved commit range"):
        run = required_step(name)["run"]
        assert "--redact" in run
        assert "--exit-code 1" in run
    assert "check_integration_architecture.py" in required_step(
        "Enforce integration constitution"
    )["run"]
