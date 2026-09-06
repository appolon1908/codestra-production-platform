from fastapi.routing import APIRoute
from pathlib import Path

import yaml

from mail_platform.api import app as mail_app
from reseller_portal import app as portal_module


def paths(app):
    return {route.path for route in app.routes if isinstance(route, APIRoute)}


def test_mail_api_has_liveness_readiness_and_real_metrics():
    assert {"/healthz", "/healthz/ready"} <= paths(mail_app)
    assert any(route.path == "/metrics" for route in mail_app.routes)
    assert mail_app.user_middleware


def test_portal_has_liveness_readiness_and_real_metrics():
    assert {"/healthz", "/readyz"} <= paths(portal_module.app)
    assert any(route.path == "/metrics" for route in portal_module.app.routes)
    assert portal_module.app.user_middleware


def test_portal_readiness_fails_closed_without_postgres(monkeypatch):
    monkeypatch.setattr(portal_module, "repository", None)
    try:
        portal_module.readyz()
    except Exception as error:
        assert getattr(error, "status_code", None) == 503
    else:
        raise AssertionError("readiness accepted missing PostgreSQL authority")


def test_portal_readiness_uses_database_probe(monkeypatch):
    class Repository:
        def ready(self):
            return True

    monkeypatch.setattr(portal_module, "repository", Repository())
    assert portal_module.readyz()["status"] == "ready"


def test_monitoring_scrapes_and_alerts_on_both_applications():
    root = Path(__file__).resolve().parents[1]
    prometheus = yaml.safe_load(
        (root / "operations/monitoring/prometheus.yml").read_text()
    )
    jobs = {job["job_name"]: job for job in prometheus["scrape_configs"]}
    assert jobs["codestra-mail-api"]["static_configs"][0]["targets"] == [
        "codestra-mail-api:8098"
    ]
    assert jobs["codestra-reseller-portal"]["static_configs"][0]["targets"] == [
        "portal:8080"
    ]
    assert len(
        jobs["codestra-middleware-runtimes"]["static_configs"][0]["targets"]
    ) == 15
    readiness = jobs["blackbox_application_readiness"]["static_configs"]
    assert {item["labels"]["application"] for item in readiness} == {
        "mail-api",
        "reseller-portal",
    }
    rules = (root / "operations/monitoring/rules/application-http.rules.yml").read_text()
    for alert in (
        "CodestraApplicationMetricsUnavailable",
        "CodestraApplicationReadinessFailed",
        "CodestraApplicationHttp5xx",
        "CodestraApplicationHttpLatencyHigh",
    ):
        assert f"alert: {alert}" in rules
    compose = yaml.safe_load(
        (root / "operations/monitoring/compose.monitoring.yaml").read_text()
    )
    assert compose["services"]["blackbox"]["networks"] == [
        "monitoring",
        "backend",
        "edge",
    ]
    assert compose["services"]["node-exporter"]["networks"] == ["monitoring"]
    assert 'up{job="blackbox_application_readiness"} == 0' in rules
