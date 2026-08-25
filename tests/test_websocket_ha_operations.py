from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]
PROMETHEUS = yaml.safe_load((ROOT / "operations/monitoring/prometheus.yml").read_text())
RUNBOOK = (ROOT / "operations/runbooks/websocket-ha-failover.md").read_text()


def test_websocket_primary_and_standby_are_scraped_and_probed() -> None:
    jobs = {item["job_name"]: item for item in PROMETHEUS["scrape_configs"]}
    scrape = jobs["websocket_gateway"]
    targets = {
        target
        for group in scrape["static_configs"]
        for target in group["targets"]
    }
    assert targets == {
        "codestra-websocket-gateway-gateway-1:8080",
        "websocket-standby:8080",
    }
    readiness = jobs["websocket_readiness"]
    probes = {
        target
        for group in readiness["static_configs"]
        for target in group["targets"]
    }
    assert probes == {
        "https://api.codestra.agency/readyz",
        "http://websocket-standby:8080/readyz",
    }


def test_failover_runbook_is_fail_closed_and_reversible() -> None:
    for field in (
        "CHANGE_ID=",
        "OWNER=",
        "PRIMARY_TARGET=127.0.0.1:18102",
        "STANDBY_TARGET=127.0.0.1:31882",
        "TRAFFIC_SWITCH_COMMAND=",
        "CONFIG_VALIDATION=",
        "RELOAD_COMMAND=",
        "WSS_VALID_AUTH_TEST=",
        "MONITORING_CHECK=",
        "ROLLBACK_TRIGGER=",
        "ROLLBACK_COMMAND=",
        "FAILBACK_COMMAND=",
        "RTO_TARGET=",
        "SUCCESS_CRITERIA=",
    ):
        assert field in RUNBOOK
    assert "Do not switch traffic" in RUNBOOK
    assert "database state synchronization" in RUNBOOK
