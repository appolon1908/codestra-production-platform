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
    assert lock["source"] == "https://github.com/appolon1908-hue/Middleware-"
    assert lock["revision"] == "1aa4d505846b7494aff94bec3d7ea68c895e2dd3"
    assert lock["source_tree"] == "f67ed2eb19afc67dbe51624b5ba6298ec5dc5e32"
    assert lock["image"] == "ghcr.io/appolon1908-hue/codestra-middleware@sha256:cec8b5a1b0e713857be1dbc94b73780bf9ae1a200d0901f95cb62193b9c2f504"
    assert "@sha256:" in lock["image"]
    assert {service["image"] for service in services.values()} == {lock["image"]}


def test_runtime_effects_and_webphone_features_fail_closed() -> None:
    override = yaml.safe_load(
        (ROOT / "deploy/middleware/compose.approved-release.yaml").read_text()
    )
    for service in override["services"].values():
        environment = service["environment"]
        assert environment["WEBPHONE_ENDPOINT_ADAPTER_URL"] == ""
        for key in (
            "WEBPHONE_KEYCLOAK_ENABLED",
            "WEBPHONE_SESSION_ISSUER_ENABLED",
            "WEBPHONE_STAGING_PROVISIONING_ENABLED",
            "PRODUCTION_WEBRTC_ENABLED",
            "LIVE_EMAIL_DELIVERY",
            "LIVE_SMS_DELIVERY",
            "LIVE_PSTN_DIALING",
            "ODOO_WRITE",
            "N8N_DELIVERY_ENABLED",
        ):
            assert environment[key] == "false"


def test_release_cannot_deploy_before_source_lock_staging_and_canary() -> None:
    lock = json.loads(
        (ROOT / "deploy/middleware/approved-release-lock.json").read_text()
    )
    assert lock["required_database_head"] == "0009_observability_incidents"
    assert lock["external_effects_default"] == "disabled"
    assert lock["deployment_state"] == (
        "BLOCKED_PENDING_SOURCE_LOCK_STAGING_BACKUP_RESTORE_AND_CANARY"
    )
