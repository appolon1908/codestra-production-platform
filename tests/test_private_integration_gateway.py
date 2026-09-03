from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import pytest
import yaml
from openapi_spec_validator import validate

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "services/private-integration-gateway"
SPEC = importlib.util.spec_from_file_location("private_gateway", SERVICE / "gateway.py")
assert SPEC and SPEC.loader
gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gateway
SPEC.loader.exec_module(gateway)


@pytest.fixture(autouse=True)
def clean_gateway_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    names = {
        "GATEWAY_MODE",
        "LISTEN_ADDRESS",
        "INTEGRATION_DB",
        "WEBHOOK_TTL_SECONDS",
        "MAX_BODY_BYTES",
        "SOURCE_COMMIT_SHA",
        "LIVE_SUBMISSION_ENABLED",
        "PRODUCTION_DELIVERY_AUTHORIZED",
        "PRODUCTION_CHANGE_ID",
        "INTEGRATION_COMMAND_INTAKE_ENABLED",
        "SERVICE_TENANT_BINDINGS",
        "SERVICE_TENANT_BINDINGS_FILE",
        "MIDDLEWARE_FORWARDING_ENABLED",
        "MIDDLEWARE_EVENTS_URL",
        "MIDDLEWARE_EVENTS_CA_FILE",
        "MIDDLEWARE_EVENTS_CLIENT_CERT_FILE",
        "MIDDLEWARE_EVENTS_CLIENT_KEY_FILE",
        "JASMIN_HTTP_URL",
        "JASMIN_DLR_CALLBACK_URL",
        "JASMIN_RECONCILIATION_SECRET",
        "JASMIN_RECONCILIATION_SECRET_FILE",
        "TELNEXA_CUSTOMER_POLICY_JSON",
        "TELNEXA_CUSTOMER_POLICY_JSON_FILE",
        "TELNEXA_MIDDLEWARE_API_KEY",
        "TELNEXA_MIDDLEWARE_API_KEY_FILE",
        "TELNEXA_WEBHOOK_SECRET",
        "TELNEXA_WEBHOOK_SECRET_FILE",
        "KYQRA_MIDDLEWARE_API_KEY",
        "KYQRA_MIDDLEWARE_API_KEY_FILE",
        "KYQRA_WEBHOOK_SECRET",
        "KYQRA_WEBHOOK_SECRET_FILE",
        "KLYROW_MIDDLEWARE_API_KEY",
        "KLYROW_MIDDLEWARE_API_KEY_FILE",
        "KLYROW_WEBHOOK_SECRET",
        "KLYROW_WEBHOOK_SECRET_FILE",
        "JASMIN_ROUTE_SYNTHETIC_API_USER",
        "JASMIN_ROUTE_SYNTHETIC_API_PASSWORD",
        "JASMIN_ROUTE_ALTERNATE_API_USER",
        "JASMIN_ROUTE_ALTERNATE_API_PASSWORD",
    }
    for name in names:
        monkeypatch.delenv(name, raising=False)


def settings(tmp_path: Path, **changes):
    values = {
        "database_path": tmp_path / "integration.db",
        "mode": "shared",
        "listen_address": "0.0.0.0",
        "webhook_ttl_seconds": 300,
        "max_body_bytes": 262144,
        "source_commit_sha": "a" * 40,
        "live_submission_enabled": False,
        "production_delivery_authorized": False,
        "production_change_id": "",
        "middleware_forwarding_enabled": False,
        "downstream_url": "",
        "downstream_ca_file": str(tmp_path / "middleware-ca.crt"),
        "downstream_client_cert_file": str(tmp_path / "middleware-client.crt"),
        "downstream_client_key_file": str(tmp_path / "middleware-client.key"),
        "jasmin_url": "http://jasmin:1401",
        "jasmin_dlr_callback_url": "http://gateway:8080/internal/v1/jasmin/dlr",
        "service_tenant_bindings": {"telnexa": frozenset({"tenant-a"})},
    }
    values.update(changes)
    value = gateway.Settings(**values)
    value.validate()
    return value


def store(tmp_path: Path):
    value = gateway.Store(tmp_path / "integration.db")
    value.initialize()
    return value


OPERATION_CLOCK = 2_000_000_000.0
TRACE_CONTEXT = "00-" + ("1" * 32) + "-" + ("2" * 16) + "-01"


def governed_headers(
    scope: str,
    *,
    identity: str = "telnexa",
    tenant_id: str = "tenant-a",
    idempotency_key: str = "command-key-0001",
) -> dict[str, str]:
    return {
        "Authorization": "Bearer test-telnexa-key",
        "Content-Type": "application/json",
        "X-Client-Certificate-Verified": "SUCCESS",
        "X-Service-Identity": identity,
        "X-Service-Scope": scope,
        "X-Tenant-Id": tenant_id,
        "Idempotency-Key": idempotency_key,
    }


def command_envelope(
    *,
    operation_id: str = "11111111-1111-4111-8111-111111111111",
    idempotency_key: str = "command-key-0001",
    payload: dict | None = None,
) -> dict:
    return {
        "request_id": "request-0001",
        "correlation_id": "correlation-0001",
        "tenant_id": "tenant-a",
        "service_identity": "telnexa",
        "operation_id": operation_id,
        "idempotency_key": idempotency_key,
        "api_version": "v1",
        "timestamp": datetime.fromtimestamp(
            OPERATION_CLOCK, timezone.utc
        ).isoformat().replace("+00:00", "Z"),
        "trace_context": TRACE_CONTEXT,
        "action": "sms.send",
        "payload": payload or {"message_reference": "message-0001"},
    }


def operation_action(
    idempotency_key: str, correlation_id: str = "correlation-action-0001"
) -> dict:
    return {
        "request_id": "request-action-0001",
        "correlation_id": correlation_id,
        "idempotency_key": idempotency_key,
        "timestamp": datetime.fromtimestamp(
            OPERATION_CLOCK, timezone.utc
        ).isoformat().replace("+00:00", "Z"),
        "trace_context": TRACE_CONTEXT,
    }


def test_delivery_defaults_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("INTEGRATION_DB", str(tmp_path / "default.db"))
    value = gateway.Settings.from_environment()
    assert value.live_submission_enabled is False
    assert value.production_delivery_authorized is False
    assert value.service_tenant_bindings == {}


