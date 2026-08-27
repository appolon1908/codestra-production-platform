from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "verify_kong_source_lock",
    ROOT / "tools" / "verify_kong_source_lock.py",
)
assert SPEC and SPEC.loader
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)
LOCK = json.loads((ROOT / "config" / "kong-source.lock.json").read_text())


POLICY = """
local required = "platform.admin"
kong.service.request.set_header("X-Authenticated-Role", "platform_admin")
kong.service.request.set_header("X-Authenticated-Role", "tenant_admin")
""".strip()


def kong_document() -> dict:
    security = LOCK["security_contracts"]["system_admin"]
    routes = [
        {
            "name": row["route"],
            "hosts": row["hosts"],
            "paths": row["paths"],
            "methods": row["methods"],
            "strip_path": False,
        }
        for row in LOCK["public_routes"]
    ]
    return {
        "_format_version": "3.0",
        "services": [
            {
                "name": security["service"],
                "url": "http://codestra-control-plane:8096",
                "routes": routes,
                "plugins": [
                    {
                        "name": "openid-connect",
                        "config": copy.deepcopy(
                            security["openid_connect_config"]
                        ),
                    },
                    {
                        "name": "pre-function",
                        "config": {"access": [POLICY]},
                    },
                ],
            }
        ],
    }


def remote_payloads(lock: dict, kong: dict | None = None) -> dict[str, str]:
    base = (
        "https://raw.githubusercontent.com/"
        f"{lock['repository']}/{lock['commit']}"
    )
    manifest = {
        "schema": lock["manifest_schema"],
        "target_repository": lock["repository"],
        "source_protected_sha": lock["source_platform_sha"],
        "source_route_sha": lock["source_route_sha"],
        "files": [{"path": path} for path in lock["required_paths"]],
    }
    payloads = {
        f"{base}/{lock['manifest_path']}": json.dumps(manifest),
        f"{base}/deploy/kong/control-plane.yml": yaml.safe_dump(
            kong or kong_document()
        ),
        f"{base}/deploy/kong/scope-policy.lua": POLICY,
    }
    for contract in lock["external_route_contracts"].values():
        payloads[f"{base}/{contract['path']}"] = json.dumps(
            contract["document"]
        )
    return payloads


def install_remote(monkeypatch, payloads: dict[str, str]) -> None:
    def fake_fetch(url: str) -> str:
        try:
            return payloads[url]
        except KeyError as exc:
            raise VERIFIER.SourceLockError(
                f"missing pinned test resource: {url}"
            ) from exc

    monkeypatch.setattr(VERIFIER, "fetch_text", fake_fetch)


def test_valid_admin_route_inherits_exact_security_chain() -> None:
    contract = LOCK["security_contracts"]["system_admin"]
    VERIFIER.verify_admin_security(kong_document(), POLICY, contract)


@pytest.mark.parametrize("plugin_name", ["openid-connect", "pre-function"])
def test_detached_security_plugin_fails_closed(plugin_name: str) -> None:
    document = kong_document()
    service = document["services"][0]
    service["plugins"] = [
        row for row in service["plugins"] if row["name"] != plugin_name
    ]
    with pytest.raises(VERIFIER.SourceLockError):
        VERIFIER.verify_admin_security(
            document,
            POLICY,
            LOCK["security_contracts"]["system_admin"],
        )


def test_duplicate_or_shadowed_security_plugin_fails_closed() -> None:
    document = kong_document()
    admin = next(
        row
        for row in document["services"][0]["routes"]
        if row["name"] == "control-plane-system-admin"
    )
    admin["plugins"] = [
        {
            "name": "openid-connect",
            "config": copy.deepcopy(
                LOCK["security_contracts"]["system_admin"][
                    "openid_connect_config"
                ]
            ),
        }
    ]
    with pytest.raises(VERIFIER.SourceLockError):
        VERIFIER.verify_admin_security(
            document,
            POLICY,
            LOCK["security_contracts"]["system_admin"],
        )


def test_admin_route_moved_to_unsecured_service_fails_closed() -> None:
    document = kong_document()
    secured = document["services"][0]
    admin = next(
        row
        for row in secured["routes"]
        if row["name"] == "control-plane-system-admin"
    )
    secured["routes"].remove(admin)
    document["services"].append(
        {
            "name": "unsecured-admin",
            "url": "http://unsecured:8096",
            "routes": [admin],
        }
    )
    with pytest.raises(VERIFIER.SourceLockError):
        VERIFIER.verify_admin_security(
            document,
            POLICY,
            LOCK["security_contracts"]["system_admin"],
        )


