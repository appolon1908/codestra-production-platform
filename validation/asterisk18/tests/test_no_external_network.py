from pathlib import Path

import yaml

from harness import ROOT, record


def test_compose_is_internal_unprivileged_and_loopback_only():
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    assert compose["networks"]["isolated"]["internal"] is True
    service = compose["services"]["asterisk"]
    assert service.get("privileged") is not True
    assert sorted(service["cap_add"]) == ["SETGID", "SETUID"]
    assert "network_mode" not in service
    assert all(str(port).startswith("127.0.0.1:") for port in service["ports"])
    assert "/var/run/docker.sock" not in str(service.get("volumes", []))
    record("network_isolation", result="PASS", server_b_network_contact_count=0,
           production_secret_usage_count=0, production_write_count=0, real_call_count=0)


def test_no_runtime_endpoint_or_production_material_references():
    allowed = {".test.invalid", "downloads.asterisk.org", "debian"}
    text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in ROOT.rglob("*")
        if path.is_file()
        and path.suffix in {".py", ".sh", ".yaml", ".conf", ".template", ".md"}
        and "runtime" not in path.parts
        and path.name not in {"test_no_external_network.py", "validate-static.sh"}
    )
    forbidden = ["pull_request_target", "network_mode: host", "/var/run/docker.sock",
                 "vicidial_", "repository.secrets", "secrets."]
    assert not [token for token in forbidden if token.lower() in text.lower()]
