import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_all_runtime_services_use_one_approved_immutable_image() -> None:
    lock = json.loads(
        (ROOT / "deploy/middleware/approved-release-lock.json").read_text()
    )
    override = yaml.safe_load(
        (ROOT / "deploy/middleware/compose.approved-release.yaml").read_text()
    )
    services = override["services"]
    assert len(services) == 18
    assert "@sha256:" in lock["image"]
    assert {service["image"] for service in services.values()} == {lock["image"]}


def test_stale_webphone_endpoint_and_features_fail_closed() -> None:
    override = yaml.safe_load(
        (ROOT / "deploy/middleware/compose.approved-release.yaml").read_text()
    )
    for service in override["services"].values():
        environment = service["environment"]
        assert environment["WEBPHONE_ENDPOINT_ADAPTER_URL"] == ""
        assert environment["WEBPHONE_KEYCLOAK_ENABLED"] == "false"
        assert environment["WEBPHONE_SESSION_ISSUER_ENABLED"] == "false"
        assert environment["WEBPHONE_STAGING_PROVISIONING_ENABLED"] == "false"
        assert environment["PRODUCTION_WEBRTC_ENABLED"] == "false"


def test_release_cannot_deploy_before_required_database_head() -> None:
    lock = json.loads(
        (ROOT / "deploy/middleware/approved-release-lock.json").read_text()
    )
    assert lock["required_database_head"] == "0010_realtime_gateway"
    assert lock["deployment_state"].startswith("BLOCKED_PENDING_")
