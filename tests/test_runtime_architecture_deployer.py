from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "tools/reconcile_runtime_architecture.py").read_text()


def test_deployer_has_fixed_complete_project_inventory():
    for project in (
        "codestra", "codestra-beyvra-email", "codestra-email-reseller",
        "codestra-integration-control-plane", "private-integration",
        "codestra-sms-api", "codestra-websocket-gateway",
    ):
        assert f'Project("{project}"' in SOURCE


def test_deployer_preflights_every_compose_model_before_mutation():
    assert "prepared = preflight()" in SOURCE
    assert '"config", "--quiet"' in SOURCE
    assert SOURCE.index("prepared = preflight()") < SOURCE.index("ensure_network(name)")


def test_provider_networks_are_egress_capable_and_governed():
    assert '("codestra-provider-email", "codestra-provider-sms", "codestra-provider-voice")' in SOURCE
    assert '"network", "create", "--driver", "bridge"' in SOURCE
    assert '["/usr/bin/docker", "network", "create", "--driver", "bridge", "--internal"]' not in SOURCE
    assert 'network.get("Internal") is not False' in SOURCE
    assert '"codestra.governance": "runtime-architecture-remediation.v1"' in SOURCE


def test_deployer_never_accepts_runtime_paths_or_projects():
    assert 'parser.add_argument("--apply"' in SOURCE
    assert 'parser.add_argument("--project"' not in SOURCE
    assert 'parser.add_argument("--file-path"' not in SOURCE
    assert '"--no-deps"' in SOURCE


def test_image_recreation_remains_digest_only():
    assert '"RepoDigests"' in SOURCE
    assert 'has no unique immutable image digest' in SOURCE
    assert 'return image.rsplit("@", 1)[1]' in SOURCE


def test_beyvra_worker_is_in_fixed_reconciliation_inventory():
    assert 'Project("codestra-beyvra-email", "codestra-beyvra-email-api-1", ("api", "worker")' in SOURCE


def test_apply_pass_requires_health_and_exact_network_readback():
    assert 'result["projects"][project.name] = verify_project(' in SOURCE
    assert 'row.get("State") != "running"' in SOURCE
    assert 'health not in {"", "healthy"}' in SOURCE
    assert 'actual_networks != desired_networks' in SOURCE
    assert SOURCE.index('verify_project(') < SOURCE.rindex('result["apply"] = "PASS"')
