import json
from pathlib import Path
import subprocess

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
    assert jobs["redis"]["static_configs"][0]["targets"] == [
        "redis-exporter:9121"
    ]


def test_redis_alerts_fail_closed_and_cover_required_categories() -> None:
    rules = yaml.safe_load(
        (ROOT / "operations/monitoring/rules/redis-production.rules.yml").read_text()
    )
    alerts = {rule["alert"]: rule for rule in rules["groups"][0]["rules"]}
    assert set(alerts) == {
        "RedisExporterMissing",
        "RedisDown",
        "RedisAuthenticationFailure",
        "RedisRejectedConnections",
        "RedisBlockedClients",
        "RedisMemoryWarning",
        "RedisMemoryCritical",
        "RedisEvictions",
        "RedisAOFFailure",
        "RedisRDBFailure",
        "RedisPersistenceStale",
        "RedisUnexpectedReplicaState",
    }
    assert "absent(up{job=\"redis\"})" in alerts["RedisExporterMissing"]["expr"]
    assert "absent(redis_up{job=\"redis\"})" in alerts["RedisDown"]["expr"]


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


def test_canonical_odoo_compose_has_no_public_ports_and_order_is_explicit() -> None:
    deploy = ROOT / "deploy/odoo"
    order = (deploy / "compose-order.txt").read_text().splitlines()
    assert order == [
        "compose.production.yaml",
        "overrides/feature-policy.yaml",
        "overrides/integration-trust.yaml",
    ]
    base = yaml.safe_load((deploy / order[0]).read_text())
    service = base["services"]["odoo"]
    assert "ports" not in service
    assert service["restart"] == "unless-stopped"
    assert service["healthcheck"]["test"][-1].endswith("|| exit 1")
    assert set(service["networks"]) == {
        "backend",
        "edge",
        "identity",
        "internal-integration",
    }


def test_all_live_odoo_layers_are_classified() -> None:
    inventory = json.loads(
        (ROOT / "deploy/odoo/live-layer-inventory.json").read_text()
    )
    assert inventory["unknown_layers"] == 0
    assert [layer["order"] for layer in inventory["layers"]] == list(range(1, 11))
    assert all(layer["classification"] != "UNKNOWN" for layer in inventory["layers"])


def test_odoo_container_classifier_has_no_unknown_runtime_entries() -> None:
    result = subprocess.run(
        ["python3", str(ROOT / "scripts/classify_odoo_containers.py")],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "ODOO_UNKNOWN_HISTORICAL_CONTAINERS=0" in result.stdout
    assert "ODOO_CLEANUP_APPROVED_COUNT=0" in result.stdout


def test_odoo_contract_is_enforced_by_deployment_preflight() -> None:
    validator = (ROOT / "scripts/validate_odoo_production_contract.py").read_text()
    assert '"@sha256:" not in args.image' in validator
    assert "org.opencontainers.image.source" in validator
    assert "org.opencontainers.image.revision" in validator
    assert "ODOO_PUBLIC_PORT_EXPOSURE" in validator
    assert "scripts/test_odoo_private_allowlist.sh" in validator
