import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_redis_exporter_is_authoritative_and_scraped() -> None:
    compose = yaml.safe_load(
        (ROOT / "operations/monitoring/compose.monitoring.yaml").read_text()
    )
    exporter = compose["services"]["redis-exporter"]
    assert "@sha256:" in exporter["image"]
    assert exporter["environment"]["REDIS_ADDR"] == "redis://redis:6379"
    assert exporter["environment"]["REDIS_USER"] == "redis-monitoring"
    assert exporter["environment"]["REDIS_PASSWORD_FILE"].startswith("/run/secrets/")
    assert exporter["read_only"] is True
    assert exporter["cap_drop"] == ["ALL"]

    prometheus = yaml.safe_load(
        (ROOT / "operations/monitoring/prometheus.yml").read_text()
    )
    jobs = {job["job_name"]: job for job in prometheus["scrape_configs"]}
    assert jobs["redis-exporter"]["static_configs"][0]["targets"] == [
        "redis-exporter:9121"
    ]


def test_odoo_contract_keeps_browser_private_and_api_boundaries_distinct() -> None:
    contract = json.loads(
        (ROOT / "config/odoo-production-contract.json").read_text()
    )
    assert contract["public_browser"]["host"] == "crm.codestra.agency"
    assert contract["public_browser"]["default_upstream"].endswith(":8069")
    assert contract["public_browser"]["realtime_upstream"].endswith(":8072")
    assert contract["private_integration"]["network"] == "codestra-internal-integration"
    assert contract["private_integration"]["outside_network_response"] == 403
    assert contract["private_integration"]["default_response"] == 404
    assert contract["kong_crm_api"]["path"] == "/v1/crm"


def test_odoo_private_contract_is_method_allowlisted() -> None:
    contract = json.loads(
        (ROOT / "config/odoo-production-contract.json").read_text()
    )
    routes = {
        (method, route["path"])
        for route in contract["private_integration"]["routes"]
        for method in route["methods"]
    }
    assert routes == {
        ("POST", "/api/v1/integration/results"),
        ("POST", "/codestra/api/v1/call-events"),
        ("GET", "/web/health"),
        ("HEAD", "/web/health"),
    }


def test_odoo_release_requires_source_and_revision_provenance() -> None:
    contract = json.loads(
        (ROOT / "config/odoo-production-contract.json").read_text()
    )
    assert contract["runtime_security"]["required_oci_labels"] == [
        "org.opencontainers.image.source",
        "org.opencontainers.image.revision",
    ]
