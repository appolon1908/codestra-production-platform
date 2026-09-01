from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import os
import sys
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
        "MIDDLEWARE_EVENTS_URL",
        "JASMIN_HTTP_URL",
        "TELNEXA_CUSTOMER_POLICY_JSON",
        "TELNEXA_CUSTOMER_POLICY_JSON_FILE",
        "TELNEXA_MIDDLEWARE_API_KEY",
        "TELNEXA_MIDDLEWARE_API_KEY_FILE",
        "TELNEXA_WEBHOOK_SECRET",
        "TELNEXA_WEBHOOK_SECRET_FILE",
        "KYQRA_MIDDLEWARE_API_KEY",
        "KYQRA_WEBHOOK_SECRET",
        "KLYROW_MIDDLEWARE_API_KEY",
        "KLYROW_WEBHOOK_SECRET",
        "JASMIN_API_USER",
        "JASMIN_API_PASSWORD",
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
            "SELECT payload,payload_sha256 FROM events WHERE event_id='old-event'"
        ).fetchone()
        sms_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(sms_transactions)")
        }
    assert event["payload"] == '{"old":true}'
    assert event["payload_sha256"] == hashlib.sha256(b'{"old":true}').hexdigest()
    assert "provider_response_sha256" in sms_columns


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


class HealthyJasmin:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, _limit=None):
        return b"Success:provider-test-id"


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