def test_forwarding_environment_binds_outbound_mtls_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    values = {
        "INTEGRATION_DB": str(tmp_path / "forwarding.db"),
        "MIDDLEWARE_FORWARDING_ENABLED": "true",
        "MIDDLEWARE_EVENTS_URL": "https://middleware.invalid/v1/events",
        "MIDDLEWARE_EVENTS_CA_FILE": str(tmp_path / "ca.crt"),
        "MIDDLEWARE_EVENTS_CLIENT_CERT_FILE": str(tmp_path / "client.crt"),
        "MIDDLEWARE_EVENTS_CLIENT_KEY_FILE": str(tmp_path / "client.key"),
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    settings_value = gateway.Settings.from_environment()
    assert settings_value.middleware_forwarding_enabled is True
    assert settings_value.downstream_url == values["MIDDLEWARE_EVENTS_URL"]
    assert settings_value.downstream_ca_file == values["MIDDLEWARE_EVENTS_CA_FILE"]
    assert (
        settings_value.downstream_client_cert_file
        == values["MIDDLEWARE_EVENTS_CLIENT_CERT_FILE"]
    )
    assert (
        settings_value.downstream_client_key_file
        == values["MIDDLEWARE_EVENTS_CLIENT_KEY_FILE"]
    )


def test_service_tenant_bindings_are_strict_and_file_backed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bindings = tmp_path / "tenant-bindings.json"
    bindings.write_text('{"telnexa":["tenant-a","tenant-b"]}')
    bindings.chmod(0o400)
    monkeypatch.setenv("SERVICE_TENANT_BINDINGS_FILE", str(bindings))
    assert gateway.read_service_tenant_bindings() == {
        "telnexa": frozenset({"tenant-a", "tenant-b"})
    }
    bindings.chmod(0o600)
    bindings.write_text('{"telnexa":["tenant-a"],"telnexa":["tenant-b"]}')
    with pytest.raises(ValueError, match="duplicate keys"):
        gateway.read_service_tenant_bindings()


@pytest.mark.parametrize("mode", ["middleware", "shared"])
def test_private_gateway_openapi_contains_only_executable_routes(mode: str):
    document = gateway.openapi_document(mode)
    validate(document)
    assert document["x-gateway-mode"] == mode
    paths = document["paths"]
    expected = {
        "/health",
        "/ready",
        "/version",
        "/health/live",
        "/health/ready",
        "/openapi.json",
        "/metrics",
        "/v1/capabilities",
        "/v1/operations",
        "/v1/operations/{id}",
        "/v1/operations/{id}/events",
        "/v1/operations/{id}/attempts",
        "/v1/operations/{id}/cancel",
        "/v1/operations/{id}/reconcile",
        gateway.JASMIN_DLR_PATH,
        *(f"/api/v1/{system}/health" for system in gateway.SYSTEMS),
    }
    if mode == "shared":
        expected.update({"/v1/messages", "/v1/integrations/sms/commands"})
    else:
        expected.update(
            path for values in gateway.INGRESS_PATHS.values() for path in values
        )
    assert set(paths) == expected
    post_paths = {
        gateway.JASMIN_DLR_PATH,
        "/v1/operations/{id}/cancel",
        "/v1/operations/{id}/reconcile",
    }
    if mode == "shared":
        post_paths.update({"/v1/messages", "/v1/integrations/sms/commands"})
    else:
        post_paths.update(
            value for values in gateway.INGRESS_PATHS.values() for value in values
        )
    assert all(
        set(item) == ({"post"} if path in post_paths else {"get"})
        for path, item in paths.items()
    )
    assert paths["/metrics"]["get"]["security"] == [
        {
            "mutualTLS": [],
            "bearerAuth": [],
            "serviceIdentity": [],
            "serviceScope": [],
        }
    ]
    assert paths["/v1/capabilities"]["get"]["security"] == [
        {
            "mutualTLS": [],
            "bearerAuth": [],
            "serviceIdentity": [],
            "serviceScope": [],
        }
    ]
    if mode == "shared":
        assert paths["/v1/messages"]["post"]["security"] == [
            {
                "mutualTLS": [],
                "bearerAuth": [],
                "codestraTimestamp": [],
                "codestraNonce": [],
                "codestraSignature": [],
            }
        ]
    assert paths[gateway.JASMIN_DLR_PATH]["post"]["security"] == [
        {"jasminProof": []}
    ]
    if mode == "middleware":
        kyqra_security = paths["/api/v1/kyqra/jobs"]["post"]["security"]
        assert kyqra_security == [
            {
                "mutualTLS": [],
                "bearerAuth": [],
                "kyqraTimestamp": [],
                "kyqraEventId": [],
                "kyqraSignature": [],
                "sourceSystem": [],
            }
        ]
    schemes = document["components"]["securitySchemes"]
    assert schemes["kyqraTimestamp"]["name"] == "X-Kyqra-Timestamp"
    assert schemes["telnexaEventId"]["name"] == "X-Telnexa-Event-Id"
    assert schemes["klyrowSignature"]["name"] == "X-Klyrow-Signature"
    if mode == "shared":
        command_security = paths["/v1/integrations/sms/commands"]["post"][
            "security"
        ]
        assert command_security == [
            {
                "mutualTLS": [],
                "bearerAuth": [],
                "serviceIdentity": [],
                "serviceScope": [],
                "tenantHeader": [],
                "idempotencyHeader": [],
            }
        ]


def test_private_gateway_openapi_rejects_unknown_runtime_mode():
    with pytest.raises(ValueError, match="OpenAPI mode"):
        gateway.openapi_document("invalid")


def test_governed_command_is_durable_idempotent_and_semantic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TELNEXA_MIDDLEWARE_API_KEY", "test-telnexa-key")
    storage = store(tmp_path)
    app = gateway.Gateway(
        settings(tmp_path, integration_command_intake_enabled=True),
        storage,
        clock=lambda: OPERATION_CLOCK,
    )
    headers = governed_headers("integrations:sms:commands")
    body = json.dumps(command_envelope(), separators=(",", ":")).encode()

    code, created = app.integration_command("sms", body, headers)
    assert code == 202
    assert created == {
        "operation_id": "11111111-1111-4111-8111-111111111111",
        "status": "RECONCILIATION_REQUIRED",
        "resource_version": 1,
        "result": None,
        "error": {
            "code": "downstream_dispatch_authority_unavailable",
            "message": "command persisted; downstream dispatch is not authorized",
        },
        "retryability": False,
        "reconciliation_required": True,
        "correlation_id": "correlation-0001",
        "duplicate": False,
    }

    code, replay = app.integration_command("sms", body, headers)
    assert code == 200
    assert replay == {**created, "duplicate": True}

    changed = command_envelope(payload={"message_reference": "message-0002"})
    code, conflict = app.integration_command(
        "sms", json.dumps(changed).encode(), headers
    )
    assert code == 409
    assert conflict == {"detail": "idempotency_conflict"}

    code, wrong_channel = app.integration_command(
        "email", body, governed_headers("integrations:email:commands")
    )
    assert code == 403
    assert wrong_channel == {"detail": "channel_not_authorized"}

    sensitive = command_envelope(
        operation_id="22222222-2222-4222-8222-222222222222",
        idempotency_key="command-key-0002",
        payload={"provider": {"smtp_password": "must-not-be-accepted"}},
    )
    sensitive_headers = governed_headers(
        "integrations:sms:commands", idempotency_key="command-key-0002"
    )
    code, rejected = app.integration_command(
        "sms", json.dumps(sensitive).encode(), sensitive_headers
    )
    assert code == 422
    assert rejected == {"detail": "invalid_or_sensitive_payload"}


def test_command_intake_is_fail_closed_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TELNEXA_MIDDLEWARE_API_KEY", "test-telnexa-key")
    storage = store(tmp_path)
    app = gateway.Gateway(
        settings(tmp_path), storage, clock=lambda: OPERATION_CLOCK
    )
    code, value = app.integration_command(
        "sms",
        json.dumps(command_envelope()).encode(),
        governed_headers("integrations:sms:commands"),
    )
    assert code == 503
    assert value == {"detail": "integration_command_intake_disabled"}
    assert storage.integration_operation(
        "11111111-1111-4111-8111-111111111111", "tenant-a", "telnexa"
    ) is None


def test_operations_are_tenant_isolated_and_actions_are_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TELNEXA_MIDDLEWARE_API_KEY", "test-telnexa-key")
    storage = store(tmp_path)
    app = gateway.Gateway(
        settings(tmp_path, integration_command_intake_enabled=True),
        storage,
        clock=lambda: OPERATION_CLOCK,
    )
    command_headers = governed_headers("integrations:sms:commands")
    operation_id = command_envelope()["operation_id"]
    code, _ = app.integration_command(
        "sms", json.dumps(command_envelope()).encode(), command_headers
    )
    assert code == 202

    read_headers = governed_headers("operations:read")
    code, operation = app.read_integration_operation(operation_id, read_headers)
    assert code == 200
    assert operation["operation_id"] == operation_id
    other_tenant = governed_headers("operations:read", tenant_id="tenant-b")
    assert app.read_integration_operation(operation_id, other_tenant) == (
        401,
        {"detail": "operation_read_authority_required"},
    )
    code, listed = app.list_integration_operations(read_headers, 50)
    assert code == 200
    assert [item["operation_id"] for item in listed["operations"]] == [operation_id]

    reconcile_headers = governed_headers(
        "operations:reconcile", idempotency_key="reconcile-key-0001"
    )
    reconcile_body = json.dumps(operation_action("reconcile-key-0001")).encode()
    code, blocked = app.mutate_integration_operation(
        operation_id, "reconcile", reconcile_body, reconcile_headers
    )
    assert code == 409
    assert blocked["status"] == "RECONCILIATION_REQUIRED"
    assert blocked["resource_version"] == 2
    assert blocked["duplicate"] is False

    code, replay = app.mutate_integration_operation(
        operation_id, "reconcile", reconcile_body, reconcile_headers
    )
    assert code == 200
    assert replay["resource_version"] == 2
    assert replay["duplicate"] is True

    code, attempts = app.read_integration_operation_records(
        operation_id, "attempts", read_headers
    )
    assert code == 200
    assert len(attempts["attempts"]) == 1
    assert attempts["attempts"][0]["status"] == "BLOCKED"

    cancel_headers = governed_headers(
        "operations:cancel", idempotency_key="cancel-key-0001"
    )
    cancel_body = json.dumps(operation_action("cancel-key-0001")).encode()
    code, cancelled = app.mutate_integration_operation(
        operation_id, "cancel", cancel_body, cancel_headers
    )
    assert code == 200
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["resource_version"] == 3
    assert cancelled["duplicate"] is False

    code, duplicate_cancel = app.mutate_integration_operation(
        operation_id, "cancel", cancel_body, cancel_headers
    )
    assert code == 200
    assert duplicate_cancel["resource_version"] == 3
    assert duplicate_cancel["duplicate"] is True

    code, events = app.read_integration_operation_records(
        operation_id, "events", read_headers
    )
    assert code == 200
    assert [event["resource_version"] for event in events["events"]] == [1, 2, 3]


def test_capabilities_route_requires_derived_identity_and_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TELNEXA_MIDDLEWARE_API_KEY", "test-telnexa-key")
    app = gateway.Gateway(
        settings(tmp_path, integration_command_intake_enabled=True), store(tmp_path)
    )
    server = gateway.ThreadingHTTPServer(("127.0.0.1", 0), gateway.handler_for(app))
    server.daemon_threads = True
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    endpoint = f"http://127.0.0.1:{server.server_port}/v1/capabilities"
    try:
        with pytest.raises(urllib.error.HTTPError) as missing_scope:
            urllib.request.urlopen(endpoint, timeout=5)
        assert missing_scope.value.code == 401
        request = urllib.request.Request(
            endpoint, headers=governed_headers("capabilities:read")
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            value = json.load(response)
        assert value["service_identity"] == "telnexa"
        assert value["command_channels"] == ["sms"]
        assert value["command_intake_enabled"] is True
        assert value["downstream_dispatch_enabled"] is False
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def test_production_edge_derives_telnexa_identity_and_scopes() -> None:
    nginx = (SERVICE / "nginx/telnexa-private-gateway.conf").read_text()
    assert "proxy_set_header X-Service-Identity telnexa;" in nginx
    assert "integrations:sms:commands" in nginx
    assert "metrics:read" in nginx
    assert "operations:reconcile" in nginx
    assert '"^CN=middleware-telnexa-client$"' in nginx
    assert '$ssl_client_serial !=' not in nginx
    assert "$http_x_service_identity" not in nginx.lower()
    compose = yaml.safe_load((SERVICE / "compose.production.yaml").read_text())
    environment = compose["services"]["gateway"]["environment"]
    assert environment["INTEGRATION_COMMAND_INTAKE_ENABLED"] == "false"
    assert environment["SERVICE_TENANT_BINDINGS_FILE"] == (
        "/run/secrets/private_gateway_tenant_bindings"
    )
    assert "private_gateway_tenant_bindings" in compose["secrets"]
    assert environment["LIVE_SUBMISSION_ENABLED"] == "false"
    assert environment["PRODUCTION_DELIVERY_AUTHORIZED"] == "false"


def test_command_and_operation_authority_fail_closed_without_tenant_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TELNEXA_MIDDLEWARE_API_KEY", "test-telnexa-key")
    app = gateway.Gateway(
        settings(
            tmp_path,
            integration_command_intake_enabled=True,
            service_tenant_bindings={},
        ),
        store(tmp_path),
        clock=lambda: OPERATION_CLOCK,
    )
    command_headers = governed_headers("integrations:sms:commands")
    code, value = app.integration_command(
        "sms", json.dumps(command_envelope()).encode(), command_headers
    )
    assert code == 403
    assert value == {"detail": "tenant_not_authorized"}
    assert app.list_integration_operations(
        governed_headers("operations:read"), 50
    ) == (401, {"detail": "operation_read_authority_required"})


def test_metrics_requires_mtls_derived_matching_service_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TELNEXA_MIDDLEWARE_API_KEY", "test-telnexa-key")
    app = gateway.Gateway(
        settings(tmp_path, integration_command_intake_enabled=True),
        store(tmp_path),
        clock=lambda: OPERATION_CLOCK,
    )
    command_headers = governed_headers("integrations:sms:commands")
    operation_id = command_envelope()["operation_id"]
    code, _ = app.integration_command(
        "sms", json.dumps(command_envelope()).encode(), command_headers
    )
    assert code == 202
    reconcile_headers = governed_headers(
        "operations:reconcile", idempotency_key="reconcile-key-0001"
    )
    code, _ = app.mutate_integration_operation(
        operation_id,
        "reconcile",
        json.dumps(operation_action("reconcile-key-0001")).encode(),
        reconcile_headers,
    )
    assert code == 409
    server = gateway.ThreadingHTTPServer(("127.0.0.1", 0), gateway.handler_for(app))
    server.daemon_threads = True
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    endpoint = f"http://127.0.0.1:{server.server_port}/metrics"
    try:
        with pytest.raises(urllib.error.HTTPError) as missing_authority:
            urllib.request.urlopen(endpoint, timeout=5)
        assert missing_authority.value.code == 401

        wrong_certificate = urllib.request.Request(
            endpoint,
            headers={
                "Authorization": "Bearer test-telnexa-key",
                "X-Client-Certificate-Verified": "FAILED",
                "X-Service-Identity": "telnexa",
            },
        )
        with pytest.raises(urllib.error.HTTPError) as unverified:
            urllib.request.urlopen(wrong_certificate, timeout=5)
        assert unverified.value.code == 401

        missing_scope = urllib.request.Request(
            endpoint,
            headers={
                "Authorization": "Bearer test-telnexa-key",
                "X-Client-Certificate-Verified": "SUCCESS",
                "X-Service-Identity": "telnexa",
            },
        )
        with pytest.raises(urllib.error.HTTPError) as unscoped:
            urllib.request.urlopen(missing_scope, timeout=5)
        assert unscoped.value.code == 401

        authorized = urllib.request.Request(
            endpoint,
            headers={
                "Authorization": "Bearer test-telnexa-key",
                "X-Client-Certificate-Verified": "SUCCESS",
                "X-Service-Identity": "telnexa",
                "X-Service-Scope": "metrics:read",
            },
        )
        with urllib.request.urlopen(authorized, timeout=5) as response:
            assert response.status == 200
            assert response.headers["Content-Type"] == "text/plain; charset=us-ascii"
            metrics = response.read()
            assert b"private_gateway_events" in metrics
            assert (
                b'private_gateway_operations{channel="sms",status="RECONCILIATION_REQUIRED"} 1'
                in metrics
            )
            assert (
                b'private_gateway_operation_attempts{attempt_type="RECONCILE",status="BLOCKED"} 1'
                in metrics
            )
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def test_connectivity_audit_proves_metrics_through_the_real_mtls_edge() -> None:
    source = (ROOT / "scripts/private_gateway_audit.py").read_text()

    assert "https://telnexa.internal.codestra.agency:8443/metrics" in source
    assert 'EDGE_ADDRESS != "10.40.0.4"' in source
    assert "PRIVATE_GATEWAY_AUDIT_CLIENT_CERT_FILE" in source
    assert "PRIVATE_GATEWAY_AUDIT_CLIENT_KEY_FILE" in source
    assert "PRIVATE_GATEWAY_AUDIT_CA_FILE" in source
    assert "PRIVATE_GATEWAY_AUDIT_BEARER_TOKEN_FILE" in source
    assert "context.load_cert_chain" in source
    assert "server_hostname=self.host" in source
    assert "X-Client-Certificate-Verified" not in source
    assert '"X-Service-Identity"' not in source
    assert '"X-Service-Scope"' not in source


def test_live_delivery_requires_second_gate_and_change_id(tmp_path: Path):
    with pytest.raises(ValueError, match="production authorization"):
        settings(tmp_path, live_submission_enabled=True)
    with pytest.raises(ValueError, match="production authorization"):
        settings(
            tmp_path,
            live_submission_enabled=True,
            production_delivery_authorized=True,
        )


def test_middleware_forwarding_is_explicit_https_and_source_bounded(tmp_path: Path):
    with pytest.raises(ValueError, match="MIDDLEWARE_EVENTS_URL"):
        settings(tmp_path, middleware_forwarding_enabled=True)
    with pytest.raises(ValueError, match="outbound mTLS material"):
        settings(
            tmp_path,
            middleware_forwarding_enabled=True,
            downstream_url="https://middleware.invalid/v1/events",
            downstream_ca_file="",
        )
    with pytest.raises(ValueError, match="paths must be absolute"):
        settings(
            tmp_path,
            middleware_forwarding_enabled=True,
            downstream_url="https://middleware.invalid/v1/events",
            downstream_ca_file="relative-ca.crt",
        )
    shared = settings(
        tmp_path,
        middleware_forwarding_enabled=True,
        downstream_url="https://middleware.invalid/v1/events",
    )
    assert shared.middleware_forwarding_enabled is True
    assert gateway.Gateway(shared, store(tmp_path)).forwarding_systems() == {
        "telnexa"
    }
    value = settings(
        tmp_path,
        mode="middleware",
        middleware_forwarding_enabled=True,
        downstream_url="https://middleware.invalid/v1/events",
    )
    assert value.middleware_forwarding_enabled is True


def test_middleware_tls_context_requires_files_and_loads_client_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    value = settings(
        tmp_path,
        middleware_forwarding_enabled=True,
        downstream_url="https://middleware.invalid/v1/events",
    )
    with pytest.raises(RuntimeError, match="mTLS material is unavailable"):
        gateway.build_middleware_tls_context(value)

    for path_value in (
        value.downstream_ca_file,
        value.downstream_client_cert_file,
        value.downstream_client_key_file,
    ):
        Path(path_value).write_text("test fixture", encoding="utf-8")

    class Context:
        minimum_version = None
        loaded = None

        def load_cert_chain(self, *, certfile, keyfile):
            self.loaded = (certfile, keyfile)

    context = Context()
    calls = []

    def create_default_context(*, cafile):
        calls.append(cafile)
        return context

    monkeypatch.setattr(gateway.ssl, "create_default_context", create_default_context)
    assert gateway.build_middleware_tls_context(value) is context
    assert calls == [value.downstream_ca_file]
    assert context.minimum_version == gateway.ssl.TLSVersion.TLSv1_2
    assert context.loaded == (
        value.downstream_client_cert_file,
        value.downstream_client_key_file,
    )


def test_gateway_builds_outbound_mtls_context_before_default_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    value = settings(
        tmp_path,
        middleware_forwarding_enabled=True,
        downstream_url="https://middleware.invalid/v1/events",
    )
    sentinel = object()
    monkeypatch.setattr(
        gateway, "build_middleware_tls_context", lambda supplied: sentinel
    )
    app = gateway.production_gateway(value, store(tmp_path))
    assert app.middleware_tls_context is sentinel


def test_only_private_jasmin_service_is_accepted(tmp_path: Path):
    with pytest.raises(ValueError, match="private"):
        settings(tmp_path, jasmin_url="https://example.invalid")
    with pytest.raises(ValueError, match="private"):
        settings(tmp_path, jasmin_url="http://127.0.0.1:1401")
    with pytest.raises(ValueError, match="exact private gateway callback"):
        settings(
            tmp_path,
            jasmin_dlr_callback_url="https://public.example/internal/v1/jasmin/dlr",
        )


def test_secret_file_must_be_regular_and_not_writable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    secret = tmp_path / "secret"
    secret.write_text("test-secret-value\n")
    secret.chmod(0o600)
    monkeypatch.setenv("TELNEXA_WEBHOOK_SECRET_FILE", str(secret))
    assert gateway.read_secret("TELNEXA_WEBHOOK_SECRET") == "test-secret-value"
    secret.chmod(0o620)
    with pytest.raises(ValueError, match="writable"):
        gateway.read_secret("TELNEXA_WEBHOOK_SECRET")


def test_secret_file_symlink_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    secret = tmp_path / "secret"
    secret.write_text("test-secret-value\n")
    secret.chmod(0o600)
    link = tmp_path / "secret-link"
    link.symlink_to(secret)
    monkeypatch.setenv("TELNEXA_WEBHOOK_SECRET_FILE", str(link))
    with pytest.raises(OSError):
        gateway.read_secret("TELNEXA_WEBHOOK_SECRET")


def configure_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "TELNEXA_CUSTOMER_POLICY_JSON",
        json.dumps(
            {
                "tenant-a": {
                    "enabled": True,
                    "tenant_id": "tenant-a",
                    "senders": ["TEST"],
                    "destination_prefixes": ["+49155"],
                    "route": "synthetic",
                    "approved_recipients": ["+4915512345678"],
                    "consented_recipients": ["+4915512345678"],
                    "suppressed_recipients": [],
                    "delivery_window": {
                        "timezone": "Z",
                        "start": "00:00",
                        "end": "23:59",
                    },
                    "billing_period": "2026-09",
                    "quota_limit_segments": 1000,
                    "wallet_limit_minor": 100000,
                    "cost_per_segment_minor": 5,
                    "currency": "EUR",
                },
                "tenant-disabled": {
                    "enabled": False,
                    "senders": ["TEST"],
                    "destination_prefixes": ["+49155"],
                    "route": "synthetic",
                },
            }
        ),
    )


def configure_jasmin_route(
    monkeypatch: pytest.MonkeyPatch,
    route: str = "synthetic",
    username: str = "test-user",
    password: str = "test-password",
) -> None:
    stem = "JASMIN_ROUTE_" + route.upper().replace("-", "_")
    monkeypatch.setenv(stem + "_API_USER", username)
    monkeypatch.setenv(stem + "_API_PASSWORD", password)
    monkeypatch.setenv("JASMIN_RECONCILIATION_SECRET", "r" * 64)


def valid_payload(**changes):
    value = {
        "customer_id": "tenant-a",
        "message_id": "message-0001",
        "tenant_id": "tenant-a",
        "sender": "TEST",
        "to": "+4915512345678",
        "body": "synthetic",
        "idempotency_key": "idem-0001",
        "correlation_id": "corr-0001",
    }
    value.update(changes)
    return value


@pytest.mark.parametrize("prefix", ["", "+", "49155", "+0", "+49x", "+1234567890123456"])
def test_customer_destination_prefixes_are_strict_e164_routes(
    monkeypatch: pytest.MonkeyPatch, prefix: str
) -> None:
    configure_tenant(monkeypatch)
    policy = gateway.customer_policy()
    policy["tenant-a"]["destination_prefixes"] = [prefix]
    monkeypatch.setenv("TELNEXA_CUSTOMER_POLICY_JSON", json.dumps(policy))
    with pytest.raises(PermissionError, match="destination_route_not_authorized"):
        gateway.validate_outbound(valid_payload(), 2_000_000_000)


@pytest.mark.parametrize(
    ("message", "segments"),
    [
        ("a" * 160, 1),
        ("a" * 161, 2),
        ("^" * 80, 1),
        ("^" * 81, 2),
        ("€" * 80, 1),
        ("漢" * 70, 1),
        ("漢" * 71, 2),
        ("😀" * 35, 1),
        ("😀" * 36, 2),
    ],
)
def test_sms_segment_count_uses_gsm_septets_and_utf16_units(
    message: str, segments: int
) -> None:
    assert gateway.sms_segment_count(message) == segments


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"sender": "bad sender!"}, ValueError),
        ({"sender": "OTHER"}, PermissionError),
        ({"to": "0155abc"}, ValueError),
        ({"to": "+18095550101"}, PermissionError),
        ({"customer_id": "tenant-disabled"}, PermissionError),
        ({"customer_id": "tenant-b"}, PermissionError),
        ({"customer_id": " tenant-a"}, ValueError),
        ({"customer_id": "x" * 129}, ValueError),
        ({"correlation_id": "x" * 129}, ValueError),
    ],
)
def test_outbound_policy_rejects_invalid_or_cross_tenant_input(
    monkeypatch: pytest.MonkeyPatch, changes, error
):
    configure_tenant(monkeypatch)
    with pytest.raises(error):
        gateway.validate_outbound(valid_payload(**changes), 2_000_000_000)


def test_outbound_policy_accepts_exact_sender_destination_and_route(
    monkeypatch: pytest.MonkeyPatch,
):
    configure_tenant(monkeypatch)
    assert gateway.validate_outbound(valid_payload(), 2_000_000_000) == (
        "tenant-a",
        "TEST",
        "+4915512345678",
        "synthetic",
        "corr-0001",
    )


def test_outbound_policy_is_bound_to_the_exact_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_tenant(monkeypatch)
    policy = gateway.customer_policy()
    policy["shared-customer"] = policy.pop("tenant-a")
    policy["shared-customer"]["tenant_id"] = "tenant-a"
    monkeypatch.setenv("TELNEXA_CUSTOMER_POLICY_JSON", json.dumps(policy))
    with pytest.raises(PermissionError, match="tenant_customer_policy_mismatch"):
        gateway.validate_outbound(
            valid_payload(customer_id="shared-customer", tenant_id="tenant-b"),
            2_000_000_000,
        )


@pytest.mark.parametrize(
    "field",
    [
        "billing_period",
        "quota_limit_segments",
        "wallet_limit_minor",
        "cost_per_segment_minor",
        "currency",
    ],
)
def test_enabled_customer_requires_complete_billing_policy(
    monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    configure_tenant(monkeypatch)
    policy = gateway.customer_policy()
    del policy["tenant-a"][field]
    monkeypatch.setenv("TELNEXA_CUSTOMER_POLICY_JSON", json.dumps(policy))
    with pytest.raises(PermissionError, match="billing_policy_invalid"):
        gateway.validate_outbound(valid_payload(), 2_000_000_000)
    with pytest.raises(RuntimeError, match="billing policy is invalid"):
        gateway.validate_live_route_authorities()


@pytest.mark.parametrize(
    "senders",
    ["CODESTRA", {"CODE": True}, [], ["TEST", "TEST"], [" TEST"]],
)
def test_sender_policy_requires_a_unique_canonical_list(
    monkeypatch: pytest.MonkeyPatch, senders
) -> None:
    configure_tenant(monkeypatch)
    policy = gateway.customer_policy()
    policy["tenant-a"]["senders"] = senders
    monkeypatch.setenv("TELNEXA_CUSTOMER_POLICY_JSON", json.dumps(policy))
    with pytest.raises(PermissionError, match="sender_policy_invalid"):
        gateway.validate_outbound(valid_payload(sender="CODE"), 2_000_000_000)
    with pytest.raises(RuntimeError, match="sender policy is invalid"):
        gateway.validate_live_route_authorities()


@pytest.mark.parametrize(
    ("policy_change", "detail"),
    [
        ({"approved_recipients": []}, "recipient_not_approved"),
        ({"consented_recipients": []}, "recipient_consent_required"),
        ({"suppressed_recipients": ["+4915512345678"]}, "recipient_suppressed"),
        ({"approved_recipients": [" +4915512345678"]}, "recipient_policy_invalid"),
    ],
)
def test_outbound_requires_approved_consented_unsuppressed_recipient(
    monkeypatch: pytest.MonkeyPatch,
    policy_change: dict[str, list[str]],
    detail: str,
):
    configure_tenant(monkeypatch)
    policy = gateway.customer_policy()
    policy["tenant-a"].update(policy_change)
    monkeypatch.setenv("TELNEXA_CUSTOMER_POLICY_JSON", json.dumps(policy))
    with pytest.raises(PermissionError, match=detail):
        gateway.validate_outbound(valid_payload(), 2_000_000_000)


@pytest.mark.parametrize("enabled", ["false", 1, 0, None])
def test_customer_enablement_requires_literal_boolean_true(
    monkeypatch: pytest.MonkeyPatch, enabled
) -> None:
    configure_tenant(monkeypatch)
    policy = gateway.customer_policy()
    policy["tenant-a"]["enabled"] = enabled
    monkeypatch.setenv("TELNEXA_CUSTOMER_POLICY_JSON", json.dumps(policy))
    with pytest.raises(PermissionError, match="customer_disabled_or_unknown"):
        gateway.validate_outbound(valid_payload(), 2_000_000_000)
    with pytest.raises(RuntimeError, match="enabled flag is invalid"):
        gateway.validate_live_route_authorities()


@pytest.mark.parametrize("customer_id", [" tenant-a", "tenant-a ", "x" * 129])
def test_customer_identity_is_canonical_before_policy_startup_and_sms_reservation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    customer_id: str,
) -> None:
    configure_tenant(monkeypatch)
    policy = gateway.customer_policy()
    policy[customer_id] = policy.pop("tenant-a")
    monkeypatch.setenv("TELNEXA_CUSTOMER_POLICY_JSON", json.dumps(policy))
    with pytest.raises(RuntimeError, match="customer policy identity is invalid"):
        gateway.validate_live_route_authorities()

    configure_tenant(monkeypatch)
    configure_jasmin_route(monkeypatch)
    monkeypatch.setenv("TELNEXA_MIDDLEWARE_API_KEY", "test-telnexa-key")
    monkeypatch.setenv("TELNEXA_WEBHOOK_SECRET", "test-telnexa-secret")
    state = store(tmp_path)
    app = gateway.Gateway(
        settings(
            tmp_path,
            live_submission_enabled=True,
            production_delivery_authorized=True,
            production_change_id="CHG-CANONICAL-CUSTOMER",
        ),
        state,
        clock=lambda: 2_000_000_000,
        urlopen=lambda *_args, **_kwargs: pytest.fail(
            "carrier reached for a noncanonical customer"
        ),
    )
    body = json.dumps(
        valid_payload(customer_id=customer_id), separators=(",", ":")
    ).encode()
    assert app.outbound(
        body,
        outbound_headers(body, 2_000_000_000, "nonce-canonical-customer-0001"),
    ) == (422, {"detail": "customer_required"})
    with state.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM sms_transactions"
        ).fetchone()[0] == 0


