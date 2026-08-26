from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

import pytest

from control_plane_service.api.auth import resolve_operator
from control_plane_service.api.http import (
    is_form_preflight_allowed,
    read_request_body,
    write_form_preflight,
    write_json_response,
)
from control_plane_service.application import ApplicationHandler
from control_plane_service.core import ControlPlaneError
from control_plane_service.server import Handler as LegacyHandler


ROOT = Path(__file__).resolve().parents[1]


class FakeTransport:
    def __init__(self) -> None:
        self.status: int | None = None
        self.headers: list[tuple[str, str]] = []
        self.ended = False
        self.wfile = BytesIO()

    def send_response(self, code: int) -> None:
        self.status = code

    def send_header(self, name: str, value: str) -> None:
        self.headers.append((name, value))

    def end_headers(self) -> None:
        self.ended = True


def test_compact_json_response_preserves_headers_and_allowed_cors() -> None:
    transport = FakeTransport()
    write_json_response(
        transport,
        202,
        {"status": "accepted", "duplicate": False},
        origin="https://codestra.co",
        allowed_origins={"https://codestra.co"},
    )
    assert transport.status == 202
    assert transport.ended
    assert transport.wfile.getvalue() == b'{"status":"accepted","duplicate":false}'
    headers = dict(transport.headers)
    assert headers["Content-Type"] == "application/json"
    assert headers["Content-Length"] == str(len(transport.wfile.getvalue()))
    assert headers["Access-Control-Allow-Origin"] == "https://codestra.co"
    assert headers["Vary"] == "Origin"


def test_unknown_origin_never_receives_cors_headers() -> None:
    transport = FakeTransport()
    write_json_response(
        transport,
        403,
        {"error": "origin_denied"},
        origin="https://evil.invalid",
        allowed_origins={"https://codestra.co"},
    )
    names = {name for name, _ in transport.headers}
    assert "Access-Control-Allow-Origin" not in names
    assert "Vary" not in names


def test_request_body_reader_preserves_fail_closed_size_contract() -> None:
    assert read_request_body(
        {"Content-Length": "4"},
        BytesIO(b"test-extra"),
        4,
    ) == b"test"
    with pytest.raises(ControlPlaneError, match="invalid_body_size"):
        read_request_body({"Content-Length": "0"}, BytesIO(), 4)
    with pytest.raises(ControlPlaneError, match="invalid_body_size"):
        read_request_body({"Content-Length": "5"}, BytesIO(b"12345"), 4)


def test_form_preflight_contract_is_exact_and_path_bounded() -> None:
    origins = {"https://codestra.co"}
    assert is_form_preflight_allowed(
        "https://codestra.co",
        "/v1/forms/sales-contact",
        origins,
    )
    assert not is_form_preflight_allowed(
        "https://codestra.co",
        "/api/v1/control",
        origins,
    )
    assert not is_form_preflight_allowed(
        "https://evil.invalid",
        "/v1/forms/sales-contact",
        origins,
    )
    transport = FakeTransport()
    write_form_preflight(transport, "https://codestra.co")
    assert transport.status == 204
    assert transport.wfile.getvalue() == b""
    assert dict(transport.headers) == {
        "Access-Control-Allow-Origin": "https://codestra.co",
        "Vary": "Origin",
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": (
            "Content-Type, Idempotency-Key, X-Correlation-ID"
        ),
        "Access-Control-Max-Age": "600",
    }


def test_trusted_gateway_operator_requires_digest_role_peer_and_tenant() -> None:
    secret = "synthetic-gateway-secret"
    verifier = hashlib.sha256(secret.encode()).hexdigest()
    headers = {
        "X-Authenticated-Client": "operator-client",
        "X-Authenticated-Tenant": "tenant-a",
        "X-Authenticated-Role": "tenant_admin",
        "X-Codestra-Gateway-Secret": secret,
    }
    resolved = resolve_operator(
        headers,
        "127.0.0.1",
        {"tenant_admin"},
        trusted_proxy_cidrs="127.0.0.1/32",
        gateway_verifier=verifier,
        fallback_operator=lambda _: None,
    )
    assert resolved.authorized
    assert resolved.identity == ("operator-client", "tenant_admin", "tenant-a")

    missing_tenant = resolve_operator(
        {key: value for key, value in headers.items() if key != "X-Authenticated-Tenant"},
        "127.0.0.1",
        {"tenant_admin"},
        trusted_proxy_cidrs="127.0.0.1/32",
        gateway_verifier=verifier,
        fallback_operator=lambda _: None,
    )
    assert not missing_tenant.authorized
    assert missing_tenant.error == "forbidden"


def test_bearer_fallback_is_role_bounded_and_invalid_proxy_config_is_not_trusted() -> None:
    fallback = lambda token: (
        ("legacy-operator", "operations", None) if token == "good" else None
    )
    resolved = resolve_operator(
        {"Authorization": "Bearer good"},
        "127.0.0.1",
        {"operations"},
        trusted_proxy_cidrs="invalid-cidr",
        gateway_verifier="",
        fallback_operator=fallback,
    )
    assert resolved.identity == ("legacy-operator", "operations", None)
    denied = resolve_operator(
        {"Authorization": "Bearer good"},
        "127.0.0.1",
        {"auditor"},
        trusted_proxy_cidrs="127.0.0.1/32",
        gateway_verifier="",
        fallback_operator=fallback,
    )
    assert denied.identity is None
    assert denied.error == "forbidden"


def test_application_handler_inherits_every_business_route_without_reimplementation() -> None:
    for name in (
        "do_GET",
        "do_POST",
        "do_PUT",
        "do_PATCH",
        "crm_get",
        "crm_mutation",
        "crm_customer",
        "crm_error",
    ):
        assert getattr(ApplicationHandler, name) is getattr(LegacyHandler, name)
    assert ApplicationHandler.send_json is not LegacyHandler.send_json
    assert ApplicationHandler.body is not LegacyHandler.body
    assert ApplicationHandler.auth_operator is not LegacyHandler.auth_operator
    assert ApplicationHandler.do_OPTIONS is not LegacyHandler.do_OPTIONS


def test_container_runtime_uses_compatibility_application_entrypoint() -> None:
    dockerfile = (ROOT / "deploy/control-plane/Dockerfile").read_text(encoding="utf-8")
    assert (
        'CMD ["/opt/venv/bin/python", "-m", "control_plane_service.application"]'
        in dockerfile
    )
    assert (
        'CMD ["/opt/venv/bin/python", "-m", "control_plane_service.server"]'
        not in dockerfile
    )


def test_application_main_binds_configured_address_and_new_handler(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeServer:
        def __init__(self, address, handler) -> None:
            captured["address"] = address
            captured["handler"] = handler

        def serve_forever(self) -> None:
            captured["served"] = True

    monkeypatch.setenv("CONTROL_PLANE_BIND", "127.0.0.2")
    monkeypatch.setenv("CONTROL_PLANE_PORT", "18096")
    monkeypatch.setattr(
        "control_plane_service.application.ThreadingHTTPServer",
        FakeServer,
    )
    from control_plane_service import application

    application.main()
    assert captured == {
        "address": ("127.0.0.2", 18096),
        "handler": ApplicationHandler,
        "served": True,
    }
