from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import os
import sys
import threading
import urllib.error
import urllib.parse
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import yaml


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
        "MIDDLEWARE_FORWARDING_ENABLED",
        "MIDDLEWARE_EVENTS_URL",
        "JASMIN_HTTP_URL",
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
        "jasmin_url": "http://jasmin:1401",
    }
    values.update(changes)
    value = gateway.Settings(**values)
    value.validate()
    return value


def store(tmp_path: Path):
    value = gateway.Store(tmp_path / "integration.db")
    value.initialize()
    return value


def test_delivery_defaults_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("INTEGRATION_DB", str(tmp_path / "default.db"))
    value = gateway.Settings.from_environment()
    assert value.live_submission_enabled is False
    assert value.production_delivery_authorized is False


def test_live_delivery_requires_second_gate_and_change_id(tmp_path: Path):
    with pytest.raises(ValueError, match="production authorization"):
        settings(tmp_path, live_submission_enabled=True)
    with pytest.raises(ValueError, match="production authorization"):
        settings(
            tmp_path,
            live_submission_enabled=True,
            production_delivery_authorized=True,
        )


def test_middleware_forwarding_is_explicit_and_mode_bounded(tmp_path: Path):
    with pytest.raises(ValueError, match="middleware mode"):
        settings(tmp_path, middleware_forwarding_enabled=True)
    with pytest.raises(ValueError, match="MIDDLEWARE_EVENTS_URL"):
        settings(
            tmp_path,
            mode="middleware",
            middleware_forwarding_enabled=True,
        )
    value = settings(
        tmp_path,
        mode="middleware",
        middleware_forwarding_enabled=True,
        downstream_url="https://middleware.invalid/v1/events",
    )
    assert value.middleware_forwarding_enabled is True


def test_only_private_jasmin_service_is_accepted(tmp_path: Path):
    with pytest.raises(ValueError, match="private"):
        settings(tmp_path, jasmin_url="https://example.invalid")
    with pytest.raises(ValueError, match="private"):
        settings(tmp_path, jasmin_url="http://127.0.0.1:1401")


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
                    "senders": ["TEST"],
                    "destination_prefixes": ["+49155"],
                    "route": "synthetic",
                    "approved_recipients": ["+4915512345678"],
                    "consented_recipients": ["+4915512345678"],
                    "suppressed_recipients": [],
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


def valid_payload(**changes):
    value = {
        "customer_id": "tenant-a",
        "sender": "TEST",
        "to": "+4915512345678",
        "body": "synthetic",
        "idempotency_key": "idem-0001",
        "correlation_id": "corr-0001",
    }
    value.update(changes)
    return value


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"sender": "bad sender!"}, ValueError),
        ({"sender": "OTHER"}, PermissionError),
        ({"to": "0155abc"}, ValueError),
        ({"to": "+18095550101"}, PermissionError),
        ({"customer_id": "tenant-disabled"}, PermissionError),
        ({"customer_id": "tenant-b"}, PermissionError),
        ({"correlation_id": "x" * 129}, ValueError),
    ],
)
def test_outbound_policy_rejects_invalid_or_cross_tenant_input(
    monkeypatch: pytest.MonkeyPatch, changes, error
):
    configure_tenant(monkeypatch)
    with pytest.raises(error):
        gateway.validate_outbound(valid_payload(**changes))