def test_customer_timezone_delivery_window_blocks_before_sms_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure_tenant(monkeypatch)
    policy = gateway.customer_policy()
    policy["tenant-a"]["delivery_window"] = {
        "timezone": "+02:00",
        "start": "09:00",
        "end": "17:00",
    }
    monkeypatch.setenv("TELNEXA_CUSTOMER_POLICY_JSON", json.dumps(policy))
    allowed = datetime(2026, 9, 1, 12, tzinfo=timezone.utc).timestamp()
    blocked = datetime(2026, 9, 1, 18, tzinfo=timezone.utc).timestamp()
    assert gateway.validate_outbound(valid_payload(), allowed)[0] == "tenant-a"
    with pytest.raises(PermissionError, match="quiet_hours"):
        gateway.validate_outbound(valid_payload(), blocked)

    monkeypatch.setenv("TELNEXA_MIDDLEWARE_API_KEY", "test-telnexa-key")
    monkeypatch.setenv("TELNEXA_WEBHOOK_SECRET", "test-telnexa-secret")
    configure_jasmin_route(monkeypatch)
    state = store(tmp_path)
    app = gateway.Gateway(
        settings(
            tmp_path,
            live_submission_enabled=True,
            production_delivery_authorized=True,
            production_change_id="CHG-QUIET-HOURS",
        ),
        state,
        clock=lambda: blocked,
        urlopen=lambda *_args, **_kwargs: pytest.fail("carrier reached in quiet hours"),
    )
    body = json.dumps(valid_payload(), separators=(",", ":")).encode()
    code, result = app.outbound(
        body, outbound_headers(body, int(blocked), "nonce-quiet-hours-0001")
    )
    assert (code, result) == (403, {"detail": "quiet_hours"})
    with state.connect() as connection:
        count = connection.execute("SELECT COUNT(*) FROM sms_transactions").fetchone()[0]
    assert count == 0


@pytest.mark.parametrize(
    ("policy_change", "expected_error"),
    [
        ({"quota_limit_segments": 1}, "customer_quota_exhausted"),
        ({"wallet_limit_minor": 5}, "wallet_funds_insufficient"),
    ],
)
def test_quota_and_wallet_are_atomically_reserved_before_carrier_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    policy_change: dict[str, int],
    expected_error: str,
) -> None:
    now = 2_000_000_000
    configure_tenant(monkeypatch)
    policy = gateway.customer_policy()
    policy["tenant-a"].update(policy_change)
    monkeypatch.setenv("TELNEXA_CUSTOMER_POLICY_JSON", json.dumps(policy))
    monkeypatch.setenv("TELNEXA_MIDDLEWARE_API_KEY", "test-telnexa-key")
    monkeypatch.setenv("TELNEXA_WEBHOOK_SECRET", "test-telnexa-secret")
    state = store(tmp_path)
    probes = 0

    def urlopen(url, **_kwargs):
        nonlocal probes
        probes += 1
        return HealthyJasmin()

    app = gateway.Gateway(
        settings(tmp_path), state, clock=lambda: now, urlopen=urlopen
    )
    first_body = json.dumps(valid_payload(), separators=(",", ":")).encode()
    assert app.outbound(
        first_body,
        outbound_headers(first_body, now, "nonce-billing-reserve-0001"),
    )[0] == 202
    with state.connect() as connection:
        connection.execute(
            "UPDATE sms_transactions SET state='submitted',carrier_submitted=1"
        )
    second_body = json.dumps(
        valid_payload(
            idempotency_key="idem-billing-0002",
            message_id="message-billing-0002",
        ),
        separators=(",", ":"),
    ).encode()
    assert app.outbound(
        second_body,
        outbound_headers(second_body, now, "nonce-billing-reserve-0002"),
    ) == (403, {"detail": expected_error})
    assert probes == 1
    with state.connect() as connection:
        rows = connection.execute(
            """SELECT tenant_id,billing_period,reserved_units,reserved_cost_minor,
            currency,validation_result FROM sms_transactions"""
        ).fetchall()
    assert [tuple(row) for row in rows] == [
        ("tenant-a", "2026-09", 1, 5, "EUR", "quota_wallet_reserved")
    ]


def test_segment_quota_remains_enforced_after_currency_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = 2_000_000_000
    configure_tenant(monkeypatch)
    policy = gateway.customer_policy()
    policy["tenant-a"].update(
        {"quota_limit_segments": 1, "wallet_limit_minor": 5}
    )
    monkeypatch.setenv("TELNEXA_CUSTOMER_POLICY_JSON", json.dumps(policy))
    monkeypatch.setenv("TELNEXA_MIDDLEWARE_API_KEY", "test-telnexa-key")
    monkeypatch.setenv("TELNEXA_WEBHOOK_SECRET", "test-telnexa-secret")
    state = store(tmp_path)
    app = gateway.Gateway(
        settings(tmp_path),
        state,
        clock=lambda: now,
        urlopen=lambda *_args, **_kwargs: HealthyJasmin(),
    )
    first = json.dumps(valid_payload(), separators=(",", ":")).encode()
    assert app.outbound(
        first, outbound_headers(first, now, "nonce-cross-currency-0001")
    )[0] == 202
    with state.connect() as connection:
        connection.execute(
            "UPDATE sms_transactions SET state='submitted',carrier_submitted=1"
        )
    policy["tenant-a"]["currency"] = "USD"
    monkeypatch.setenv("TELNEXA_CUSTOMER_POLICY_JSON", json.dumps(policy))
    second = json.dumps(
        valid_payload(
            idempotency_key="idem-cross-currency-0002",
            message_id="message-cross-currency-0002",
        ),
        separators=(",", ":"),
    ).encode()
    assert app.outbound(
        second, outbound_headers(second, now, "nonce-cross-currency-0002")
    ) == (403, {"detail": "customer_quota_exhausted"})


def test_released_reservation_reacquires_current_capacity_before_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = 2_000_000_000
    configure_tenant(monkeypatch)
    policy = gateway.customer_policy()
    policy["tenant-a"]["quota_limit_segments"] = 1
    monkeypatch.setenv("TELNEXA_CUSTOMER_POLICY_JSON", json.dumps(policy))
    monkeypatch.setenv("TELNEXA_MIDDLEWARE_API_KEY", "test-telnexa-key")
    monkeypatch.setenv("TELNEXA_WEBHOOK_SECRET", "test-telnexa-secret")
    probes = [False, True]

    def urlopen(url, **_kwargs):
        assert url.endswith("/ping")
        if not probes.pop(0):
            raise TimeoutError("synthetic dependency outage")
        return HealthyJasmin()

    state = store(tmp_path)
    app = gateway.Gateway(
        settings(tmp_path), state, clock=lambda: now, urlopen=urlopen
    )
    released = json.dumps(valid_payload(), separators=(",", ":")).encode()
    assert app.outbound(
        released, outbound_headers(released, now, "nonce-release-capacity-0001")
    ) == (503, {"detail": "jasmin_dependency_unavailable"})
    replacement = json.dumps(
        valid_payload(
            idempotency_key="idem-release-capacity-0002",
            message_id="message-release-capacity-0002",
        ),
        separators=(",", ":"),
    ).encode()
    assert app.outbound(
        replacement,
        outbound_headers(replacement, now, "nonce-release-capacity-0002"),
    )[0] == 202
    with state.connect() as connection:
        connection.execute(
            """UPDATE sms_transactions SET state='submitted',carrier_submitted=1
            WHERE idempotency_key='idem-release-capacity-0002'"""
        )
    assert app.outbound(
        released, outbound_headers(released, now, "nonce-release-capacity-0003")
    ) == (403, {"detail": "customer_quota_exhausted"})


def test_safe_mode_and_rejected_rows_release_reserved_capacity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = 2_000_000_000
    configure_tenant(monkeypatch)
    policy = gateway.customer_policy()
    policy["tenant-a"]["quota_limit_segments"] = 1
    policy["tenant-a"]["wallet_limit_minor"] = 5
    monkeypatch.setenv("TELNEXA_CUSTOMER_POLICY_JSON", json.dumps(policy))
    monkeypatch.setenv("TELNEXA_MIDDLEWARE_API_KEY", "test-telnexa-key")
    monkeypatch.setenv("TELNEXA_WEBHOOK_SECRET", "test-telnexa-secret")
    state = store(tmp_path)
    app = gateway.Gateway(
        settings(tmp_path),
        state,
        clock=lambda: now,
        urlopen=lambda *_args, **_kwargs: HealthyJasmin(),
    )
    for attempt in range(1, 4):
        body = json.dumps(
            valid_payload(
                idempotency_key=f"idem-released-{attempt:04d}",
                message_id=f"message-released-{attempt:04d}",
            ),
            separators=(",", ":"),
        ).encode()
        assert app.outbound(
            body,
            outbound_headers(body, now, f"nonce-released-{attempt:04d}"),
        )[0] == 202
        if attempt == 1:
            with state.connect() as connection:
                connection.execute(
                    """UPDATE sms_transactions
                    SET state='rejected',carrier_submitted=0
                    WHERE idempotency_key='idem-released-0001'"""
                )


@pytest.mark.parametrize(
    "window",
    [
        None,
        {"timezone": "Europe/Berlin", "start": "09:00", "end": "17:00"},
        {"timezone": "Z", "start": "09:00", "end": "09:00"},
        {"timezone": "Z", "start": "9:00", "end": "17:00"},
        {"timezone": "+13:99", "start": "09:00", "end": "17:00"},
        {"timezone": "-14:01", "start": "09:00", "end": "17:00"},
        {"timezone": "-00:00", "start": "09:00", "end": "17:00"},
    ],
)
def test_enabled_customer_delivery_window_configuration_fails_closed(
    monkeypatch: pytest.MonkeyPatch, window
) -> None:
    configure_tenant(monkeypatch)
    policy = gateway.customer_policy()
    policy["tenant-a"]["delivery_window"] = window
    monkeypatch.setenv("TELNEXA_CUSTOMER_POLICY_JSON", json.dumps(policy))
    with pytest.raises(PermissionError, match="delivery_window_policy_invalid"):
        gateway.validate_outbound(valid_payload(), 2_000_000_000)
    with pytest.raises(RuntimeError, match="delivery window is invalid"):
        gateway.validate_live_route_authorities()


def test_live_submission_uses_the_customer_route_specific_jasmin_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    now = 2_000_000_000
    monkeypatch.setenv(
        "TELNEXA_CUSTOMER_POLICY_JSON",
        json.dumps(
            {
                "tenant-a": {
                    "enabled": True,
                    "tenant_id": "tenant-a",
                    "senders": ["TEST"],
                    "destination_prefixes": ["+49155"],
                    "route": "synthetic",
                    "approved_recipients": ["+4915512345678"],
                    "consented_recipients": ["+4915512345678"],
                    "suppressed_recipients": [],
                    "delivery_window": {
                        "timezone": "Z",
                        "start": "00:00",
                        "end": "23:59",
                    },
                    "billing_period": "2026-09",
                    "quota_limit_segments": 1000,
                    "wallet_limit_minor": 100000,
                    "cost_per_segment_minor": 5,
                    "currency": "EUR",
                },
                "tenant-b": {
                    "enabled": True,
                    "tenant_id": "tenant-b",
                    "senders": ["TEST"],
                    "destination_prefixes": ["+49155"],
                    "route": "alternate",
                    "approved_recipients": ["+4915512345678"],
                    "consented_recipients": ["+4915512345678"],
                    "suppressed_recipients": [],
                    "delivery_window": {
                        "timezone": "Z",
                        "start": "00:00",
                        "end": "23:59",
                    },
                    "billing_period": "2026-09",
                    "quota_limit_segments": 1000,
                    "wallet_limit_minor": 100000,
                    "cost_per_segment_minor": 5,
                    "currency": "EUR",
                },
            }
        ),
    )
    monkeypatch.setenv("TELNEXA_MIDDLEWARE_API_KEY", "test-telnexa-key")
    monkeypatch.setenv("TELNEXA_WEBHOOK_SECRET", "test-telnexa-secret")
    configure_jasmin_route(
        monkeypatch, "synthetic", "route-synthetic-user", "route-synthetic-password"
    )
    configure_jasmin_route(
        monkeypatch, "alternate", "route-alternate-user", "route-alternate-password"
    )
    gateway.validate_live_route_authorities()
    submissions = []

    def urlopen(url, **_kwargs):
        if url.endswith("/ping"):
            return HealthyJasmin()
        submissions.append(urllib.parse.parse_qs(urllib.parse.urlsplit(url).query))
        return HealthyJasmin()

    app = gateway.Gateway(
        settings(
            tmp_path,
            live_submission_enabled=True,
            production_delivery_authorized=True,
            production_change_id="CHG-ROUTE-AUTHORITY",
        ),
        store(tmp_path),
        clock=lambda: now,
        urlopen=urlopen,
    )
    for index, tenant in enumerate(("tenant-a", "tenant-b"), start=1):
        body = json.dumps(
            valid_payload(
                customer_id=tenant,
                tenant_id=tenant,
                idempotency_key=f"route-idem-{index}",
            ),
            separators=(",", ":"),
        ).encode()
        code, result = app.outbound(
            body, outbound_headers(body, now, f"route-nonce-0000000{index}")
        )
        assert code == 202 and result["state"] == "submitted"
    assert [item["username"] for item in submissions] == [
        ["route-synthetic-user"],
        ["route-alternate-user"],
    ]
    assert [item["password"] for item in submissions] == [
        ["route-synthetic-password"],
        ["route-alternate-password"],
    ]
    monkeypatch.setenv(
        "JASMIN_ROUTE_ALTERNATE_API_USER", "route-synthetic-user"
    )
    with pytest.raises(RuntimeError, match="distinct Jasmin authorities"):
        gateway.validate_live_route_authorities()


def signed_headers(system: str, body: bytes, now: int, event_id: str):
    prefix = {"kyqra": "X-Kyqra", "telnexa": "X-Telnexa", "klyrow": "X-Klyrow"}[system]
    secret = f"test-{system}-secret"
    signature = hmac.new(
        secret.encode(), gateway.canonical(str(now), event_id, system, body), hashlib.sha256
    ).hexdigest()
    return {
        "Authorization": f"Bearer test-{system}-key",
        prefix + "-Timestamp": str(now),
        prefix + "-Event-Id": event_id,
        prefix + "-Signature": "sha256=" + signature,
        "X-Source-System": system,
    }


def test_ingress_authentication_replay_and_payload_conflict_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    now = 2_000_000_000
    for system in gateway.SYSTEMS:
        monkeypatch.setenv(f"{system.upper()}_MIDDLEWARE_API_KEY", f"test-{system}-key")
        monkeypatch.setenv(f"{system.upper()}_WEBHOOK_SECRET", f"test-{system}-secret")
    app = gateway.Gateway(
        settings(tmp_path, mode="middleware"), store(tmp_path), clock=lambda: now
    )
    body = json.dumps({"message_id": "message-1"}, separators=(",", ":")).encode()
    headers = signed_headers("klyrow", body, now, "event-0001")
    assert app.ingress("klyrow", "/api/v1/klyrow/events", body, headers)[0] == 202
    assert app.ingress("klyrow", "/api/v1/klyrow/events", body, headers)[0] == 409
    changed = json.dumps({"message_id": "message-2"}, separators=(",", ":")).encode()
    changed_headers = signed_headers("klyrow", changed, now, "event-0001")
    assert app.ingress("klyrow", "/api/v1/klyrow/events", changed, changed_headers)[0] == 409


def test_existing_live_database_schema_is_migrated_without_data_loss(tmp_path: Path):
    path = tmp_path / "integration.db"
    import sqlite3

    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TABLE events(
                event_id TEXT PRIMARY KEY, system TEXT NOT NULL, path TEXT NOT NULL,
                entity_key TEXT, payload TEXT NOT NULL, state TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0, next_attempt REAL NOT NULL DEFAULT 0,
                created_at REAL NOT NULL, last_error TEXT
            )"""
        )
        connection.execute(
            "INSERT INTO events(event_id,system,path,payload,state,created_at) VALUES('old-event','klyrow','/old','{\"old\":true}','queued',1)"
        )
        connection.execute(
            """CREATE TABLE sms_transactions(
                adapter_message_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL, payload_hash TEXT NOT NULL,
                payload TEXT NOT NULL, correlation_id TEXT, sender TEXT NOT NULL,
                destination TEXT NOT NULL, logical_route TEXT NOT NULL,
                validation_result TEXT NOT NULL, jasmin_dependency TEXT NOT NULL,
                state TEXT NOT NULL, carrier_submitted INTEGER NOT NULL DEFAULT 0,
                provider_message_id TEXT, provider_response TEXT, created_at REAL NOT NULL,
                UNIQUE(customer_id,idempotency_key)
            )"""
        )
        legacy_payload = json.dumps(
            {"body": "migration fixture"}, separators=(",", ":")
        )
        connection.execute(
            """INSERT INTO sms_transactions(
                adapter_message_id,customer_id,idempotency_key,payload_hash,
                payload,correlation_id,sender,destination,logical_route,
                validation_result,jasmin_dependency,state,carrier_submitted,
                provider_message_id,provider_response,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "old-sms", "legacy-customer", "legacy-idempotency",
                hashlib.sha256(legacy_payload.encode()).hexdigest(), legacy_payload,
                None, "TEST", "+4915512345678", "synthetic", "accepted",
                "jasmin", "queued", 0, None, None, 1,
            ),
        )
    value = gateway.Store(path)
    value.initialize()
    with value.connect() as connection:
        event = connection.execute(
            """SELECT payload,payload_sha256,dispatch_eligible
            FROM events WHERE event_id='old-event'"""
        ).fetchone()
        sms_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(sms_transactions)")
        }
        legacy_sms = connection.execute(
            "SELECT customer_id,tenant_id,payload FROM sms_transactions "
            "WHERE adapter_message_id='old-sms'"
        ).fetchone()
    assert event["payload"] == '{"old":true}'
    assert event["payload_sha256"] == hashlib.sha256(b'{"old":true}').hexdigest()
    assert event["dispatch_eligible"] == 0
    assert value.pending_events(2_000_000_000) == []
    assert "provider_response_sha256" in sms_columns
    assert "operation_token" in sms_columns
    assert "lease_expires_at" in sms_columns
    assert "effect_hash" in sms_columns
    assert "reconciliation_proof_sha256" in sms_columns
    assert "carrier_dlr_sha256" in sms_columns
    assert legacy_sms["customer_id"] == "legacy-customer"
    assert legacy_sms["tenant_id"] == "legacy-customer"
    assert json.loads(legacy_sms["payload"]) == {"body": "migration fixture"}


