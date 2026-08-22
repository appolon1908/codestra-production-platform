import json
from types import SimpleNamespace

import pytest

from control_plane_service.core import ControlPlaneError
from control_plane_service.email_adapters import (
    CANONICAL_ISSUER,
    KLYROW_PRIVATE_ENDPOINT,
    ODOO_PRIVATE_ENDPOINT,
    KeycloakIdentityAdapter,
    KlyrowMailboxAdapter,
    OdooMailboxAdapter,
    ServiceTokenProvider,
)


class RecordingClient:
    def __init__(self):
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if url.endswith("/validations/outbound"):
            return {"authorized": True, "external_delivery": False}
        if url.endswith("/validations/inbound"):
            return {"matched": True, "match": "EXACT"}
        return {}


class Tokens:
    def __init__(self):
        self.tenants = []

    def token(self, tenant_id):
        self.tenants.append(tenant_id)
        return "redacted-test-token"


def command():
    return {
        "tenant_id": "COD",
        "campaign_id": "COD-SUPPORT-IN",
        "agent_id": "agent-1",
        "mailbox_id": "mailbox-1",
        "keycloak_user_id": "kc-subject-1",
        "primary_email": "alice@codestra.co",
        "correlation_id": "correlation-1",
        "idempotency_key": "idempotency-1",  # gitleaks:allow - non-secret test fixture
    }


def test_noncanonical_keycloak_issuer_is_rejected(tmp_path):
    with pytest.raises(ControlPlaneError, match="noncanonical_keycloak_issuer"):
        ServiceTokenProvider(
            SimpleNamespace(), issuer="https://auth.codestra.agency/realms/codestra",
            client_id="mailbox-provisioner", client_secret_file=str(tmp_path / "secret"),
            audience="klyrow-private-api", scopes=("mailbox.provision",),
        )


def test_service_token_cache_is_tenant_bound(tmp_path, monkeypatch):
    secret = tmp_path / "secret"
    secret.write_text("fixture-value", encoding="utf-8")
    secret.chmod(0o600)
    responses = iter(("token-cod", "token-mbl"))

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, _limit):
            return json.dumps({"access_token": next(responses), "expires_in": 120}).encode()

    class Opener:
        def open(self, _request, timeout):
            assert timeout == 10
            return Response()

    client = SimpleNamespace(opener=Opener(), timeout=10)
    provider = ServiceTokenProvider(
        client, issuer=CANONICAL_ISSUER, client_id="mailbox-provisioner",
        client_secret_file=str(secret), audience="klyrow-private-api",
        scopes=("mailbox.provision",),
    )
    monkeypatch.setattr("control_plane_service.email_adapters.time.time", lambda: 1000)
    assert provider.token("COD") == "token-cod"
    assert provider.token("COD") == "token-cod"
    assert provider.token("MBL") == "token-mbl"


def test_klyrow_endpoint_is_pinned_to_private_service():
    with pytest.raises(ControlPlaneError, match="unapproved_klyrow_endpoint"):
        KlyrowMailboxAdapter(RecordingClient(), Tokens(), "https://mail.example.test")


def test_klyrow_exact_route_is_tenant_bound_and_never_catch_all():
    client, tokens = RecordingClient(), Tokens()
    adapter = KlyrowMailboxAdapter(client, tokens, KLYROW_PRIVATE_ENDPOINT)
    adapter.provision_inbound_route(command())
    method, url, kwargs = client.calls[-1]
    assert method == "PUT"
    assert url.endswith("/v1/email/inbound-routes/alice%40codestra.co")
    assert kwargs["body"]["match"] == "EXACT"
    assert kwargs["body"]["catch_all"] is False
    assert kwargs["headers"]["X-Klyrow-Tenant-ID"] == "COD"
    assert tokens.tenants == ["COD"]


def test_validation_requires_nonexternal_send_and_exact_inbound():
    adapter = KlyrowMailboxAdapter(RecordingClient(), Tokens())
    assert adapter.validate_send_path(command()) is True
    assert adapter.validate_inbound_route(command()) is True


def test_keycloak_requires_authoritative_existing_subject():
    adapter = KeycloakIdentityAdapter(RecordingClient(), Tokens())
    value = command(); value["keycloak_user_id"] = ""
    with pytest.raises(ControlPlaneError, match="authoritative_keycloak_subject_required"):
        adapter.reconcile(value)


def test_odoo_endpoint_is_pinned_and_projection_is_allowlisted():
    with pytest.raises(ControlPlaneError, match="unapproved_odoo_endpoint"):
        OdooMailboxAdapter(RecordingClient(), Tokens(), "https://odoo.example.test")

    class OdooClient(RecordingClient):
        def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            body = kwargs["body"]
            return {key: body[key] for key in ("tenant_id", "primary_email", "mailbox_id", "mailbox_status")}

    client = OdooClient(); adapter = OdooMailboxAdapter(client, Tokens(), ODOO_PRIVATE_ENDPOINT)
    value = {**command(), "mailbox_status": "ACTIVE", "sending_enabled": True,
             "receiving_enabled": True, "roles": ["must-not-project"], "scopes": ["must-not-project"]}
    adapter.write_mailbox(value)
    projected = client.calls[-1][2]["body"]
    assert "roles" not in projected and "scopes" not in projected and "keycloak_user_id" not in projected