def test_inline_policy_drift_fails_even_when_policy_file_is_unchanged() -> None:
    document = kong_document()
    pre_function = next(
        row
        for row in document["services"][0]["plugins"]
        if row["name"] == "pre-function"
    )
    pre_function["config"]["access"][0] = POLICY.replace(
        "platform.admin", "platform.read"
    )
    with pytest.raises(VERIFIER.SourceLockError):
        VERIFIER.verify_admin_security(
            document,
            POLICY,
            LOCK["security_contracts"]["system_admin"],
        )


@pytest.mark.parametrize(
    ("contract_name", "mutator"),
    [
        ("callback", lambda row: row.__setitem__("host", "legacy.invalid")),
        (
            "callback",
            lambda row: row["service"].__setitem__("host", "wrong-upstream"),
        ),
        (
            "callback",
            lambda row: row.__setitem__("audience", "wrong-audience"),
        ),
        ("callback", lambda row: row.__setitem__("tenant", "OTHER")),
        (
            "callback",
            lambda row: row["routes"][0].__setitem__("methods", ["GET"]),
        ),
        (
            "callback",
            lambda row: row["routes"][0].__setitem__(
                "requiredScope", "callbacks.read"
            ),
        ),
        (
            "callback",
            lambda row: row["routes"][0].__setitem__("ratePerMinute", 1),
        ),
        (
            "campaign_automation",
            lambda row: row.__setitem__("host", "legacy.invalid"),
        ),
        (
            "campaign_automation",
            lambda row: row["service"].__setitem__("host", "wrong-upstream"),
        ),
        (
            "campaign_automation",
            lambda row: row.__setitem__("audience", "wrong-audience"),
        ),
        (
            "campaign_automation",
            lambda row: row.__setitem__("environment", "staging"),
        ),
        (
            "campaign_automation",
            lambda row: row["routes"][0].__setitem__("path", "/wrong"),
        ),
        (
            "campaign_automation",
            lambda row: row["routes"][0].__setitem__(
                "scope", "n8n.results.submit"
            ),
        ),
        (
            "campaign_automation",
            lambda row: row["routes"][0].__setitem__("rate_per_minute", 1),
        ),
        (
            "campaign_automation",
            lambda row: row["routes"][0].__setitem__("max_body_mb", 9),
        ),
    ],
)
def test_callback_and_campaign_contract_drift_fails_closed(
    contract_name: str,
    mutator,
) -> None:
    expected = LOCK["external_route_contracts"][contract_name]["document"]
    actual = copy.deepcopy(expected)
    mutator(actual)
    with pytest.raises(VERIFIER.SourceLockError):
        VERIFIER.verify_exact_contract(contract_name, actual, expected)


def test_added_or_removed_contract_field_fails_closed() -> None:
    expected = LOCK["external_route_contracts"]["callback"]["document"]
    added = copy.deepcopy(expected)
    added["unreviewed"] = True
    removed = copy.deepcopy(expected)
    removed.pop("campaign")
    for actual in (added, removed):
        with pytest.raises(VERIFIER.SourceLockError):
            VERIFIER.verify_exact_contract("callback", actual, expected)


@pytest.mark.parametrize(
    "contract_name",
    ["callback", "campaign_automation"],
)
def test_missing_remote_contract_file_fails_closed(
    monkeypatch,
    contract_name: str,
) -> None:
    payloads = remote_payloads(LOCK)
    contract = LOCK["external_route_contracts"][contract_name]
    base = (
        "https://raw.githubusercontent.com/"
        f"{LOCK['repository']}/{LOCK['commit']}"
    )
    payloads.pop(f"{base}/{contract['path']}")
    install_remote(monkeypatch, payloads)
    with pytest.raises(VERIFIER.SourceLockError):
        VERIFIER.verify_online(LOCK)


def test_complete_pinned_projection_passes_end_to_end(monkeypatch) -> None:
    install_remote(monkeypatch, remote_payloads(LOCK))
    VERIFIER.verify_online(LOCK)