def test_legacy_sms_migration_prefers_explicit_customer_tenant_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "TELNEXA_CUSTOMER_POLICY_JSON",
        json.dumps({"shared-customer": {"tenant_id": "tenant-a"}}),
    )
    assert gateway.legacy_sms_tenant("shared-customer", {"body": "old"}) == "tenant-a"
    assert (
        gateway.legacy_sms_tenant(
            "shared-customer", {"tenant_id": "tenant-b", "body": "new"}
        )
        == "tenant-b"
    )
    for invalid in (None, "", " tenant-b", "tenant-b ", "x" * 129):
        with pytest.raises(ValueError, match="tenant_id_required"):
            gateway.legacy_sms_tenant(
                "shared-customer", {"tenant_id": invalid, "body": "malformed"}
            )


def test_ingress_rejects_stale_and_invalid_signatures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    now = 2_000_000_000
    monkeypatch.setenv("KYQRA_MIDDLEWARE_API_KEY", "test-kyqra-key")
    monkeypatch.setenv("KYQRA_WEBHOOK_SECRET", "test-kyqra-secret")
    app = gateway.Gateway(
        settings(tmp_path, mode="middleware"), store(tmp_path), clock=lambda: now
    )
    body = b'{"job_id":"job-1"}'
    stale = signed_headers("kyqra", body, now - 301, "event-stale")
    assert app.ingress("kyqra", "/api/v1/kyqra/jobs", body, stale)[0] == 401
    invalid = signed_headers("kyqra", body, now, "event-invalid")
    invalid["X-Kyqra-Signature"] = "sha256=" + "0" * 64
    assert app.ingress("kyqra", "/api/v1/kyqra/jobs", body, invalid)[0] == 401


def test_authentication_header_names_are_case_insensitive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    now = 2_000_000_000
    monkeypatch.setenv("KLYROW_MIDDLEWARE_API_KEY", "test-klyrow-key")
    monkeypatch.setenv("KLYROW_WEBHOOK_SECRET", "test-klyrow-secret")
    app = gateway.Gateway(
        settings(tmp_path, mode="middleware"), store(tmp_path), clock=lambda: now
    )
    body = b'{"message_id":"message-case"}'
    headers = {
        key.swapcase(): value
        for key, value in signed_headers("klyrow", body, now, "event-case-1").items()
    }
    assert app.ingress("klyrow", "/api/v1/klyrow/events", body, headers)[0] == 202


def test_kyqra_entity_duplicate_requires_the_same_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    now = 2_000_000_000
    monkeypatch.setenv("KYQRA_MIDDLEWARE_API_KEY", "test-kyqra-key")
    monkeypatch.setenv("KYQRA_WEBHOOK_SECRET", "test-kyqra-secret")
    app = gateway.Gateway(
        settings(tmp_path, mode="middleware"), store(tmp_path), clock=lambda: now
    )
    payload = {
        "job_id": "job-1",
        "record_id": "record-1",
        "source_url": "https://example.invalid/record",
        "business_name": "Synthetic",
        "crawl_timestamp": "2026-09-01T00:00:00Z",
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    first = signed_headers("kyqra", body, now, "event-entity-1")
    duplicate = signed_headers("kyqra", body, now, "event-entity-2")
    assert app.ingress("kyqra", "/api/v1/kyqra/results", body, first)[0] == 202
    assert app.ingress("kyqra", "/api/v1/kyqra/results", body, duplicate)[0] == 200
    payload["business_name"] = "Different"
    changed = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    conflict = signed_headers("kyqra", changed, now, "event-entity-3")
    assert app.ingress("kyqra", "/api/v1/kyqra/results", changed, conflict)[0] == 409


def test_kyqra_lifecycle_paths_do_not_conflict_on_shared_job_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    now = 2_000_000_000
    monkeypatch.setenv("KYQRA_MIDDLEWARE_API_KEY", "test-kyqra-key")
    monkeypatch.setenv("KYQRA_WEBHOOK_SECRET", "test-kyqra-secret")
    app = gateway.Gateway(
        settings(tmp_path, mode="middleware"), store(tmp_path), clock=lambda: now
    )
    for index, path in enumerate(
        (
            "/api/v1/kyqra/jobs",
            "/api/v1/kyqra/progress",
            "/api/v1/kyqra/failures",
        ),
        start=1,
    ):
        body = json.dumps({"job_id": "job-shared"}, separators=(",", ":")).encode()
        headers = signed_headers("kyqra", body, now, f"event-life-{index}")
        assert app.ingress("kyqra", path, body, headers)[0] == 202


@pytest.mark.parametrize(
    ("system", "path"),
    [
        ("kyqra", "/api/v1/kyqra/jobs"),
        ("telnexa", "/api/v1/telnexa/provider-status"),
        ("klyrow", "/api/v1/klyrow/campaigns"),
        ("klyrow", "/api/v1/klyrow/contacts"),
    ],
)
def test_unmapped_ingress_contracts_remain_dispatch_quarantined(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    system: str,
    path: str,
):
    now = 2_000_000_000
    monkeypatch.setenv(f"{system.upper()}_MIDDLEWARE_API_KEY", f"test-{system}-key")
    monkeypatch.setenv(f"{system.upper()}_WEBHOOK_SECRET", f"test-{system}-secret")
    state = store(tmp_path)
    app = gateway.Gateway(
        settings(
            tmp_path,
            mode="middleware",
            middleware_forwarding_enabled=True,
            downstream_url="https://middleware.invalid/v1/events",
        ),
        state,
        clock=lambda: now,
        urlopen=lambda *_args, **_kwargs: pytest.fail("quarantined event dispatched"),
    )
    body = json.dumps({"tenant_id": "tenant-a"}, separators=(",", ":")).encode()
    event_id = "event-quarantine-" + system + path.rsplit("/", 1)[-1]
    headers = signed_headers(system, body, now, event_id)
    assert app.ingress(system, path, body, headers)[0] == 202
    with state.connect() as connection:
        row = connection.execute(
            "SELECT dispatch_eligible,state FROM events WHERE event_id=?", (event_id,)
        ).fetchone()
    assert dict(row) == {"dispatch_eligible": 0, "state": "queued"}
    assert app.dispatch_once() == 0


@pytest.mark.parametrize(
    "tenant_id", [None, "", "   ", " tenant-a", "tenant-a ", "x" * 129]
)
def test_mapped_forwarding_callback_requires_tenant_before_acknowledgement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tenant_id: str | None,
):
    now = 2_000_000_000
    monkeypatch.setenv("KLYROW_MIDDLEWARE_API_KEY", "test-klyrow-key")
    monkeypatch.setenv("KLYROW_WEBHOOK_SECRET", "test-klyrow-secret")
    state = store(tmp_path)
    app = gateway.Gateway(
        settings(
            tmp_path,
            mode="middleware",
            middleware_forwarding_enabled=True,
            downstream_url="https://middleware.invalid/v1/events",
        ),
        state,
        clock=lambda: now,
        urlopen=lambda *_args, **_kwargs: pytest.fail("invalid event dispatched"),
    )
    payload = {} if tenant_id is None else {"tenant_id": tenant_id}
    body = json.dumps(payload, separators=(",", ":")).encode()
    event_id = "event-missing-tenant-" + hashlib.sha256(body).hexdigest()[:16]
    code, result = app.ingress(
        "klyrow",
        "/api/v1/klyrow/events",
        body,
        signed_headers("klyrow", body, now, event_id),
    )
    assert (code, result) == (422, {"detail": "tenant_id_required"})
    with state.connect() as connection:
        assert connection.execute(
            "SELECT 1 FROM events WHERE event_id=?", (event_id,)
        ).fetchone() is None


@pytest.mark.parametrize(
    "correlation_id", [{"nested": "value"}, ["value"], 7, "", " value", "value ", "x" * 129]
)
def test_mapped_forwarding_callback_rejects_invalid_correlation_before_acknowledgement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    correlation_id,
):
    now = 2_000_000_000
    monkeypatch.setenv("KLYROW_MIDDLEWARE_API_KEY", "test-klyrow-key")
    monkeypatch.setenv("KLYROW_WEBHOOK_SECRET", "test-klyrow-secret")
    state = store(tmp_path)
    app = gateway.Gateway(
        settings(
            tmp_path,
            mode="middleware",
            middleware_forwarding_enabled=True,
            downstream_url="https://middleware.invalid/v1/events",
        ),
        state,
        clock=lambda: now,
        urlopen=lambda *_args, **_kwargs: pytest.fail("invalid event dispatched"),
    )
    payload = {
        "tenant_id": "tenant-a",
        "message_id": "message-correlation-1",
        "event_type": "klyrow.email.delivered",
        "correlation_id": correlation_id,
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    event_id = "event-invalid-correlation-" + hashlib.sha256(body).hexdigest()[:16]
    code, result = app.ingress(
        "klyrow",
        "/api/v1/klyrow/events",
        body,
        signed_headers("klyrow", body, now, event_id),
    )
    assert (code, result) == (422, {"detail": "invalid_correlation_id"})
    with state.connect() as connection:
        assert connection.execute(
            "SELECT 1 FROM events WHERE event_id=?", (event_id,)
        ).fetchone() is None


class HttpResponse:
    def __init__(self, status: int = 202, body: bytes = b"{}"):
        self.status = status
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, limit=None):
        return self.body if limit is None else self.body[:limit]


def dispatch_receipt(request, *, status: int = 202, duplicate: bool = False):
    headers = {key.lower(): value for key, value in request.header_items()}
    envelope = json.loads(request.data)
    body = json.dumps(
        {
            "event_id": headers["x-event-id"],
            "correlation_id": "receipt-correlation",
            "duplicate": duplicate,
            "projection": gateway.expected_dispatch_projection(
                envelope["event_type"], envelope["payload"], headers["x-event-id"]
            ),
            "state": "queued",
        },
        separators=(",", ":"),
    ).encode()
    return HttpResponse(status, body)


def replay_projection_receipt(request) -> bytes:
    headers = {key.lower(): value for key, value in request.header_items()}
    envelope = json.loads(request.data)
    return json.dumps(
        {
            "error": "replayed_event_id",
            "event_id": headers["x-event-id"],
            "projection": gateway.expected_dispatch_projection(
                envelope["event_type"], envelope["payload"], headers["x-event-id"]
            ),
        },
        separators=(",", ":"),
    ).encode()


def test_new_ingress_events_are_dispatched_with_control_plane_authentication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    now = 2_000_000_000
    monkeypatch.setenv("KLYROW_MIDDLEWARE_API_KEY", "test-klyrow-key")
    monkeypatch.setenv("KLYROW_WEBHOOK_SECRET", "test-klyrow-secret")
    requests = []
    transports = []

    def urlopen(request, **kwargs):
        requests.append(request)
        transports.append(kwargs)
        return dispatch_receipt(request)

    state = store(tmp_path)
    app = gateway.Gateway(
        settings(
            tmp_path,
            mode="middleware",
            middleware_forwarding_enabled=True,
            downstream_url="https://middleware.invalid/v1/events",
        ),
        state,
        clock=lambda: now,
        urlopen=urlopen,
    )
    payload = {
        "message_id": "message-1",
        "event_type": "klyrow.email.delivered",
        "tenant_id": "tenant-a",
        "customer_id": "customer-a",
        "idempotency_key": "delivery-1",
        "occurred_at": "2026-09-01T00:00:00Z",
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    headers = signed_headers("klyrow", body, now, "event-dispatch-1")
    assert app.ingress("klyrow", "/api/v1/klyrow/events", body, headers)[0] == 202
    assert app.dispatch_once() == 1
    assert len(requests) == 1
    assert transports == [{"timeout": 10, "context": app.middleware_tls_context}]
    request = requests[0]
    assert request.full_url == "https://middleware.invalid/v1/events"
    sent = json.loads(request.data)
    assert sent == {
        "customer_id": "customer-a",
        "event_type": "klyrow.email.event",
        "event_version": "1.0",
        "idempotency_key": "delivery-1",
        "occurred_at": "2026-09-01T00:00:00Z",
        "payload": payload,
        "tenant_id": "tenant-a",
    }
    request_headers = {key.lower(): value for key, value in request.header_items()}
    assert request_headers["authorization"] == "Bearer test-klyrow-key"
    assert request_headers["x-event-source"] == "klyrow"
    assert request_headers["x-event-id"] == "event-dispatch-1"
    assert request_headers["x-timestamp"] == str(now)
    expected = hmac.new(
        b"test-klyrow-secret",
        gateway.canonical(str(now), "event-dispatch-1", "klyrow", request.data),
        hashlib.sha256,
    ).hexdigest()
    assert request_headers["x-signature"] == "sha256=" + expected
    with state.connect() as connection:
        row = connection.execute(
            "SELECT state,attempts FROM events WHERE event_id='event-dispatch-1'"
        ).fetchone()
    assert dict(row) == {"state": "delivered", "attempts": 1}


@pytest.mark.parametrize(
    "event_type",
    [None, "", "klyrow.email.opened", "klyrow.email.complained"],
)
def test_unsupported_klyrow_status_is_rejected_before_persistence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    event_type: str | None,
):
    now = 2_000_000_000
    monkeypatch.setenv("KLYROW_MIDDLEWARE_API_KEY", "test-klyrow-key")
    monkeypatch.setenv("KLYROW_WEBHOOK_SECRET", "test-klyrow-secret")
    state = store(tmp_path)
    app = gateway.Gateway(
        settings(
            tmp_path,
            mode="middleware",
            middleware_forwarding_enabled=True,
            downstream_url="https://middleware.invalid/v1/events",
        ),
        state,
        clock=lambda: now,
    )
    payload = {
        "message_id": "message-unsupported",
        "tenant_id": "tenant-a",
        "idempotency_key": "unsupported-1",
        "occurred_at": "2026-09-01T00:00:00Z",
    }
    if event_type is not None:
        payload["event_type"] = event_type
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    code, result = app.ingress(
        "klyrow",
        "/api/v1/klyrow/events",
        body,
        signed_headers("klyrow", body, now, "event-unsupported-status"),
    )
    assert code == 422
    assert result == {"detail": "unsupported_klyrow_email_status"}
    with state.connect() as connection:
        assert connection.execute("SELECT count(*) FROM events").fetchone()[0] == 0


