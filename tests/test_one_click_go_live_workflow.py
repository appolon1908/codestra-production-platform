from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "one-click-go-live.yml"


def test_one_click_go_live_is_fail_closed_and_read_only() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    required = (
        "name: ONE CLICK — Go live read-only",
        "workflow_dispatch:",
        "GO_LIVE_READONLY",
        "PRODUCTION-SOURCE-LOCK.yaml is not PASS",
        "production source lock still contains blockers",
        "appolon1908-hue/Middleware-",
        "codestra/required-ci",
        "release.yml",
        "CODESTRA_RELEASE_ORCHESTRATOR_TOKEN",
        "appolon1908-hue/Infustruction-repo",
        "TARGET_WORKFLOW: one-click-go-live.yml",
        "0 < value <= 1",
        "rollback rehearsal",
        "gh run watch",
        "Only the bounded production read-only canary is activated",
        "Live writes, trading, money movement, payments, withdrawals, email, SMS, dialing, callbacks, and external provider execution remain disabled.",
    )
    for value in required:
        assert value in text, value

    forbidden = (
        "pull_request_target:",
        "enable-production-web-traffic",
        "production-activation.yml",
        "contents: write",
        "packages: write",
        "id-token: write",
        ":latest",
        "ssh ",
        "docker compose up",
        "tofu apply",
        "continue-on-error: true",
    )
    for value in forbidden:
        assert value not in text, value

    assert text.count("GO_LIVE_READONLY") >= 3
    assert "permissions:\n  contents: read" in text
    assert "github.ref == 'refs/heads/release/production-activation'" in text
    assert "candidate.get(\"deployment_authorized\") is not True" in text
    assert "TARGET_WORKFLOW: one-click-go-live.yml" in text


if __name__ == "__main__":
    test_one_click_go_live_is_fail_closed_and_read_only()
    print("ONE_CLICK_GO_LIVE_PLATFORM_POLICY=PASS")
