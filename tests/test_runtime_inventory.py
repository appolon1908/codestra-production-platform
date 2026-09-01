from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path


ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / "operations" / "runtime-inventory"
PROGRAM = PACKAGE / "codestra-runtime-inventory"
LOADER = importlib.machinery.SourceFileLoader("runtime_inventory", str(PROGRAM))
SPEC = importlib.util.spec_from_loader("runtime_inventory", LOADER)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def fixture_container() -> dict:
    return {
        "Name": "/codestra-api",
        "Image": "sha256:" + "a" * 64,
        "RestartCount": 0,
        "Config": {
            "Image": "ghcr.io/codestra/api@sha256:" + "b" * 64,
            "Labels": {
                "org.opencontainers.image.revision": "c" * 40,
                "org.opencontainers.image.version": "2026.09.1",
                "org.opencontainers.image.source": "https://github.com/example/repo",
                "com.codestra.release.id": "release-1",
                "unapproved.secret.label": "must-not-appear",
            },
            "Env": [
                "LIVE_EMAIL_DELIVERY=false",
                "PRODUCTION_DIALING=DISABLED",
                "DATABASE_PASSWORD=must-not-appear",
            ],
        },
        "State": {"Health": {"Status": "healthy"}},
        "NetworkSettings": {
            "Networks": {"private": {}, "edge": {}},
            "Ports": {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8095"}]},
        },
    }


def test_inventory_emits_only_fixed_sanitized_schema(monkeypatch) -> None:
    monkeypatch.setattr(MODULE, "docker_output", lambda *args: "container-id\n")

    def fake_docker(*args: str):
        assert args == ("inspect", "container-id")
        return [fixture_container()]

    monkeypatch.setattr(MODULE, "docker_json", fake_docker)
    result = MODULE.inventory()
    encoded = json.dumps(result)
    workload = result["workloads"][0]
    assert workload["name"] == "codestra-api"
    assert workload["immutable_reference"] is True
    assert workload["release"]["git_sha"] == "c" * 40
    assert workload["safety_flags"]["LIVE_EMAIL_DELIVERY"] == "false"
    assert workload["safety_flags"]["PRODUCTION_DIALING"] == "disabled"
    assert "must-not-appear" not in encoded
    assert result["summary"] == {
        "docker_runtime_inventory": "PASS",
        "immutable_images": {"passing": 1, "total": 1},
        "source_revision_exposed": {"passing": 1, "total": 1},
        "unknown_provenance_workloads": 0,
        "source_lock": "PASS",
    }


def test_mutable_or_unversioned_workload_fails_source_lock(monkeypatch) -> None:
    container = fixture_container()
    container["Config"]["Image"] = "ghcr.io/codestra/api:production"
    container["Config"]["Labels"].pop("org.opencontainers.image.revision")
    monkeypatch.setattr(MODULE, "docker_output", lambda *args: "id\n")
    monkeypatch.setattr(
        MODULE,
        "docker_json",
        lambda *args: [container],
    )
    summary = MODULE.inventory()["summary"]
    assert summary["immutable_images"] == {"passing": 0, "total": 1}
    assert summary["source_revision_exposed"] == {"passing": 0, "total": 1}
    assert summary["unknown_provenance_workloads"] == 1
    assert summary["source_lock"] == "FAIL"


def test_unknown_safety_value_is_not_echoed() -> None:
    result = MODULE.normalized_safety_flags(["LIVE_EMAIL_DELIVERY=unexpected-secretish-value"])
    assert result["LIVE_EMAIL_DELIVERY"] == "unknown"
    assert result["ENABLE_VICIDIAL_WRITES"] == "unknown"
    assert "unexpected-secretish-value" not in json.dumps(result)


def test_all_operational_write_gates_are_allowlisted_and_normalized() -> None:
    required = {
        "CALLBACK_DELIVERY_ENABLED",
        "CALLBACK_DISPATCH",
        "CALLBACK_DISPATCH_ENABLED",
        "ENABLE_EXTERNAL_DELIVERY",
        "ENABLE_VICIDIAL_WRITES",
        "EXTERNAL_DELIVERY_ENABLED",
        "GENERAL_AI_DIALING",
        "LIVE_CALL_CONTROL",
        "LIVE_EMAIL_DELIVERY",
        "LIVE_PSTN_DIALING",
        "LIVE_SMS_DELIVERY",
        "LIVE_WRITE",
        "N8N_DELIVERY_ENABLED",
        "ODOO_DELIVERY_ENABLED",
        "ODOO_WRITE",
        "ODOO_WRITE_ENABLED",
        "PRODUCTION_DIALING",
        "SEND_EVENTS",
        "VICIDIAL_WRITE_ENABLED",
        "VICIDIAL_WRITES_ENABLED",
    }
    assert required <= set(MODULE.SAFETY_FLAGS)
    result = MODULE.normalized_safety_flags(
        [f"{name}=false" for name in required]
    )
    assert all(result[name] == "false" for name in required)


def test_arguments_and_non_root_execution_fail_closed(monkeypatch) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    assert MODULE.main([]) == 2
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    assert MODULE.main(["inspect", "anything"]) == 2


def test_sudoers_is_group_scoped_and_exact() -> None:
    text = (PACKAGE / "codestra-runtime-inventory.sudoers").read_text()
    assert "NOPASSWD: ALL" not in text
    assert "%codestra-runtime-audit" in text
    assert '/usr/local/sbin/codestra-runtime-inventory ""' in text
    assert "docker" not in text.lower()


def test_installer_preserves_root_ownership_and_protected_modes() -> None:
    text = (PACKAGE / "install-runtime-inventory.sh").read_text()
    assert "install -o root -g root -m 0755" in text
    assert "install -o root -g root -m 0440" in text
    assert "visudo -cf" in text
    assert "chmod 666" not in text