@pytest.mark.parametrize("event_type", sorted(gateway.KLYROW_FORWARDED_EMAIL_STATUS_EVENTS))
def test_supported_klyrow_status_is_dispatch_eligible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    event_type: str,
):
    now = 2_000_000_000
    monkeypatch.setenv("KLYROW_MIDDLEWARE_API_KEY", "test-klyrow-key")
    monkeypatch.setenv("KLYROW_WEBHOOK_SECRET", "test-klyrow-secret")
    state = store(tmp_path)
    app = gateway.Gateway(
        settings(
            tmp_path,
            mode="middleware",
            middleware_forwarding_enabled=True,
            downstream_url="https://middleware.invalid/v1/events",
        ),
        state,
        clock=lambda: now,
    )
    payload = {
        "message_id": "message-supported",
        "event_type": event_type,
        "tenant_id": "tenant-a",
        "idempotency_key": "supported-1",
        "occurred_at": "2026-09-01T00:00:00Z",
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    code, result = app.ingress(
        "klyrow",
        "/api/v1/klyrow/events",
        body,
        signed_headers("klyrow", body, now, f"event-{event_type}"),
    )
    assert code == 202
    assert result["accepted"] is True
    with state.connect() as connection:
        row = connection.execute(
            "SELECT dispatch_eligible,state FROM events"
        ).fetchone()
    assert dict(row) == {"dispatch_eligible": 1, "state": "queued"}


def test_unrelated_success_response_cannot_mark_event_delivered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    now = 2_000_000_000
    monkeypatch.setenv("KLYROW_MIDDLEWARE_API_KEY", "downstream-key")
    monkeypatch.setenv("KLYROW_WEBHOOK_SECRET", "downstream-secret")
    state = store(tmp_path)
    payload = json.dumps({"tenant_id": "tenant-a"}, separators=(",", ":"))
    assert state.insert_event(
        "event-untrusted-2xx",
        "klyrow",
        "/api/v1/klyrow/events",
        None,
        payload,
        now,
        True,
    ) == "accepted"
    app = gateway.Gateway(
        settings(
            tmp_path,
            mode="middleware",
            middleware_forwarding_enabled=True,
            downstream_url="https://middleware.invalid/v1/events",
        ),
        state,
        clock=lambda: now,
        urlopen=lambda *_args, **_kwargs: HttpResponse(202, b'{"accepted":true}'),
    )
    assert app.dispatch_once() == 1
    with state.connect() as connection:
        row = connection.execute(
            "SELECT state,attempts,last_error FROM events WHERE event_id=?",
            ("event-untrusted-2xx",),
        ).fetchone()
    assert dict(row) == {
        "state": "queued",
        "attempts": 1,
        "last_error": "DispatchOutcomeUnknown",
    }

    with pytest.raises(RuntimeError, match="invalid_downstream_receipt"):
        gateway.verify_dispatch_receipt(
            202,
            b'{"event_id":"event-untrusted-2xx","correlation_id":"receipt",'
            b'"duplicate":false,"projection":null,"state":[]}',
            "event-untrusted-2xx",
            0,
            None,
            None,
            False,
        )


def test_authenticated_replay_receipt_reconciles_only_after_unknown_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    with pytest.raises(RuntimeError, match="downstream_receipt_rejected"):
        gateway.verify_dispatch_receipt(
            409,
            b'{"error":"replayed_event_id"}',
            "event-lost-receipt",
            0,
            None,
            None,
            False,
        )
    with pytest.raises(RuntimeError, match="downstream_receipt_rejected"):
        gateway.verify_dispatch_receipt(
            409,
            b'{"error":"replayed_event_id"}',
            "event-lost-receipt",
            1,
            "RuntimeError",
            None,
            False,
        )
    now = [2_000_000_000.0]
    monkeypatch.setenv("TELNEXA_MIDDLEWARE_API_KEY", "downstream-key")
    monkeypatch.setenv("TELNEXA_WEBHOOK_SECRET", "downstream-secret")
    state = store(tmp_path)
    payload = json.dumps({
        "tenant_id": "tenant-a",
        "message_id": "message-lost-receipt",
        "provider_message_id": "carrier-lost-receipt",
        "status": "submitted",
    }, separators=(",", ":"))
    assert state.insert_event(
        "event-lost-receipt",
        "telnexa",
        gateway.TELNEXA_SUBMITTED_EVENT_PATH,
        None,
        payload,
        now[0],
        True,
    ) == "accepted"
    responses = ["lost", "replay"]

    def urlopen(request, **_kwargs):
        if responses.pop(0) == "lost":
            raise TimeoutError("response lost after receiver commit")
        raise urllib.error.HTTPError(
            request.full_url,
            409,
            "Conflict",
            {},
            BytesIO(replay_projection_receipt(request)),
        )

    app = gateway.Gateway(
        settings(
            tmp_path,
            mode="middleware",
            middleware_forwarding_enabled=True,
            downstream_url="https://middleware.invalid/v1/events",
        ),
        state,
        clock=lambda: now[0],
        urlopen=urlopen,
    )
    assert app.dispatch_once() == 1
    now[0] += 3
    assert app.dispatch_once() == 1
    with state.connect() as connection:
        row = connection.execute(
            "SELECT state,attempts,last_error FROM events WHERE event_id=?",
            ("event-lost-receipt",),
        ).fetchone()
    assert dict(row) == {"state": "delivered", "attempts": 2, "last_error": None}
    assert responses == []


def test_http_error_after_receiver_commit_reconciles_by_exact_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [2_000_000_000.0]
    monkeypatch.setenv("TELNEXA_MIDDLEWARE_API_KEY", "downstream-key")
    monkeypatch.setenv("TELNEXA_WEBHOOK_SECRET", "downstream-secret")
    state = store(tmp_path)
    payload = json.dumps(
        {
            "tenant_id": "tenant-a",
            "message_id": "message-http-error",
            "provider_message_id": "carrier-http-error",
            "status": "submitted",
        },
        separators=(",", ":"),
    )
    assert state.insert_event(
        "event-http-error",
        "telnexa",
        gateway.TELNEXA_SUBMITTED_EVENT_PATH,
        None,
        payload,
        now[0],
        True,
    ) == "accepted"
    responses = [500, 409]

    def urlopen(request, **_kwargs):
        status = responses.pop(0)
        if status == 500:
            raise urllib.error.HTTPError(
                request.full_url,
                status,
                "Internal Server Error",
                {},
                BytesIO(b'{"error":"internal"}'),
            )
        raise urllib.error.HTTPError(
            request.full_url,
            status,
            "Conflict",
            {},
            BytesIO(replay_projection_receipt(request)),
        )

    app = gateway.Gateway(
        settings(
            tmp_path,
            mode="middleware",
            middleware_forwarding_enabled=True,
            downstream_url="https://middleware.invalid/v1/events",
        ),
        state,
        clock=lambda: now[0],
        urlopen=urlopen,
    )
    assert app.dispatch_once() == 1
    with state.connect() as connection:
        first = connection.execute(
            "SELECT state,attempts,last_error FROM events WHERE event_id=?",
            ("event-http-error",),
        ).fetchone()
    assert dict(first) == {
        "state": "queued",
        "attempts": 1,
        "last_error": "DispatchOutcomeUnknown",
    }
    now[0] += 3
    assert app.dispatch_once() == 1
    with state.connect() as connection:
        reconciled = connection.execute(
            "SELECT state,attempts,last_error FROM events WHERE event_id=?",
            ("event-http-error",),
        ).fetchone()
    assert dict(reconciled) == {
        "state": "delivered",
        "attempts": 2,
        "last_error": None,
    }
    assert responses == []


def test_replay_receipt_requires_exact_durable_projection() -> None:
    expected = {
        "event_id": "event-lost-receipt",
        "message_id": "message-lost-receipt",
        "provider_message_id": "carrier-lost-receipt",
        "raw_status": "delivery_success",
        "status": "delivered",
    }
    mismatched = dict(expected, status="accepted")
    raw = json.dumps(
        {
            "error": "replayed_event_id",
            "event_id": "event-lost-receipt",
            "projection": mismatched,
        },
        separators=(",", ":"),
    ).encode()
    with pytest.raises(RuntimeError, match="downstream_receipt_rejected"):
        gateway.verify_dispatch_receipt(
            409,
            raw,
            "event-lost-receipt",
            1,
            "DispatchOutcomeUnknown",
            expected,
            True,
        )


def test_external_status_receipt_allows_an_absent_local_projection() -> None:
    expected = {
        "event_id": "external-event",
        "message_id": "external-message",
        "provider_message_id": "external-carrier-message",
        "raw_status": "delivery_success",
        "status": "delivered",
    }
    raw = json.dumps(
        {
            "event_id": "external-event",
            "correlation_id": "external-correlation",
            "duplicate": False,
            "projection": None,
            "state": "queued",
        },
        separators=(",", ":"),
    ).encode()
    assert gateway.verify_dispatch_receipt(
        202,
        raw,
        "external-event",
        0,
        None,
        expected,
        False,
    ) == "accepted"
    replay = json.dumps(
        {
            "error": "replayed_event_id",
            "event_id": "external-event",
            "projection": None,
        },
        separators=(",", ":"),
    ).encode()
    assert gateway.verify_dispatch_receipt(
        409,
        replay,
        "external-event",
        1,
        "DispatchOutcomeUnknown",
        expected,
        False,
    ) == "reconciled_event"


@pytest.mark.parametrize(
    ("event_type", "payload", "raw_status", "normalized_status"),
    [
        (
            "klyrow.email.event",
            {
                "event_type": "klyrow.email.delivered",
                "message_id": "klyrow-message-1",
                "provider_message_id": "klyrow-provider-1",
                "status": "delivery_success",
            },
            "delivery_success",
            "delivered",
        ),
        (
            "klyrow.email.event",
            {
                "event_type": "klyrow.email.held",
                "message_id": "klyrow-message-2",
                "provider_message_id": "klyrow-provider-2",
                "status": "Held",
            },
            "deferred",
            "deferred",
        ),
        (
            "klyrow.email.complained",
            {
                "message_id": "klyrow-message-3",
                "provider_message_id": "klyrow-provider-3",
                "status": "spam_complaint",
            },
            "spam_complaint",
            "complained",
        ),
    ],
)
def test_klyrow_status_receipts_use_the_exact_receiver_projection(
    event_type: str,
    payload: dict[str, str],
    raw_status: str,
    normalized_status: str,
) -> None:
    event_id = "klyrow-projection-" + normalized_status
    expected = {
        "event_id": event_id,
        "message_id": payload["message_id"],
        "provider_message_id": payload["provider_message_id"],
        "raw_status": raw_status,
        "status": normalized_status,
    }
    assert gateway.expected_dispatch_projection(event_type, payload, event_id) == expected
    accepted = json.dumps(
        {
            "event_id": event_id,
            "correlation_id": "klyrow-projection-correlation",
            "duplicate": False,
            "projection": expected,
            "state": "queued",
        },
        separators=(",", ":"),
    ).encode()
    assert gateway.verify_dispatch_receipt(
        202, accepted, event_id, 0, None, expected, False
    ) == "accepted"
    replay = json.dumps(
        {
            "error": "replayed_event_id",
            "event_id": event_id,
            "projection": expected,
        },
        separators=(",", ":"),
    ).encode()
    assert gateway.verify_dispatch_receipt(
        409,
        replay,
        event_id,
        1,
        "DispatchOutcomeUnknown",
        expected,
        False,
    ) == "reconciled_event"


def test_lost_receipt_body_is_reconciled_by_the_exact_replay_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    class LostBody(HttpResponse):
        def read(self, _limit=None):
            raise OSError("response body lost after receiver commit")

    now = [2_000_000_000.0]
    monkeypatch.setenv("TELNEXA_MIDDLEWARE_API_KEY", "downstream-key")
    monkeypatch.setenv("TELNEXA_WEBHOOK_SECRET", "downstream-secret")
    state = store(tmp_path)
    payload = json.dumps({
        "tenant_id": "tenant-a",
        "message_id": "message-lost-body",
        "provider_message_id": "carrier-lost-body",
        "status": "submitted",
    }, separators=(",", ":"))
    assert state.insert_event(
        "event-lost-body",
        "telnexa",
        gateway.TELNEXA_SUBMITTED_EVENT_PATH,
        None,
        payload,
        now[0],
        True,
    ) == "accepted"
    responses = [LostBody(), "replay"]

    def urlopen(request, **_kwargs):
        response = responses.pop(0)
        if response == "replay":
            raise urllib.error.HTTPError(
                request.full_url,
                409,
                "Conflict",
                {},
                BytesIO(replay_projection_receipt(request)),
            )
        return response

    app = gateway.Gateway(
        settings(
            tmp_path,
            mode="middleware",
            middleware_forwarding_enabled=True,
            downstream_url="https://middleware.invalid/v1/events",
        ),
        state,
        clock=lambda: now[0],
        urlopen=urlopen,
    )
    assert app.dispatch_once() == 1
    with state.connect() as connection:
        first_attempt = connection.execute(
            "SELECT state,attempts,last_error FROM events WHERE event_id=?",
            ("event-lost-body",),
        ).fetchone()
    assert dict(first_attempt) == {
        "state": "queued",
        "attempts": 1,
        "last_error": "DispatchOutcomeUnknown",
    }
    now[0] += 3
    assert app.dispatch_once() == 1
    with state.connect() as connection:
        row = connection.execute(
            "SELECT state,attempts,last_error FROM events WHERE event_id=?",
            ("event-lost-body",),
        ).fetchone()
    assert dict(row) == {"state": "delivered", "attempts": 2, "last_error": None}
    assert responses == []


def test_crash_after_receiver_commit_recovers_from_durable_dispatch_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    class SimulatedProcessExit(BaseException):
        pass

    now = [2_000_000_000.0]
    monkeypatch.setenv("TELNEXA_MIDDLEWARE_API_KEY", "downstream-key")
    monkeypatch.setenv("TELNEXA_WEBHOOK_SECRET", "downstream-secret")
    state = store(tmp_path)
    payload = json.dumps({
        "tenant_id": "tenant-a",
        "message_id": "message-process-exit",
        "provider_message_id": "carrier-process-exit",
        "status": "submitted",
    }, separators=(",", ":"))
    assert state.insert_event(
        "event-process-exit",
        "telnexa",
        gateway.TELNEXA_SUBMITTED_EVENT_PATH,
        None,
        payload,
        now[0],
        True,
    ) == "accepted"

    def lose_process_after_commit(_event_id, _expected_attempts):
        raise SimulatedProcessExit

    original_mark_event_delivered = state.mark_event_delivered
    monkeypatch.setattr(state, "mark_event_delivered", lose_process_after_commit)
    first = gateway.Gateway(
        settings(
            tmp_path,
            mode="middleware",
            middleware_forwarding_enabled=True,
            downstream_url="https://middleware.invalid/v1/events",
        ),
        state,
        clock=lambda: now[0],
        urlopen=lambda request, **_kwargs: dispatch_receipt(request),
    )
    with pytest.raises(SimulatedProcessExit):
        first.dispatch_once()
    with state.connect() as connection:
        claimed = connection.execute(
            "SELECT state,attempts,last_error,next_attempt FROM events WHERE event_id=?",
            ("event-process-exit",),
        ).fetchone()
    assert dict(claimed) == {
        "state": "dispatching",
        "attempts": 1,
        "last_error": "DispatchOutcomeUnknown",
        "next_attempt": now[0] + gateway.DISPATCH_LEASE_SECONDS,
    }
    assert state.pending_events(now[0]) == []

    monkeypatch.setattr(state, "mark_event_delivered", original_mark_event_delivered)
    now[0] += gateway.DISPATCH_LEASE_SECONDS + 1

    def replay(request, **_kwargs):
        raise urllib.error.HTTPError(
            request.full_url,
            409,
            "Conflict",
            {},
            BytesIO(replay_projection_receipt(request)),
        )

    recovered = gateway.Gateway(
        settings(
            tmp_path,
            mode="middleware",
            middleware_forwarding_enabled=True,
            downstream_url="https://middleware.invalid/v1/events",
        ),
        state,
        clock=lambda: now[0],
        urlopen=replay,
    )
    assert recovered.dispatch_once() == 1
    with state.connect() as connection:
        row = connection.execute(
            "SELECT state,attempts,last_error FROM events WHERE event_id=?",
            ("event-process-exit",),
        ).fetchone()
    assert dict(row) == {"state": "delivered", "attempts": 2, "last_error": None}


def test_dispatch_uses_each_selected_source_identity_and_contracted_event_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    now = 2_000_000_000
    source_paths = {
        "kyqra": "/api/v1/kyqra/failures",
        "telnexa": "/api/v1/telnexa/inbound",
        "klyrow": "/api/v1/klyrow/events",
    }
    expected_types = {
        "kyqra": "kyqra.job.failed",
        "telnexa": "telnexa.sms.received",
        "klyrow": "klyrow.email.event",
    }
    for source in gateway.SYSTEMS:
        monkeypatch.setenv(
            f"{source.upper()}_MIDDLEWARE_API_KEY", f"forward-{source}-key"
        )
        monkeypatch.setenv(
            f"{source.upper()}_WEBHOOK_SECRET", f"forward-{source}-secret"
        )
    requests = []

    def urlopen(request, **_kwargs):
        requests.append(request)
        return dispatch_receipt(request)

    state = store(tmp_path)
    for source, path in source_paths.items():
        payload = {
            "tenant_id": "tenant-a",
            "event_type": (
                "klyrow.email.bounced" if source == "klyrow" else expected_types[source]
            ),
        }
        assert state.insert_event(
            f"event-{source}",
            source,
            path,
            None,
            json.dumps(payload, separators=(",", ":"), sort_keys=True),
            now,
            True,
        ) == "accepted"
    app = gateway.Gateway(
        settings(
            tmp_path,
            mode="middleware",
            middleware_forwarding_enabled=True,
            downstream_url="https://middleware.invalid/v1/events",
        ),
        state,
        clock=lambda: now,
        urlopen=urlopen,
    )
    assert app.dispatch_once() == 3
    assert len(requests) == 3
    for request in requests:
        request_headers = {key.lower(): value for key, value in request.header_items()}
        source = request_headers["x-event-source"]
        assert request_headers["authorization"] == f"Bearer forward-{source}-key"
        envelope = json.loads(request.data)
        assert envelope["event_type"] == expected_types[source]
        expected_signature = hmac.new(
            f"forward-{source}-secret".encode(),
            gateway.canonical(
                str(now), request_headers["x-event-id"], source, request.data
            ),
            hashlib.sha256,
        ).hexdigest()
        assert request_headers["x-signature"] == "sha256=" + expected_signature
    source_text = (SERVICE / "gateway.py").read_text()
    assert "MIDDLEWARE_EVENTS_API_KEY" not in source_text
    assert "MIDDLEWARE_EVENTS_HMAC_SECRET" not in source_text


def test_dispatch_failures_are_bounded_and_dead_lettered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    now = [2_000_000_000.0]
    monkeypatch.setenv("KLYROW_MIDDLEWARE_API_KEY", "downstream-key")
    monkeypatch.setenv("KLYROW_WEBHOOK_SECRET", "downstream-secret")
    state = store(tmp_path)
    payload = json.dumps({"tenant_id": "tenant-a"}, separators=(",", ":"))
    assert state.insert_event(
        "event-failure-1",
        "klyrow",
        "/api/v1/klyrow/events",
        None,
        payload,
        now[0],
        True,
    ) == "accepted"

    requests = []

    def unavailable(request, **_kwargs):
        requests.append(request)
        raise TimeoutError("synthetic timeout")

    app = gateway.Gateway(
        settings(
            tmp_path,
            mode="middleware",
            middleware_forwarding_enabled=True,
            downstream_url="https://middleware.invalid/v1/events",
        ),
        state,
        clock=lambda: now[0],
        urlopen=unavailable,
    )
    for _ in range(5):
        assert app.dispatch_once() == 1
        now[0] += 1_000
    with state.connect() as connection:
        row = connection.execute(
            "SELECT state,attempts,last_error FROM events WHERE event_id='event-failure-1'"
        ).fetchone()
    assert dict(row) == {
        "state": "queued",
        "attempts": 5,
        "last_error": "DispatchOutcomeUnknown",
    }
    assert "X-reconciliation-only" not in requests[4].headers
    assert app.dispatch_once() == 1
    assert requests[5].headers["X-reconciliation-only"] == "true"
    with state.connect() as connection:
        row = connection.execute(
            "SELECT state,attempts,last_error FROM events WHERE event_id='event-failure-1'"
        ).fetchone()
    assert dict(row) == {
        "state": "dead_letter",
        "attempts": 6,
        "last_error": "DispatchOutcomeUnknown",
    }
    assert app.dispatch_once() == 0


def test_final_unknown_outcome_gets_one_readback_only_reconciliation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [2_000_000_000.0]
    monkeypatch.setenv("TELNEXA_MIDDLEWARE_API_KEY", "downstream-key")
    monkeypatch.setenv("TELNEXA_WEBHOOK_SECRET", "downstream-secret")
    state = store(tmp_path)
    payload = json.dumps(
        {"tenant_id": "tenant-a", "message_id": "message-reconcile-final"},
        separators=(",", ":"),
    )
    event_id = "event-final-reconciliation"
    assert state.insert_event(
        event_id,
        "telnexa",
        "/api/v1/telnexa/inbound",
        "message-reconcile-final",
        payload,
        now[0],
        True,
    ) == "accepted"
    requests = []

    def urlopen(request, **_kwargs):
        requests.append(request)
        if len(requests) <= 5:
            raise TimeoutError("synthetic lost response")
        assert request.headers["X-reconciliation-only"] == "true"
        receipt = json.dumps(
            {
                "error": "replayed_event_id",
                "event_id": event_id,
                "projection": None,
            },
            separators=(",", ":"),
        ).encode()
        raise urllib.error.HTTPError(
            request.full_url, 409, "Conflict", {}, BytesIO(receipt)
        )

    app = gateway.Gateway(
        settings(
            tmp_path,
            mode="shared",
            middleware_forwarding_enabled=True,
            downstream_url="https://middleware.invalid/v1/events",
        ),
        state,
        clock=lambda: now[0],
        urlopen=urlopen,
    )
    for _ in range(6):
        assert app.dispatch_once() == 1
        now[0] += 1_000
    with state.connect() as connection:
        delivered = connection.execute(
            "SELECT state,attempts,last_error FROM events WHERE event_id=?",
            (event_id,),
        ).fetchone()
    assert dict(delivered) == {
        "state": "delivered",
        "attempts": 6,
        "last_error": None,
    }
    assert len(requests) == 6


def test_dispatcher_startup_requires_credentials_and_starts_daemon(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    app = gateway.Gateway(
        settings(
            tmp_path,
            mode="middleware",
            middleware_forwarding_enabled=True,
            downstream_url="https://middleware.invalid/v1/events",
        ),
        store(tmp_path),
        middleware_tls_context=object(),
    )
    with pytest.raises(RuntimeError, match="KYQRA_MIDDLEWARE_API_KEY"):
        gateway.start_dispatcher(app)
    for source in gateway.SYSTEMS:
        monkeypatch.setenv(
            f"{source.upper()}_MIDDLEWARE_API_KEY", f"forward-{source}-key"
        )
        monkeypatch.setenv(
            f"{source.upper()}_WEBHOOK_SECRET", f"forward-{source}-secret"
        )
    started = []

    class FakeThread:
        def __init__(self, **values):
            self.values = values

        def start(self):
            started.append(self.values)

    monkeypatch.setattr(gateway.threading, "Thread", FakeThread)
    gateway.start_dispatcher(app)
    assert len(started) == 1
    assert started[0]["target"] is gateway.dispatch_worker
    assert started[0]["args"] == (app,)
    assert started[0]["daemon"] is True

    for source in ("kyqra", "klyrow"):
        monkeypatch.delenv(f"{source.upper()}_MIDDLEWARE_API_KEY")
        monkeypatch.delenv(f"{source.upper()}_WEBHOOK_SECRET")
    shared_app = gateway.Gateway(
        settings(
            tmp_path,
            middleware_forwarding_enabled=True,
            downstream_url="https://middleware.invalid/v1/events",
        ),
        store(tmp_path),
        middleware_tls_context=object(),
    )
    gateway.start_dispatcher(shared_app)
    assert len(started) == 2
    assert started[1]["args"] == (shared_app,)


class HealthyJasmin:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, _limit=None):
        return b'Success "07033084-5cfd-4812-90a4-e4d24ffb6e3d"'


class JasminResponse(HealthyJasmin):
    def __init__(self, body: bytes):
        self.body = body

    def read(self, _limit=None):
        return self.body


class JasminReceiptTimeout(HealthyJasmin):
    def read(self, _limit=None):
        raise TimeoutError("synthetic timeout after carrier request")


def outbound_headers(body: bytes, now: int, nonce: str):
    secret = "test-telnexa-secret"
    signature = hmac.new(
        secret.encode(), gateway.outbound_canonical(str(now), nonce, body), hashlib.sha256
    ).hexdigest()
    return {
        "Authorization": "Bearer test-telnexa-key",
        "X-Codestra-Timestamp": str(now),
        "X-Codestra-Nonce": nonce,
        "X-Codestra-Signature": "sha256=" + signature,
    }


def test_no_effect_outbound_is_idempotent_and_never_calls_carrier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    now = 2_000_000_000
    configure_tenant(monkeypatch)
    monkeypatch.setenv("TELNEXA_MIDDLEWARE_API_KEY", "test-telnexa-key")
    monkeypatch.setenv("TELNEXA_WEBHOOK_SECRET", "test-telnexa-secret")
    carrier_calls = []

    def urlopen(url, **_kwargs):
        carrier_calls.append(url)
        assert url.endswith("/ping")
        return HealthyJasmin()

    app = gateway.Gateway(settings(tmp_path), store(tmp_path), clock=lambda: now, urlopen=urlopen)
    body = json.dumps(valid_payload(), separators=(",", ":")).encode()
    first_headers = outbound_headers(body, now, "nonce-000000000001")
    code, response = app.outbound(body, first_headers)
    assert code == 202
    assert response["carrier_submitted"] is False
    assert response["state"] == "mock_accepted"
    retry_headers = outbound_headers(body, now, "nonce-000000000002")
    code, retry = app.outbound(body, retry_headers)
    assert code == 202 and retry["duplicate"] is True
    assert retry["adapter_message_id"] == response["adapter_message_id"]
    assert carrier_calls == ["http://jasmin:1401/ping"]


def test_dependency_failure_reservation_is_resumed_without_duplicate_effect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    now = 2_000_000_000
    configure_tenant(monkeypatch)
    monkeypatch.setenv("TELNEXA_MIDDLEWARE_API_KEY", "test-telnexa-key")
    monkeypatch.setenv("TELNEXA_WEBHOOK_SECRET", "test-telnexa-secret")
    probes = ["unreachable", "reachable"]

    def urlopen(url, **_kwargs):
        assert url.endswith("/ping")
        if probes.pop(0) == "unreachable":
            raise TimeoutError("synthetic dependency outage")
        return HealthyJasmin()

    state = store(tmp_path)
    app = gateway.Gateway(
        settings(tmp_path), state, clock=lambda: now, urlopen=urlopen
    )
    body = json.dumps(valid_payload(), separators=(",", ":")).encode()
    first_code, first_result = app.outbound(
        body, outbound_headers(body, now, "nonce-retryable-0001")
    )
    assert first_code == 503
    assert first_result == {"detail": "jasmin_dependency_unavailable"}
    with state.connect() as connection:
        reserved = connection.execute("SELECT * FROM sms_transactions").fetchone()
    assert reserved["state"] == "dependency_unavailable"
    assert reserved["carrier_submitted"] == 0
    second_code, second_result = app.outbound(
        body, outbound_headers(body, now, "nonce-retryable-0002")
    )
    assert second_code == 202
    assert second_result["duplicate"] is True
    assert second_result["adapter_message_id"] == reserved["adapter_message_id"]
    assert second_result["state"] == "mock_accepted"
    assert probes == []


@pytest.mark.parametrize(
    ("policy_change", "policy_error"),
    [
        ({"enabled": False}, "customer_disabled_or_unknown"),
        (
            {"suppressed_recipients": ["+4915512345678"]},
            "recipient_suppressed",
        ),
        (
            {
                "delivery_window": {
                    "timezone": "Z",
                    "start": "04:00",
                    "end": "05:00",
                }
            },
            "quiet_hours",
        ),
    ],
)
def test_terminal_sms_retry_is_read_back_before_mutable_policy_checks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    policy_change: dict[str, object],
    policy_error: str,
) -> None:
    now = 2_000_000_000
    configure_tenant(monkeypatch)
    configure_jasmin_route(monkeypatch)
    monkeypatch.setenv("TELNEXA_MIDDLEWARE_API_KEY", "test-telnexa-key")
    monkeypatch.setenv("TELNEXA_WEBHOOK_SECRET", "test-telnexa-secret")
    calls: list[str] = []

    def urlopen(url, **_kwargs):
        calls.append(url)
        return HealthyJasmin()

    app = gateway.Gateway(
        settings(
            tmp_path,
            live_submission_enabled=True,
            production_delivery_authorized=True,
            production_change_id="CHG-TERMINAL-READBACK",
        ),
        store(tmp_path),
        clock=lambda: now,
        urlopen=urlopen,
    )
    body = json.dumps(valid_payload(), separators=(",", ":")).encode()
    first_code, first = app.outbound(
        body, outbound_headers(body, now, "nonce-terminal-readback-0001")
    )
    assert first_code == 202
    assert first["state"] == "submitted"
    assert first["carrier_submitted"] is True
    policy = gateway.customer_policy()
    policy["tenant-a"].update(policy_change)
    monkeypatch.setenv("TELNEXA_CUSTOMER_POLICY_JSON", json.dumps(policy))

    retry_code, retry = app.outbound(
        body, outbound_headers(body, now, "nonce-terminal-readback-0002")
    )
    assert retry_code == 202
    assert retry == {**first, "duplicate": True}

    conflict_body = json.dumps(
        valid_payload(body="different-payload"), separators=(",", ":")
    ).encode()
    assert app.outbound(
        conflict_body,
        outbound_headers(conflict_body, now, "nonce-terminal-readback-0003"),
    ) == (409, {"detail": "idempotency_conflict"})

    new_body = json.dumps(
        valid_payload(idempotency_key="idem-new-policy-check"),
        separators=(",", ":"),
    ).encode()
    assert app.outbound(
        new_body, outbound_headers(new_body, now, "nonce-terminal-readback-0004")
    ) == (403, {"detail": policy_error})
    assert len(calls) == 2


