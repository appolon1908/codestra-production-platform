#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "deploy/middleware/compose.appolon-integration-api.yaml"
LOCK = ROOT / "deploy/middleware/appolon-integration-api-lock.json"
EXPECTED_IMAGE = "ghcr.io/appolon1908-hue/codestra-middleware@sha256:d9bbdda6b13983b429fdb063f500474421da9e14884c03415101a17a49e887f4"
DISABLED = {
    "OUTBOX_DISPATCH_ENABLED",
    "ODOO_WRITE",
    "LIVE_WRITE",
    "ENABLE_EXTERNAL_DELIVERY",
    "N8N_DELIVERY_ENABLED",
    "CALLBACK_DISPATCH",
    "LIVE_SMS_DELIVERY",
    "LIVE_EMAIL_DELIVERY",
    "LIVE_PSTN_DIALING",
    "SEND_EVENTS",
    "ODOO_DELIVERY_ENABLED",
    "ENABLE_VICIDIAL_WRITES",
    "LIVE_CALL_CONTROL",
    "GENERAL_AI_DIALING",
    "LIVE_WRITES",
    "VICIDIAL_WRITES_ENABLED",
    "EXTERNAL_DIAL_ENABLED",
    "PRODUCTION_CALLBACKS_ENABLED",
    "N8N_PRODUCTION_WORKFLOWS_ENABLED",
    "FORM_ODOO_DELIVERY_ENABLED",
    "CRAWLER_ODOO_DELIVERY_ENABLED",
    "SCRAPPER_ODOO_DELIVERY_ENABLED",
    "CRAWLER_EXTERNAL_CONTACT_ENABLED",
    "SCRAPPER_EXTERNAL_CONTACT_ENABLED",
    "SMS_DELIVERY_ENABLED",
    "EMAIL_DELIVERY_ENABLED",
    "SOCIAL_DELIVERY_ENABLED",
    "CRAWLER_EXECUTION_ENABLED",
    "SCRAPPER_EXECUTION_ENABLED",
    "UNRESTRICTED_CRAWLING",
}
SECRET_PATTERN = re.compile(r"(?i)(password|client_secret|private_key|access_token)\s*[:=]\s*[^\s$<{]+")


def validate() -> None:
    raw = COMPOSE.read_text(encoding="utf-8")
    compose = yaml.safe_load(raw)
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    assert "middleware-integration-api" not in compose["services"]
    service = compose["services"]["appolon-middleware-integration-api"]
    assert service["image"] == EXPECTED_IMAGE == lock["image"]
    assert lock["service"] == "appolon-middleware-integration-api"
    assert service.get("command") is None
    assert service.get("entrypoint") is None
    assert "ports" not in service
    assert service["expose"] == ["8080"]
    assert service["networks"]["kong_backend"]["aliases"] == ["middleware-integration-api"]
    assert compose["networks"]["kong_backend"] == {
        "name": "codestra-kong_kong_backend",
        "external": True,
    }
    environment = service["environment"]
    assert all(environment[name] == "false" for name in DISABLED)
    assert environment["APP_ENV"] == "production"
    assert environment["RUNTIME_PROFILE_ID"] == "codestra-middleware-production-compose-v1"
    assert environment["APP_SOURCE_SHA"] == "24a86223d850a77cce3b72644e9fad7ff4f9acb0"
    assert environment["IMAGE_DIGEST"] == "sha256:d9bbdda6b13983b429fdb063f500474421da9e14884c03415101a17a49e887f4"
    assert environment["BUILD_TIME"] == "2026-08-30T12:50:23Z"
    assert environment["PRODUCTION_DIALING"] == "DISABLED"
    assert service["env_file"] == [{
        "path": "/etc/codestra/secrets/appolon-middleware-production.env",
        "required": True,
    }]
    assert SECRET_PATTERN.search(raw) is None
    assert lock["source"] == "https://github.com/appolon1908-hue/Middleware-"
    assert lock["revision"] == "24a86223d850a77cce3b72644e9fad7ff4f9acb0"
    assert lock["release_run"] == 33312550094
    assert lock["runtime_profile"] == "codestra-middleware-production-compose-v1"
    assert lock["production_writes_enabled"] is False
    assert lock["deployment_state"] == "REPOSITORY_ALIGNED_NOT_APPLIED"
    assert lock["rollback"]["requires_separate_protected_apply"] is True
    assert lock["rollback"]["action"] == "remove_appolon_service_and_preserve_legacy_runtime"
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", lock["rollback"]["previous_image_digest"])


if __name__ == "__main__":
    validate()
    print("APPOLON_MIDDLEWARE_MANIFEST=PASS")
