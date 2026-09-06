from pathlib import Path


WORKFLOW = Path(__file__).parents[1] / ".github/workflows/ghcr-deployment-preflight.yml"
TEXT = WORKFLOW.read_text(encoding="utf-8")


def test_preflight_is_manual_environment_gated_and_read_only() -> None:
    assert "workflow_dispatch:" in TEXT
    assert "environment: production" in TEXT
    assert "contents: read" in TEXT
    assert "packages: write" not in TEXT
    assert "push:" not in TEXT


def test_preflight_uses_only_protected_secret_and_exact_digest() -> None:
    assert "secrets.CODESTRA_GHCR_DEPLOYMENT_READ_TOKEN" in TEXT
    assert 'test -n "${GHCR_TOKEN}"' in TEXT
    assert 'ghcr.io/appolon1908-hue/codestra-middleware@${IMAGE_DIGEST}' in TEXT
    assert 'middleware_image_digest"] == sys.argv[3]' in TEXT
    assert "docker pull --quiet" in TEXT
    assert "docker push" not in TEXT


def test_preflight_has_no_deployment_or_telephony_action() -> None:
    assert "ssh " not in TEXT
    assert "kubectl " not in TEXT
    assert "DEPLOYMENT_PERFORMED=NO" in TEXT
    assert "PSTN_DIALING=DISABLED" in TEXT
    assert "CALLS_PLACED=0" in TEXT