@pytest.mark.parametrize("ambiguous_state", ["submitting", "outcome_unknown"])
def test_ambiguous_sms_retry_is_read_back_before_mutable_policy_checks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ambiguous_state: str,
) -> None:
    class SimulatedProcessExit(BaseException):
        pass

    now = 2_000_000_000
    configure_tenant(monkeypatch)
    configure_jasmin_route(monkeypatch)
    monkeypatch.setenv("TELNEXA_MIDDLEWARE_API_KEY", "test-telnexa-key")
    monkeypatch.setenv("TELNEXA_WEBHOOK_SECRET", "test-telnexa-secret")

    def urlopen(url, **_kwargs):
        if url.endswith("/ping"):
            return HealthyJasmin()
        if ambiguous_state == "submitting":
            raise SimulatedProcessExit
        return JasminReceiptTimeout()

    state = store(tmp_path)
    app = gateway.Gateway(
        settings(
            tmp_path,
            live_submission_enabled=True,
            production_delivery_authorized=True,
            production_change_id="CHG-AMBIGUOUS-READBACK",
        ),
        state,
        clock=lambda: now,
        urlopen=urlopen,
    )
    body = json.dumps(valid_payload(), separators=(",", ":")).encode()
    if ambiguous_state == "submitting":
        with pytest.raises(SimulatedProcessExit):
            app.outbound(
                body, outbound_headers(body, now, "nonce-ambiguous-readback-01")
            )
    else:
        assert app.outbound(
            body, outbound_headers(body, now, "nonce-ambiguous-readback-01")
        )[1]["state"] == "outcome_unknown"
    with state.connect() as connection:
        pending = connection.execute("SELECT * FROM sms_transactions").fetchone()
    assert pending["state"] == ambiguous_state
    policy = gateway.customer_policy()
    policy["tenant-a"]["enabled"] = False
    monkeypatch.setenv("TELNEXA_CUSTOMER_POLICY_JSON", json.dumps(policy))
    code, replay = app.outbound(
        body, outbound_headers(body, now, "nonce-ambiguous-readback-02")
    )
    assert code == 202
    assert replay == {
        "accepted": True,
        "duplicate": True,
        "adapter_message_id": pending["adapter_message_id"],
        "carrier_submitted": False,
        "state": ambiguous_state,
    }


def test_retry_rejects_changed_authorized_route_before_carrier_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = 2_000_000_000
    configure_tenant(monkeypatch)
    monkeypatch.setenv("TELNEXA_MIDDLEWARE_API_KEY", "test-telnexa-key")
    monkeypatch.setenv("TELNEXA_WEBHOOK_SECRET", "test-telnexa-secret")
    probes = 0

    def unavailable(_url, **_kwargs):
        nonlocal probes
        probes += 1
        raise TimeoutError("synthetic dependency outage")

    state = store(tmp_path)
    app = gateway.Gateway(
        settings(tmp_path), state, clock=lambda: now, urlopen=unavailable
    )
    body = json.dumps(valid_payload(), separators=(",", ":")).encode()
    first_code, first_result = app.outbound(
        body, outbound_headers(body, now, "nonce-route-change-0001")
    )
    assert (first_code, first_result) == (
        503,
        {"detail": "jasmin_dependency_unavailable"},
    )

    policy = gateway.customer_policy()
    policy["tenant-a"]["route"] = "alternate"
    monkeypatch.setenv("TELNEXA_CUSTOMER_POLICY_JSON", json.dumps(policy))
    second_code, second_result = app.outbound(
        body, outbound_headers(body, now, "nonce-route-change-0002")
    )
    assert (second_code, second_result) == (
        409,
        {"detail": "idempotency_effect_conflict"},
    )
    assert probes == 1
    with state.connect() as connection:
        reservation = connection.execute(
            "SELECT * FROM sms_transactions"
        ).fetchone()
    assert reservation["logical_route"] == "synthetic"
    assert reservation["state"] == "dependency_unavailable"
    assert reservation["operation_token"] is None


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"OK",
        b"Success",
        b"Success:provider-test-id",
        b'Success "not-a-uuid"',
        b'prefix Success "07033084-5cfd-4812-90a4-e4d24ffb6e3d"',
    ],
)
def test_jasmin_acceptance_requires_exact_success_receipt(raw: bytes):
    with pytest.raises(ValueError, match="invalid_jasmin_receipt"):
        gateway.parse_jasmin_success_receipt(raw)
    assert gateway.parse_jasmin_success_receipt(
        b'Success "07033084-5cfd-4812-90a4-e4d24ffb6e3d"\r\n'
    ) == "07033084-5cfd-4812-90a4-e4d24ffb6e3d"


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"id=07033084-5cfd-4812-90a4-e4d24ffb6e3d",
        b"id=not-a-uuid&message_status=ESME_ROK&level=1&connector=smpp-1",
        b"id=07033084-5cfd-4812-90a4-e4d24ffb6e3d&message_status=ESME_ROK&level=2&connector=smpp-1",
        b"id=07033084-5cfd-4812-90a4-e4d24ffb6e3d&message_status=OK&level=1&connector=smpp-1",
        b"id=07033084-5cfd-4812-90a4-e4d24ffb6e3d&message_status=ESME_ROK&level=1&connector=smpp-1&extra=x",
    ],
)
def test_jasmin_dlr_requires_exact_level_one_receipt(raw: bytes):
    with pytest.raises(ValueError, match="invalid_jasmin_dlr"):
        gateway.parse_jasmin_dlr(raw)
    valid = urllib.parse.urlencode(
        {
            "id": "07033084-5cfd-4812-90a4-e4d24ffb6e3d",
            "message_status": "ESME_ROK",
            "level": "1",
            "connector": "smpp-prod-1",
        }
    ).encode()
    assert gateway.parse_jasmin_dlr(valid) == (
        "07033084-5cfd-4812-90a4-e4d24ffb6e3d",
        "ESME_ROK",
        "smpp-prod-1",
    )


def test_jasmin_reconciliation_proof_binds_exact_attempt_and_effect():
    secret = "r" * 64
    base = gateway.jasmin_reconciliation_proof(
        secret,
        "07033084-5cfd-4812-90a4-e4d24ffb6e3d",
        "3f08d4cb-fc4b-4474-95c1-0d305af3a679",
        "a" * 64,
    )
    assert base != gateway.jasmin_reconciliation_proof(
        secret,
        "07033084-5cfd-4812-90a4-e4d24ffb6e3e",
        "3f08d4cb-fc4b-4474-95c1-0d305af3a679",
        "a" * 64,
    )
    assert base != gateway.jasmin_reconciliation_proof(
        secret,
        "07033084-5cfd-4812-90a4-e4d24ffb6e3d",
        "3f08d4cb-fc4b-4474-95c1-0d305af3a680",
        "a" * 64,
    )
    assert base != gateway.jasmin_reconciliation_proof(
        secret,
        "07033084-5cfd-4812-90a4-e4d24ffb6e3d",
        "3f08d4cb-fc4b-4474-95c1-0d305af3a679",
        "b" * 64,
    )


def test_unrelated_2xx_jasmin_response_is_never_recorded_as_submitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    now = 2_000_000_000
    configure_tenant(monkeypatch)
    configure_jasmin_route(monkeypatch)
    monkeypatch.setenv("TELNEXA_MIDDLEWARE_API_KEY", "test-telnexa-key")
    monkeypatch.setenv("TELNEXA_WEBHOOK_SECRET", "test-telnexa-secret")

    def urlopen(url, **_kwargs):
        return HealthyJasmin() if url.endswith("/ping") else JasminResponse(b"")

    state = store(tmp_path)
    app = gateway.Gateway(
        settings(
            tmp_path,
            live_submission_enabled=True,
            production_delivery_authorized=True,
            production_change_id="CHG-INVALID-JASMIN-RECEIPT",
        ),
        state,
        clock=lambda: now,
        urlopen=urlopen,
    )
    body = json.dumps(valid_payload(), separators=(",", ":")).encode()
    code, result = app.outbound(
        body, outbound_headers(body, now, "nonce-invalid-receipt-1")
    )
    assert code == 202
    assert result["state"] == "outcome_unknown"
    assert result["carrier_submitted"] is False
    with state.connect() as connection:
        row = connection.execute("SELECT * FROM sms_transactions").fetchone()
    assert row["provider_message_id"] is None
    assert row["operation_token"]


def test_carrier_timeout_remains_unknown_until_attempt_bound_dlr_reconciles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    now = [2_000_000_000]
    configure_tenant(monkeypatch)
    configure_jasmin_route(monkeypatch)
    monkeypatch.setenv("TELNEXA_MIDDLEWARE_API_KEY", "test-telnexa-key")
    monkeypatch.setenv("TELNEXA_WEBHOOK_SECRET", "test-telnexa-secret")
    calls = {"ping": 0, "send": 0}
    send_urls: list[str] = []

    def urlopen(url, **_kwargs):
        if url.endswith("/ping"):
            calls["ping"] += 1
            return HealthyJasmin()
        calls["send"] += 1
        send_urls.append(url)
        return JasminReceiptTimeout()

    state = store(tmp_path)
    app = gateway.Gateway(
        settings(
            tmp_path,
            live_submission_enabled=True,
            production_delivery_authorized=True,
            production_change_id="CHG-JASMIN-READBACK",
        ),
        state,
        clock=lambda: now[0],
        urlopen=urlopen,
    )
    body = json.dumps(valid_payload(), separators=(",", ":")).encode()
    code, result = app.outbound(
        body, outbound_headers(body, now[0], "nonce-timeout-receipt-1")
    )
    assert code == 202 and result["state"] == "outcome_unknown"
    code, replay = app.outbound(
        body, outbound_headers(body, now[0], "nonce-timeout-receipt-2")
    )
    assert code == 202 and replay["duplicate"] is True
    assert replay["state"] == "outcome_unknown"
    second_body = json.dumps(
        valid_payload(idempotency_key="idem-timeout-replacement"),
        separators=(",", ":"),
    ).encode()
    blocked_code, blocked = app.outbound(
        second_body,
        outbound_headers(second_body, now[0], "nonce-timeout-receipt-3"),
    )
    assert blocked_code == 409
    assert blocked["detail"] == "carrier_outcome_pending"
    assert calls == {"ping": 1, "send": 1}
    with state.connect() as connection:
        pending = connection.execute("SELECT * FROM sms_transactions").fetchone()
    assert pending["operation_token"]
    send_parameters = urllib.parse.parse_qs(urllib.parse.urlsplit(send_urls[0]).query)
    assert send_parameters["dlr"] == ["yes"]
    assert send_parameters["dlr-level"] == ["1"]
    assert send_parameters["dlr-method"] == ["POST"]
    callback = urllib.parse.urlsplit(send_parameters["dlr-url"][0])
    assert callback.path == gateway.JASMIN_DLR_PATH
    dlr = urllib.parse.urlencode(
        {
            "id": "07033084-5cfd-4812-90a4-e4d24ffb6e3d",
            "message_status": "ESME_ROK",
            "level": "1",
            "connector": "smpp-prod-1",
        }
    ).encode()
    invalid_query = urllib.parse.urlencode(
        {
            "adapter_message_id": pending["adapter_message_id"],
            "proof": "0" * 64,
        }
    )
    with pytest.raises(PermissionError, match="invalid_jasmin_dlr_proof"):
        app.reconcile_jasmin_dlr(invalid_query, dlr)
    completed = app.reconcile_jasmin_dlr(callback.query, dlr)
    with state.connect() as connection:
        first_event = connection.execute(
            "SELECT payload,payload_sha256,created_at FROM events"
        ).fetchone()
    now[0] += 300
    replay = app.reconcile_jasmin_dlr(callback.query, dlr)
    with state.connect() as connection:
        replayed_event = connection.execute(
            "SELECT payload,payload_sha256,created_at FROM events"
        ).fetchone()
    assert replay["adapter_message_id"] == completed["adapter_message_id"]
    assert tuple(replayed_event) == tuple(first_event)
    conflicting_dlr = dlr.replace(
        b"07033084-5cfd-4812-90a4-e4d24ffb6e3d",
        b"3f08d4cb-fc4b-4474-95c1-0d305af3a679",
    )
    with pytest.raises(RuntimeError, match="conflicts with terminal result"):
        app.reconcile_jasmin_dlr(callback.query, conflicting_dlr)
    assert completed["state"] == "submitted"
    assert completed["carrier_submitted"] == 1
    assert completed["provider_message_id"] == "07033084-5cfd-4812-90a4-e4d24ffb6e3d"
    assert completed["carrier_dlr_sha256"] == hashlib.sha256(dlr).hexdigest()
    assert completed["operation_token"] is None


