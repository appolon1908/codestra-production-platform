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


def test_authority_validation_runs_for_every_pull_request() -> None:
    triggers = workflow()["on"]
    assert "pull_request" in triggers
    assert triggers["pull_request"] in (None, "", {})


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
    for name in ("Gitleaks candidate tree", "Gitleaks pull-request commit range"):
        run = required_step(name)["run"]
        assert "--redact" in run
        assert "--exit-code 1" in run
    assert "check_integration_architecture.py" in required_step(
        "Enforce integration constitution"
    )["run"]