def test_outbound_policy_accepts_exact_sender_destination_and_route(
    monkeypatch: pytest.MonkeyPatch,
):
    configure_tenant(monkeypatch)
    assert gateway.validate_outbound(valid_payload()) == (
        "tenant-a",
        "TEST",
        "+4915512345678",
        "synthetic",
        "corr-0001",
    )


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
        gateway.validate_outbound(valid_payload())


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
                    "senders": ["TEST"],
                    "destination_prefixes": ["+49155"],
                    "route": "synthetic",
                    "approved_recipients": ["+4915512345678"],
                    "consented_recipients": ["+4915512345678"],
                    "suppressed_recipients": [],
                },
                "tenant-b": {
                    "enabled": True,
                    "senders": ["TEST"],
                    "destination_prefixes": ["+49155"],
                    "route": "alternate",
                    "approved_recipients": ["+4915512345678"],
                    "consented_recipients": ["+4915512345678"],
                    "suppressed_recipients": [],
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
    assert event["payload"] == '{"old":true}'
    assert event["payload_sha256"] == hashlib.sha256(b'{"old":true}').hexdigest()
    assert event["dispatch_eligible"] == 0
    assert value.pending_events(2_000_000_000) == []
    assert "provider_response_sha256" in sms_columns
    assert "operation_token" in sms_columns
    assert "lease_expires_at" in sms_columns
    assert "effect_hash" in sms_columns


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
    body = json.dumps(
        {
            "event_id": headers["x-event-id"],
            "correlation_id": "receipt-correlation",
            "duplicate": duplicate,
            "state": "queued",
        },
        separators=(",", ":"),
    ).encode()
    return HttpResponse(status, body)


def test_new_ingress_events_are_dispatched_with_control_plane_authentication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    now = 2_000_000_000
    monkeypatch.setenv("KLYROW_MIDDLEWARE_API_KEY", "test-klyrow-key")
    monkeypatch.setenv("KLYROW_WEBHOOK_SECRET", "test-klyrow-secret")
    requests = []

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
        "last_error": "RuntimeError",
    }

    with pytest.raises(RuntimeError, match="invalid_downstream_receipt"):
        gateway.verify_dispatch_receipt(
            202,
            b'{"event_id":"event-untrusted-2xx","correlation_id":"receipt",'
            b'"duplicate":false,"state":[]}',
            "event-untrusted-2xx",
            0,
            None,
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
        )
    with pytest.raises(RuntimeError, match="downstream_receipt_rejected"):
        gateway.verify_dispatch_receipt(
            409,
            b'{"error":"replayed_event_id"}',
            "event-lost-receipt",
            1,
            "RuntimeError",
        )
    now = [2_000_000_000.0]
    monkeypatch.setenv("KLYROW_MIDDLEWARE_API_KEY", "downstream-key")
    monkeypatch.setenv("KLYROW_WEBHOOK_SECRET", "downstream-secret")
    state = store(tmp_path)
    payload = json.dumps({"tenant_id": "tenant-a"}, separators=(",", ":"))
    assert state.insert_event(
        "event-lost-receipt",
        "klyrow",
        "/api/v1/klyrow/events",
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
            BytesIO(b'{"error":"replayed_event_id"}'),
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
    payload = json.dumps({"tenant_id": "tenant-a"}, separators=(",", ":"))
    assert state.insert_event(
        "event-lost-body",
        "telnexa",
        "/api/v1/telnexa/dlr",
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
                BytesIO(b'{"error":"replayed_event_id"}'),
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
    monkeypatch.setenv("KLYROW_MIDDLEWARE_API_KEY", "downstream-key")
    monkeypatch.setenv("KLYROW_WEBHOOK_SECRET", "downstream-secret")
    state = store(tmp_path)
    payload = json.dumps({"tenant_id": "tenant-a"}, separators=(",", ":"))
    assert state.insert_event(
        "event-process-exit",
        "klyrow",
        "/api/v1/klyrow/events",
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
            BytesIO(b'{"error":"replayed_event_id"}'),
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

    def unavailable(*_args, **_kwargs):
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
        "state": "dead_letter",
        "attempts": 5,
        "last_error": "DispatchOutcomeUnknown",
    }
    assert app.dispatch_once() == 0


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


def test_carrier_timeout_remains_unknown_until_exact_readback_reconciles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    now = 2_000_000_000
    configure_tenant(monkeypatch)
    configure_jasmin_route(monkeypatch)
    monkeypatch.setenv("TELNEXA_MIDDLEWARE_API_KEY", "test-telnexa-key")
    monkeypatch.setenv("TELNEXA_WEBHOOK_SECRET", "test-telnexa-secret")
    calls = {"ping": 0, "send": 0}

    def urlopen(url, **_kwargs):
        if url.endswith("/ping"):
            calls["ping"] += 1
            return HealthyJasmin()
        calls["send"] += 1
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
        clock=lambda: now,
        urlopen=urlopen,
    )
    body = json.dumps(valid_payload(), separators=(",", ":")).encode()
    code, result = app.outbound(
        body, outbound_headers(body, now, "nonce-timeout-receipt-1")
    )
    assert code == 202 and result["state"] == "outcome_unknown"
    code, replay = app.outbound(
        body, outbound_headers(body, now, "nonce-timeout-receipt-2")
    )
    assert code == 202 and replay["duplicate"] is True
    assert replay["state"] == "outcome_unknown"
    second_body = json.dumps(
        valid_payload(idempotency_key="idem-timeout-replacement"),
        separators=(",", ":"),
    ).encode()
    blocked_code, blocked = app.outbound(
        second_body,
        outbound_headers(second_body, now, "nonce-timeout-receipt-3"),
    )
    assert blocked_code == 409
    assert blocked["detail"] == "carrier_outcome_pending"
    assert calls == {"ping": 1, "send": 1}
    with state.connect() as connection:
        pending = connection.execute("SELECT * FROM sms_transactions").fetchone()
    assert pending["operation_token"]
    with pytest.raises(ValueError, match="invalid_jasmin_receipt"):
        state.reconcile_sms_outcome(
            pending["adapter_message_id"], pending["operation_token"], b"OK"
        )
    readback = b'Success "07033084-5cfd-4812-90a4-e4d24ffb6e3d"'
    completed = state.reconcile_sms_outcome(
        pending["adapter_message_id"], pending["operation_token"], readback
    )
    assert completed["state"] == "submitted"
    assert completed["carrier_submitted"] == 1
    assert completed["provider_message_id"] == "07033084-5cfd-4812-90a4-e4d24ffb6e3d"
    assert completed["provider_response_sha256"] == hashlib.sha256(readback).hexdigest()
    assert completed["operation_token"] is None


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
            """UPDATE sms_transactions SET state='submitting',operation_token='ambiguous'
            WHERE adapter_message_id=?""",
            (preflight["adapter_message_id"],),
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