def test_attempt_bound_rejection_dlr_supersedes_synchronous_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = 2_000_000_000
    configure_tenant(monkeypatch)
    configure_jasmin_route(monkeypatch)
    monkeypatch.setenv("TELNEXA_MIDDLEWARE_API_KEY", "test-telnexa-key")
    monkeypatch.setenv("TELNEXA_WEBHOOK_SECRET", "test-telnexa-secret")
    send_urls: list[str] = []

    def urlopen(url, **_kwargs):
        if url.endswith("/ping"):
            return HealthyJasmin()
        send_urls.append(url)
        return HealthyJasmin()

    state = store(tmp_path)
    app = gateway.Gateway(
        settings(
            tmp_path,
            mode="shared",
            live_submission_enabled=True,
            production_delivery_authorized=True,
            production_change_id="CHG-JASMIN-LATE-REJECTION",
            middleware_forwarding_enabled=True,
            downstream_url="https://10.40.0.2/v1/events",
        ),
        state,
        clock=lambda: now,
        urlopen=urlopen,
    )
    body = json.dumps(valid_payload(), separators=(",", ":")).encode()
    code, result = app.outbound(
        body, outbound_headers(body, now, "nonce-late-rejection-0001")
    )
    assert code == 202
    assert result["state"] == "submitted"
    assert result["carrier_submitted"] is True
    callback = urllib.parse.urlsplit(
        urllib.parse.parse_qs(urllib.parse.urlsplit(send_urls[0]).query)["dlr-url"][0]
    )
    dlr = urllib.parse.urlencode(
        {
            "id": "07033084-5cfd-4812-90a4-e4d24ffb6e3d",
            "message_status": "ESME_RSUBMITFAIL",
            "level": "1",
            "connector": "smpp-prod-1",
        }
    ).encode()
    completed = app.reconcile_jasmin_dlr(callback.query, dlr)
    replay = app.reconcile_jasmin_dlr(callback.query, dlr)
    assert replay["adapter_message_id"] == completed["adapter_message_id"]
    assert completed["state"] == "rejected"
    assert completed["carrier_submitted"] == 0
    assert completed["provider_message_id"] == "07033084-5cfd-4812-90a4-e4d24ffb6e3d"
    assert completed["carrier_dlr_sha256"] == hashlib.sha256(dlr).hexdigest()
    assert completed["operation_token"] is None
    with state.connect() as connection:
        events = connection.execute("SELECT * FROM events").fetchall()
    assert len(events) == 1
    event = events[0]
    assert event["system"] == "telnexa"
    assert event["path"] == gateway.TELNEXA_REJECTED_EVENT_PATH
    assert event["entity_key"] == "message-0001"
    assert event["dispatch_eligible"] == 1
    projection = json.loads(event["payload"])
    assert projection == {
        "adapter_message_id": result["adapter_message_id"],
        "correlation_id": "corr-0001",
        "customer_id": "tenant-a",
        "error_code": "ESME_RSUBMITFAIL",
        "idempotency_key": event["event_id"],
        "message_id": "message-0001",
        "occurred_at": datetime.fromtimestamp(now, timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "provider_message_id": "07033084-5cfd-4812-90a4-e4d24ffb6e3d",
        "status": "delivery_failed",
        "tenant_id": "tenant-a",
    }


def test_carrier_5xx_remains_unknown_until_attempt_bound_dlr_reconciles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = 2_000_000_000
    configure_tenant(monkeypatch)
    configure_jasmin_route(monkeypatch)
    monkeypatch.setenv("TELNEXA_MIDDLEWARE_API_KEY", "test-telnexa-key")
    monkeypatch.setenv("TELNEXA_WEBHOOK_SECRET", "test-telnexa-secret")
    send_urls: list[str] = []
    response_body = b"upstream service unavailable"

    def urlopen(url, **_kwargs):
        if url.endswith("/ping"):
            return HealthyJasmin()
        send_urls.append(url)
        raise urllib.error.HTTPError(
            url, 503, "Service Unavailable", {}, BytesIO(response_body)
        )

    state = store(tmp_path)
    app = gateway.Gateway(
        settings(
            tmp_path,
            live_submission_enabled=True,
            production_delivery_authorized=True,
            production_change_id="CHG-JASMIN-5XX-READBACK",
        ),
        state,
        clock=lambda: now,
        urlopen=urlopen,
    )
    body = json.dumps(valid_payload(), separators=(",", ":")).encode()
    code, result = app.outbound(
        body, outbound_headers(body, now, "nonce-carrier-5xx-0001")
    )
    assert code == 202 and result["state"] == "outcome_unknown"
    with state.connect() as connection:
        pending = connection.execute("SELECT * FROM sms_transactions").fetchone()
    assert pending["operation_token"]
    assert pending["provider_response_sha256"] == hashlib.sha256(response_body).hexdigest()

    replacement = json.dumps(
        valid_payload(idempotency_key="idem-timeout-replacement"),
        separators=(",", ":"),
    ).encode()
    blocked_code, blocked = app.outbound(
        replacement,
        outbound_headers(replacement, now, "nonce-carrier-5xx-0002"),
    )
    assert (blocked_code, blocked["detail"]) == (409, "carrier_outcome_pending")
    assert len(send_urls) == 1

    callback = urllib.parse.urlsplit(
        urllib.parse.parse_qs(urllib.parse.urlsplit(send_urls[0]).query)["dlr-url"][0]
    )
    dlr = urllib.parse.urlencode(
        {
            "id": "07033084-5cfd-4812-90a4-e4d24ffb6e3d",
            "message_status": "ESME_ROK",
            "level": "1",
            "connector": "smpp-prod-1",
        }
    ).encode()
    completed = app.reconcile_jasmin_dlr(callback.query, dlr)
    assert completed["state"] == "submitted"
    assert completed["carrier_submitted"] == 1
    assert completed["operation_token"] is None


@pytest.mark.parametrize(
    ("message_status", "expected_state", "carrier_submitted"),
    [
        ("ESME_ROK", "submitted", True),
        ("ESME_RSUBMITFAIL", "rejected", False),
    ],
)
def test_attempt_bound_terminal_dlr_wins_race_with_synchronous_success_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    message_status: str,
    expected_state: str,
    carrier_submitted: bool,
):
    now = 2_000_000_000
    configure_tenant(monkeypatch)
    configure_jasmin_route(monkeypatch)
    monkeypatch.setenv("TELNEXA_MIDDLEWARE_API_KEY", "test-telnexa-key")
    monkeypatch.setenv("TELNEXA_WEBHOOK_SECRET", "test-telnexa-secret")
    app_reference: dict[str, gateway.Gateway] = {}
    provider_id = "3f08d4cb-fc4b-4474-95c1-0d305af3a679"
    dlr = urllib.parse.urlencode(
        {
            "id": provider_id,
            "message_status": message_status,
            "level": "1",
            "connector": "smpp-prod-1",
        }
    ).encode()

    class ReceiptAfterCallback(HealthyJasmin):
        def __init__(self, callback_query: str):
            self.callback_query = callback_query

        def read(self, _limit=None):
            app_reference["app"].reconcile_jasmin_dlr(self.callback_query, dlr)
            return f'Success "{provider_id}"'.encode()

    def urlopen(url, **_kwargs):
        if url.endswith("/ping"):
            return HealthyJasmin()
        parameters = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        callback = urllib.parse.urlsplit(parameters["dlr-url"][0])
        return ReceiptAfterCallback(callback.query)

    state = store(tmp_path)
    app = gateway.Gateway(
        settings(
            tmp_path,
            live_submission_enabled=True,
            production_delivery_authorized=True,
            production_change_id="CHG-JASMIN-DLR-RACE",
        ),
        state,
        clock=lambda: now,
        urlopen=urlopen,
    )
    app_reference["app"] = app
    body = json.dumps(valid_payload(), separators=(",", ":")).encode()
    code, result = app.outbound(
        body, outbound_headers(body, now, "nonce-dlr-race-0001")
    )
    assert code == 202
    assert result["state"] == expected_state
    assert result["carrier_submitted"] is carrier_submitted
    with state.connect() as connection:
        completed = connection.execute("SELECT * FROM sms_transactions").fetchone()
    assert completed["provider_message_id"] == provider_id
    assert completed["carrier_dlr_sha256"] == hashlib.sha256(dlr).hexdigest()
    assert completed["provider_response_sha256"] == hashlib.sha256(
        f'Success "{provider_id}"'.encode()
    ).hexdigest()


@pytest.mark.parametrize(
    "payload",
    [
        {"tenant_id": "tenant-a", "from": "+18095550123"},
        {"tenant_id": "tenant-a", "customer_id": "customer-1"},
        {
            "tenant_id": "tenant-a",
            "customer_id": " customer-1",
            "from": "+18095550123",
        },
        {
            "tenant_id": "tenant-a",
            "customer_id": "customer-1",
            "from": "18095550123",
        },
    ],
)
def test_new_inbound_sms_requires_receiver_identities_before_acknowledgement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, str],
):
    now = 2_000_000_000
    monkeypatch.setenv("TELNEXA_MIDDLEWARE_API_KEY", "test-telnexa-key")
    monkeypatch.setenv("TELNEXA_WEBHOOK_SECRET", "test-telnexa-secret")
    state = store(tmp_path)
    app = gateway.Gateway(
        settings(
            tmp_path,
            mode="middleware",
            middleware_forwarding_enabled=True,
            downstream_url="https://middleware.invalid/v1/events",
        ),
        state,
        clock=lambda: now,
        urlopen=lambda *_args, **_kwargs: pytest.fail("invalid event dispatched"),
    )
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    event_id = "event-invalid-inbound-" + hashlib.sha256(body).hexdigest()[:16]
    code, result = app.ingress(
        "telnexa",
        "/api/v1/telnexa/inbound",
        body,
        signed_headers("telnexa", body, now, event_id),
    )
    assert (code, result) == (422, {"detail": "inbound_identity_required"})
    with state.connect() as connection:
        assert connection.execute(
            "SELECT 1 FROM events WHERE event_id=?", (event_id,)
        ).fetchone() is None


def test_new_inbound_sms_with_exact_receiver_identities_is_dispatch_eligible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    now = 2_000_000_000
    monkeypatch.setenv("TELNEXA_MIDDLEWARE_API_KEY", "test-telnexa-key")
    monkeypatch.setenv("TELNEXA_WEBHOOK_SECRET", "test-telnexa-secret")
    state = store(tmp_path)
    app = gateway.Gateway(
        settings(
            tmp_path,
            mode="middleware",
            middleware_forwarding_enabled=True,
            downstream_url="https://middleware.invalid/v1/events",
        ),
        state,
        clock=lambda: now,
    )
    payload = {
        "tenant_id": "tenant-a",
        "customer_id": "customer-1",
        "from": "+18095550123",
        "text": "HELP",
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    event_id = "event-valid-inbound-identity"
    code, result = app.ingress(
        "telnexa",
        "/api/v1/telnexa/inbound",
        body,
        signed_headers("telnexa", body, now, event_id),
    )
    assert code == 202 and result["accepted"] is True
    with state.connect() as connection:
        accepted = connection.execute(
            "SELECT dispatch_eligible,state FROM events WHERE event_id=?", (event_id,)
        ).fetchone()
    assert dict(accepted) == {"dispatch_eligible": 1, "state": "queued"}


@pytest.mark.parametrize(
    ("system", "path", "payload"),
    [
        ("telnexa", "/api/v1/telnexa/dlr", {"tenant_id": "tenant-a"}),
        ("telnexa", "/api/v1/telnexa/failure", {"tenant_id": "tenant-a"}),
        (
            "klyrow",
            "/api/v1/klyrow/events",
            {"tenant_id": "tenant-a", "event_type": "klyrow.email.delivered"},
        ),
        ("klyrow", "/api/v1/klyrow/bounces", {"tenant_id": "tenant-a"}),
        ("klyrow", "/api/v1/klyrow/complaints", {"tenant_id": "tenant-a"}),
        ("klyrow", "/api/v1/klyrow/unsubscribes", {"tenant_id": "tenant-a"}),
    ],
)
def test_forwarded_provider_status_requires_message_id_before_acknowledgement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    system: str,
    path: str,
    payload: dict[str, str],
):
    now = 2_000_000_000
    monkeypatch.setenv(f"{system.upper()}_MIDDLEWARE_API_KEY", f"test-{system}-key")
    monkeypatch.setenv(f"{system.upper()}_WEBHOOK_SECRET", f"test-{system}-secret")
    state = store(tmp_path)
    app = gateway.Gateway(
        settings(
            tmp_path,
            mode="middleware",
            middleware_forwarding_enabled=True,
            downstream_url="https://middleware.invalid/v1/events",
        ),
        state,
        clock=lambda: now,
        urlopen=lambda *_args, **_kwargs: pytest.fail("invalid event dispatched"),
    )
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    event_id = "event-missing-message-" + hashlib.sha256(body + path.encode()).hexdigest()[:16]
    code, result = app.ingress(
        system,
        path,
        body,
        signed_headers(system, body, now, event_id),
    )
    assert (code, result) == (422, {"detail": "message_id_required"})
    with state.connect() as connection:
        assert connection.execute(
            "SELECT 1 FROM events WHERE event_id=?", (event_id,)
        ).fetchone() is None


@pytest.mark.parametrize("message_id", [None, "", " ", "x" * 129, ["message-1"]])
def test_forwarding_message_identity_rejects_noncanonical_values(message_id) -> None:
    with pytest.raises(ValueError, match="message_id_required"):
        gateway.forwarding_message_identity({"message_id": message_id})


@pytest.mark.parametrize("path", ["/api/v1/telnexa/dlr", "/api/v1/telnexa/failure"])
def test_telnexa_status_with_exact_message_id_is_dispatch_eligible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path: str
):
    now = 2_000_000_000
    monkeypatch.setenv("TELNEXA_MIDDLEWARE_API_KEY", "test-telnexa-key")
    monkeypatch.setenv("TELNEXA_WEBHOOK_SECRET", "test-telnexa-secret")
    state = store(tmp_path)
    app = gateway.Gateway(
        settings(
            tmp_path,
            mode="middleware",
            middleware_forwarding_enabled=True,
            downstream_url="https://middleware.invalid/v1/events",
        ),
        state,
        clock=lambda: now,
    )
    payload = {"tenant_id": "tenant-a", "message_id": "message-status-1"}
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    event_id = "event-valid-message-" + path.rsplit("/", 1)[-1]
    code, result = app.ingress(
        "telnexa",
        path,
        body,
        signed_headers("telnexa", body, now, event_id),
    )
    assert code == 202 and result["accepted"] is True
    with state.connect() as connection:
        accepted = connection.execute(
            "SELECT entity_key,dispatch_eligible,state FROM events WHERE event_id=?",
            (event_id,),
        ).fetchone()
    assert dict(accepted) == {
        "entity_key": "message-status-1",
        "dispatch_eligible": 1,
        "state": "queued",
    }


def test_signed_provider_delivery_receipt_dispatches_as_delivered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = 2_000_000_000
    monkeypatch.setenv("TELNEXA_MIDDLEWARE_API_KEY", "test-telnexa-key")
    monkeypatch.setenv("TELNEXA_WEBHOOK_SECRET", "test-telnexa-secret")
    requests: list[urllib.request.Request] = []

    def urlopen(request, **_kwargs):
        requests.append(request)
        return dispatch_receipt(request)

    state = store(tmp_path)
    app = gateway.Gateway(
        settings(
            tmp_path,
            mode="middleware",
            middleware_forwarding_enabled=True,
            downstream_url="https://middleware.invalid/v1/events",
        ),
        state,
        clock=lambda: now,
        urlopen=urlopen,
    )
    payload = {
        "tenant_id": "tenant-a",
        "customer_id": "customer-1",
        "correlation_id": "correlation-provider-dlr",
        "message_id": "message-delivered-1",
        "provider_message_id": "carrier-message-1",
        "status": "delivery_success",
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    event_id = "event-provider-delivered-1"
    code, result = app.ingress(
        "telnexa",
        "/api/v1/telnexa/dlr",
        body,
        signed_headers("telnexa", body, now, event_id),
    )
    assert code == 202 and result["accepted"] is True
    assert app.dispatch_once() == 1
    assert len(requests) == 1
    envelope = json.loads(requests[0].data)
    assert envelope["event_type"] == "telnexa.sms.delivered"
    assert envelope["payload"]["status"] == "delivery_success"


@pytest.mark.parametrize(
    ("message_status", "expected_state", "carrier_submitted"),
    [
        ("ESME_ROK", "submitted", True),
        ("ESME_RSUBMITFAIL", "rejected", False),
    ],
)
def test_attempt_bound_dlr_wins_race_with_ambiguous_carrier_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    message_status: str,
    expected_state: str,
    carrier_submitted: bool,
):
    now = 2_000_000_000
    configure_tenant(monkeypatch)
    configure_jasmin_route(monkeypatch)
    monkeypatch.setenv("TELNEXA_MIDDLEWARE_API_KEY", "test-telnexa-key")
    monkeypatch.setenv("TELNEXA_WEBHOOK_SECRET", "test-telnexa-secret")
    app_reference: dict[str, gateway.Gateway] = {}
    provider_id = "3f08d4cb-fc4b-4474-95c1-0d305af3a679"
    dlr = urllib.parse.urlencode(
        {
            "id": provider_id,
            "message_status": message_status,
            "level": "1",
            "connector": "smpp-prod-1",
        }
    ).encode()

    class TimeoutAfterCallback(HealthyJasmin):
        def __init__(self, callback_query: str):
            self.callback_query = callback_query

        def read(self, _limit=None):
            app_reference["app"].reconcile_jasmin_dlr(self.callback_query, dlr)
            raise TimeoutError("synthetic timeout after authenticated DLR")

    def urlopen(url, **_kwargs):
        if url.endswith("/ping"):
            return HealthyJasmin()
        parameters = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        callback = urllib.parse.urlsplit(parameters["dlr-url"][0])
        return TimeoutAfterCallback(callback.query)

    state = store(tmp_path)
    app = gateway.Gateway(
        settings(
            tmp_path,
            live_submission_enabled=True,
            production_delivery_authorized=True,
            production_change_id="CHG-JASMIN-DLR-TIMEOUT-RACE",
        ),
        state,
        clock=lambda: now,
        urlopen=urlopen,
    )
    app_reference["app"] = app
    body = json.dumps(valid_payload(), separators=(",", ":")).encode()
    code, result = app.outbound(
        body, outbound_headers(body, now, "nonce-dlr-timeout-race-1")
    )
    assert code == 202
    assert result["state"] == expected_state
    assert result["carrier_submitted"] is carrier_submitted
    with state.connect() as connection:
        completed = connection.execute("SELECT * FROM sms_transactions").fetchone()
    assert completed["state"] == expected_state
    assert bool(completed["carrier_submitted"]) is carrier_submitted
    assert completed["provider_message_id"] == provider_id
    assert completed["carrier_dlr_sha256"] == hashlib.sha256(dlr).hexdigest()
    assert completed["operation_token"] is None


