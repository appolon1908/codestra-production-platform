#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "deploy/middleware/compose.appolon-integration-api.yaml"
LOCK = ROOT / "deploy/middleware/appolon-integration-api-lock.json"
EXPECTED_IMAGE = "ghcr.io/appolon1908-hue/codestra-middleware@sha256:a5c508fea8634351fb1bdd11e22a6cea520e436355cba3305456a07a3e0a2484"
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
    assert environment["APP_SOURCE_SHA"] == "f3437709c06747249586598590145234ea2c7327"
    assert environment["IMAGE_DIGEST"] == "sha256:a5c508fea8634351fb1bdd11e22a6cea520e436355cba3305456a07a3e0a2484"
    assert environment["BUILD_TIME"] == "2026-09-02T10:04:02Z"
    assert environment["PRODUCTION_DIALING"] == "DISABLED"
    assert service["env_file"] == [{
        "path": "/etc/codestra/secrets/appolon-middleware-production.env",
        "required": True,
    }]
    assert SECRET_PATTERN.search(raw) is None
    assert lock["source"] == "https://github.com/appolon1908-hue/Middleware-"
    assert lock["revision"] == "f3437709c06747249586598590145234ea2c7327"
    assert lock["release_run"] == 33617485810
    assert lock["runtime_profile"] == "codestra-middleware-production-compose-v1"
    assert lock["database_name"] == "codestra_middleware_appolon"
    assert lock["database_role"] == "appolon_middleware_api"
    assert lock["production_writes_enabled"] is False
    assert lock["deployment_state"] == "ISOLATED_DATABASE_REVIEW_REQUIRED"
    assert lock["rollback"]["requires_separate_protected_apply"] is True
    assert lock["rollback"]["action"] == "redeploy_previous_appolon_image_digest"
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", lock["rollback"]["previous_image_digest"])


if __name__ == "__main__":
    validate()
    print("APPOLON_MIDDLEWARE_MANIFEST=PASS")