def test_shared_http_submission_forwards_sms_c_ack_as_submitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = 2_000_000_000
    configure_tenant(monkeypatch)
    configure_jasmin_route(monkeypatch)
    monkeypatch.setenv("TELNEXA_MIDDLEWARE_API_KEY", "test-telnexa-key")
    monkeypatch.setenv("TELNEXA_WEBHOOK_SECRET", "test-telnexa-secret")
    send_urls: list[str] = []
    middleware_requests: list[urllib.request.Request] = []

    def urlopen(target, **_kwargs):
        if isinstance(target, urllib.request.Request):
            middleware_requests.append(target)
            return dispatch_receipt(target)
        if target.endswith("/ping"):
            return HealthyJasmin()
        send_urls.append(target)
        return HealthyJasmin()

    state = store(tmp_path)
    app = gateway.Gateway(
        settings(
            tmp_path,
            mode="shared",
            live_submission_enabled=True,
            production_delivery_authorized=True,
            production_change_id="CHG-SHARED-DLR-FORWARDING",
            middleware_forwarding_enabled=True,
            downstream_url="https://middleware.invalid/v1/events",
        ),
        state,
        clock=lambda: now,
        urlopen=urlopen,
    )
    server = gateway.ThreadingHTTPServer(("127.0.0.1", 0), gateway.handler_for(app))
    server.daemon_threads = True
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        body = json.dumps(valid_payload(), separators=(",", ":")).encode()
        headers = outbound_headers(body, now, "nonce-shared-http-0001")
        headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/v1/messages",
            data=body,
            method="POST",
            headers=headers,
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            result = json.loads(response.read())
        assert result["state"] == "submitted"

        callback = urllib.parse.urlsplit(
            urllib.parse.parse_qs(urllib.parse.urlsplit(send_urls[0]).query)[
                "dlr-url"
            ][0]
        )
        dlr = urllib.parse.urlencode(
            {
                "id": "07033084-5cfd-4812-90a4-e4d24ffb6e3d",
                "message_status": "ESME_ROK",
                "level": "1",
                "connector": "smpp-prod-1",
            }
        ).encode()
        callback_request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}{callback.path}?{callback.query}",
            data=dlr,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(callback_request, timeout=5) as response:
            assert response.status == 200
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)

    with state.connect() as connection:
        event = connection.execute("SELECT * FROM events").fetchone()
    assert event["dispatch_eligible"] == 1
    assert json.loads(event["payload"])["status"] == "submitted"
    assert app.dispatch_once() == 1
    assert len(middleware_requests) == 1
    envelope = json.loads(middleware_requests[0].data)
    assert envelope["event_type"] == "telnexa.sms.submitted"
    assert envelope["payload"]["status"] == "submitted"
    assert envelope["metadata"] == {
        "private_gateway_projection_required": True,
    }


def test_crashed_submitting_row_reconciles_only_from_production_dlr_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    now = 2_000_000_000
    configure_tenant(monkeypatch)
    configure_jasmin_route(monkeypatch)
    monkeypatch.setenv("TELNEXA_MIDDLEWARE_API_KEY", "test-telnexa-key")
    monkeypatch.setenv("TELNEXA_WEBHOOK_SECRET", "test-telnexa-secret")

    send_urls: list[str] = []
    middleware_requests: list[urllib.request.Request] = []

    def urlopen(url, **_kwargs):
        if isinstance(url, urllib.request.Request):
            middleware_requests.append(url)
            return dispatch_receipt(url)
        if url.endswith("/ping"):
            return HealthyJasmin()
        send_urls.append(url)
        raise RuntimeError("synthetic process termination after durable claim")

    state = store(tmp_path)
    app = gateway.Gateway(
        settings(
            tmp_path,
            live_submission_enabled=True,
            production_delivery_authorized=True,
            production_change_id="CHG-JASMIN-CRASH-READBACK",
            middleware_forwarding_enabled=True,
            downstream_url="https://middleware.invalid/v1/events",
        ),
        state,
        clock=lambda: now,
        urlopen=urlopen,
    )
    body = json.dumps(valid_payload(), separators=(",", ":")).encode()
    with pytest.raises(RuntimeError, match="synthetic process termination"):
        app.outbound(body, outbound_headers(body, now, "nonce-submit-crash-1"))
    with state.connect() as connection:
        pending = connection.execute("SELECT * FROM sms_transactions").fetchone()
    assert pending["state"] == "submitting"
    assert pending["operation_token"]
    send_parameters = urllib.parse.parse_qs(urllib.parse.urlsplit(send_urls[0]).query)
    callback = urllib.parse.urlsplit(send_parameters["dlr-url"][0])
    dlr = urllib.parse.urlencode(
        {
            "id": "3f08d4cb-fc4b-4474-95c1-0d305af3a679",
            "message_status": "ESME_ROK",
            "level": "1",
            "connector": "smpp-prod-1",
        }
    ).encode()
    server = gateway.ThreadingHTTPServer(
        ("127.0.0.1", 0), gateway.handler_for(app)
    )
    server.daemon_threads = True
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}{callback.path}?{callback.query}",
            data=dlr,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            assert response.status == 200
            assert response.read() == b"ACK/Jasmin"
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
    with state.connect() as connection:
        completed = connection.execute("SELECT * FROM sms_transactions").fetchone()
        event = connection.execute("SELECT * FROM events").fetchone()
    assert completed["state"] == "submitted"
    assert completed["provider_message_id"] == "3f08d4cb-fc4b-4474-95c1-0d305af3a679"
    assert completed["carrier_dlr_sha256"] == hashlib.sha256(dlr).hexdigest()
    assert completed["operation_token"] is None
    assert event["path"] == gateway.TELNEXA_SUBMITTED_EVENT_PATH
    assert event["dispatch_eligible"] == 1
    assert json.loads(event["payload"])["status"] == "submitted"
    assert app.dispatch_once() == 1
    assert len(middleware_requests) == 1
    envelope = json.loads(middleware_requests[0].data)
    assert envelope["event_type"] == "telnexa.sms.submitted"
    assert envelope["payload"]["status"] == "submitted"


def test_request_body_read_timeout_and_short_read_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gateway, "REQUEST_IO_TIMEOUT_SECONDS", 0.1)
    app = gateway.Gateway(settings(tmp_path), store(tmp_path))
    server = gateway.ThreadingHTTPServer(("127.0.0.1", 0), gateway.handler_for(app))
    server.daemon_threads = True
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        started = time.monotonic()
        with socket.create_connection(("127.0.0.1", server.server_port), timeout=2) as client:
            client.settimeout(2)
            client.sendall(
                b"POST /api/v1/kyqra/jobs HTTP/1.1\r\n"
                b"Host: localhost\r\nContent-Length: 16\r\n\r\n{}"
            )
            timeout_response = client.recv(4096)
        assert time.monotonic() - started < 1.5
        assert b" 408 " in timeout_response.split(b"\r\n", 1)[0]

        with socket.create_connection(("127.0.0.1", server.server_port), timeout=2) as client:
            client.settimeout(2)
            client.sendall(
                b"POST /api/v1/kyqra/jobs HTTP/1.1\r\n"
                b"Host: localhost\r\nContent-Length: 16\r\n\r\n{}"
            )
            client.shutdown(socket.SHUT_WR)
            short_response = client.recv(4096)
        assert b" 400 " in short_response.split(b"\r\n", 1)[0]
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def test_request_body_deadline_rejects_continuous_byte_drip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gateway, "REQUEST_IO_TIMEOUT_SECONDS", 1.0)
    monkeypatch.setattr(gateway, "REQUEST_BODY_DEADLINE_SECONDS", 0.15)
    app = gateway.Gateway(settings(tmp_path), store(tmp_path))
    server = gateway.ThreadingHTTPServer(("127.0.0.1", 0), gateway.handler_for(app))
    server.daemon_threads = True
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        started = time.monotonic()
        with socket.create_connection(("127.0.0.1", server.server_port), timeout=2) as client:
            client.settimeout(2)
            client.sendall(
                b"POST /api/v1/kyqra/jobs HTTP/1.1\r\n"
                b"Host: localhost\r\nContent-Length: 16\r\n\r\n"
            )
            for _ in range(10):
                try:
                    client.sendall(b"x")
                except OSError:
                    break
                time.sleep(0.05)
            response = client.recv(4096)
        assert time.monotonic() - started < 1.0
        assert b" 408 " in response.split(b"\r\n", 1)[0]
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def test_request_header_deadline_rejects_continuous_byte_drip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gateway, "REQUEST_IO_TIMEOUT_SECONDS", 1.0)
    monkeypatch.setattr(gateway, "REQUEST_HEADER_DEADLINE_SECONDS", 0.15)
    app = gateway.Gateway(settings(tmp_path), store(tmp_path))
    server = gateway.ThreadingHTTPServer(("127.0.0.1", 0), gateway.handler_for(app))
    server.daemon_threads = True
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        started = time.monotonic()
        response = b""
        with socket.create_connection(("127.0.0.1", server.server_port), timeout=2) as client:
            client.settimeout(2)
            for byte in b"GET /health HTTP/1.1\r\nHost: localhost\r\n\r\n":
                try:
                    client.sendall(bytes((byte,)))
                except OSError:
                    break
                time.sleep(0.05)
            try:
                response = client.recv(4096)
            except (ConnectionError, OSError):
                pass
        assert time.monotonic() - started < 1.0
        assert b" 200 " not in response.split(b"\r\n", 1)[0]
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def test_crash_after_reservation_is_lease_resumable_before_carrier_submission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    now = 2_000_000_000
    configure_tenant(monkeypatch)
    monkeypatch.setenv("TELNEXA_MIDDLEWARE_API_KEY", "test-telnexa-key")
    monkeypatch.setenv("TELNEXA_WEBHOOK_SECRET", "test-telnexa-secret")
    configure_jasmin_route(monkeypatch)
    calls = {"ping": 0, "send": 0}

    def urlopen(url, **_kwargs):
        if url.endswith("/ping"):
            calls["ping"] += 1
        else:
            calls["send"] += 1
        return HealthyJasmin()

    state = store(tmp_path)
    app = gateway.Gateway(
        settings(
            tmp_path,
            live_submission_enabled=True,
            production_delivery_authorized=True,
            production_change_id="CHG-TEST-CRASH",
        ),
        state,
        clock=lambda: now,
        urlopen=urlopen,
    )
    original_claim = state.claim_sms

    def synthetic_crash(*_args, **_kwargs):
        raise RuntimeError("synthetic crash after reservation")

    monkeypatch.setattr(state, "claim_sms", synthetic_crash)
    body = json.dumps(valid_payload(), separators=(",", ":")).encode()
    with pytest.raises(RuntimeError, match="synthetic crash"):
        app.outbound(body, outbound_headers(body, now, "nonce-crash-0000001"))
    with state.connect() as connection:
        reserved = connection.execute("SELECT * FROM sms_transactions").fetchone()
    assert reserved["state"] == "reserved"
    assert calls == {"ping": 0, "send": 0}
    monkeypatch.setattr(state, "claim_sms", original_claim)
    code, result = app.outbound(
        body, outbound_headers(body, now, "nonce-crash-0000002")
    )
    assert code == 202
    assert result["duplicate"] is True
    assert result["adapter_message_id"] == reserved["adapter_message_id"]
    assert result["state"] == "submitted"
    assert calls == {"ping": 1, "send": 1}


def test_expired_preflight_lease_is_reclaimed_but_submitting_is_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    now = [2_000_000_000.0]
    configure_tenant(monkeypatch)
    monkeypatch.setenv("TELNEXA_MIDDLEWARE_API_KEY", "test-telnexa-key")
    monkeypatch.setenv("TELNEXA_WEBHOOK_SECRET", "test-telnexa-secret")
    state = store(tmp_path)
    app = gateway.Gateway(
        settings(tmp_path),
        state,
        clock=lambda: now[0],
        urlopen=lambda *_args, **_kwargs: HealthyJasmin(),
    )
    body = json.dumps(valid_payload(), separators=(",", ":")).encode()
    original_complete = state.complete_sms

    def crash_during_preflight(*_args, **_kwargs):
        raise RuntimeError("synthetic preflight crash")

    monkeypatch.setattr(state, "complete_sms", crash_during_preflight)
    with pytest.raises(RuntimeError, match="synthetic preflight crash"):
        app.outbound(body, outbound_headers(body, int(now[0]), "nonce-lease-00000001"))
    with state.connect() as connection:
        preflight = connection.execute("SELECT * FROM sms_transactions").fetchone()
    assert preflight["state"] == "preflight"
    now[0] += 31
    monkeypatch.setattr(state, "complete_sms", original_complete)
    code, result = app.outbound(
        body, outbound_headers(body, int(now[0]), "nonce-lease-00000002")
    )
    assert code == 202 and result["state"] == "mock_accepted"
    with state.connect() as connection:
        connection.execute(
            """UPDATE sms_transactions
            SET state='submitting',operation_token='ambiguous',
                reconciliation_proof_sha256=?
            WHERE adapter_message_id=?""",
            ("a" * 64, preflight["adapter_message_id"]),
        )
    code, result = app.outbound(
        body, outbound_headers(body, int(now[0]), "nonce-lease-00000003")
    )
    assert code == 202
    assert result["duplicate"] is True
    assert result["state"] == "submitting"


def test_live_idempotency_is_reserved_before_concurrent_carrier_submission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    now = 2_000_000_000
    configure_tenant(monkeypatch)
    monkeypatch.setenv("TELNEXA_MIDDLEWARE_API_KEY", "test-telnexa-key")
    monkeypatch.setenv("TELNEXA_WEBHOOK_SECRET", "test-telnexa-secret")
    configure_jasmin_route(monkeypatch)
    carrier_started = threading.Event()
    release_carrier = threading.Event()
    calls = {"ping": 0, "send": 0}
    call_lock = threading.Lock()

    def urlopen(url, **_kwargs):
        with call_lock:
            if isinstance(url, str) and url.endswith("/ping"):
                calls["ping"] += 1
                return HealthyJasmin()
            calls["send"] += 1
        carrier_started.set()
        assert release_carrier.wait(timeout=5)
        return HealthyJasmin()

    state = store(tmp_path)
    app = gateway.Gateway(
        settings(
            tmp_path,
            live_submission_enabled=True,
            production_delivery_authorized=True,
            production_change_id="CHG-TEST-1",
        ),
        state,
        clock=lambda: now,
        urlopen=urlopen,
    )
    body = json.dumps(valid_payload(), separators=(",", ":")).encode()
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            app.outbound,
            body,
            outbound_headers(body, now, "nonce-concurrent-0001"),
        )
        assert carrier_started.wait(timeout=5)
        second = executor.submit(
            app.outbound,
            body,
            outbound_headers(body, now, "nonce-concurrent-0002"),
        )
        second_code, second_result = second.result(timeout=5)
        release_carrier.set()
        first_code, first_result = first.result(timeout=5)
    assert first_code == second_code == 202
    assert first_result["duplicate"] is False
    assert second_result["duplicate"] is True
    assert first_result["adapter_message_id"] == second_result["adapter_message_id"]
    assert calls == {"ping": 1, "send": 1}
    with state.connect() as connection:
        count = connection.execute("SELECT COUNT(*) FROM sms_transactions").fetchone()[0]
    assert count == 1


def test_compose_is_digest_only_nonroot_and_fail_closed():
    compose = yaml.safe_load((SERVICE / "compose.production.yaml").read_text())
    service = compose["services"]["gateway"]
    assert "build" not in service
    assert "PRIVATE_INTEGRATION_GATEWAY_IMAGE" in service["image"]
    assert service["user"] == "10001:10001"
    assert service["read_only"] is True
    assert service["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in service["security_opt"]
    assert service["ports"] == ["127.0.0.1:18443:8080"]
    assert service["environment"]["JASMIN_DLR_CALLBACK_URL"] == (
        "http://gateway:8080/internal/v1/jasmin/dlr"
    )
    assert service["environment"]["LIVE_SUBMISSION_ENABLED"] == "false"
    assert service["environment"]["PRODUCTION_DELIVERY_AUTHORIZED"] == "false"
    assert service["environment"]["MIDDLEWARE_FORWARDING_ENABLED"] == "false"
    assert compose["networks"]["private_api"]["internal"] is True
    assert "/etc/kyqra-telnexa-integration/shared.env" in service["env_file"][0]


def test_container_base_and_runtime_are_immutable_and_isolated():
    dockerfile = (SERVICE / "Dockerfile").read_text()
    first = dockerfile.splitlines()[0]
    assert first.startswith("FROM python:3.12.14-alpine3.24@sha256:")
    assert 'USER 10001:10001' in dockerfile
    assert 'ENTRYPOINT ["python", "-I", "-u", "/app/gateway.py"]' in dockerfile
    assert "org.opencontainers.image.revision" in dockerfile


def test_source_never_logs_message_bodies_or_secret_values():
    source = (SERVICE / "gateway.py").read_text()
    assert "LOG.info(payload" not in source
    assert "LOG.info(body" not in source
    assert "provider_response=%s" not in source
    assert "password=%s" not in source
    assert "api_key=%s" not in source


def test_release_signing_is_isolated_from_repository_code():
    workflow = (ROOT / ".github/workflows/private-integration-gateway.yml").read_text()
    build = workflow.split("  build_candidate:", 1)[1].split("  sign_and_promote:", 1)[0]
    signer = workflow.split("  sign_and_promote:", 1)[1]
    assert "actions/checkout@" in build
    assert "id-token: write" not in build
    assert "actions/checkout@" not in signer
    assert "actions/setup-python@" not in signer
    assert "services/private-integration-gateway/gateway.py" not in signer
    assert "id-token: write" in signer
    assert "Download protected build evidence without repository checkout" in signer


def test_release_scans_and_verifies_the_exact_digest_before_source_tag():
    workflow = (ROOT / ".github/workflows/private-integration-gateway.yml").read_text()
    assert "image-ref: ${{ env.PRIVATE_GATEWAY_IMAGE }}@${{ steps.push.outputs.digest }}" in workflow
    assert "severity: CRITICAL,HIGH" in workflow
    assert 'high_critical_findings:0' in workflow
    signer = workflow.split("  sign_and_promote:", 1)[1]
    verification = signer.index("Verify exact signature, provenance, and SBOM before publication")
    promotion = signer.index("Promote only the fully certified digest to the source tag")
    assert verification < promotion
    assert "--certificate-identity \"$SIGNING_IDENTITY\"" in signer
    assert "--certificate-oidc-issuer \"$OIDC_ISSUER\"" in signer
    assert signer.count("jq -s -e") == 4
    assert "--prefer-index=false" in signer


def test_release_cannot_deploy_or_send_communications():
    workflow = (ROOT / ".github/workflows/private-integration-gateway.yml").read_text().lower()
    for prohibited in (
        "ssh ",
        "scp ",
        "docker compose up",
        "docker compose restart",
        "systemctl restart",
        "send email",
        "send sms",
        "canary",
    ):
        assert prohibited not in workflow
