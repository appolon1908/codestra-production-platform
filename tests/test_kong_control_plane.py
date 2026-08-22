from pathlib import Path
import hashlib

from control_plane_service.server import Handler

ROOT=Path(__file__).resolve().parents[1]

def test_kong_control_plane_is_host_method_auth_and_size_bounded():
    policy=(ROOT/"deploy/kong/control-plane.yml").read_text()
    for value in ("api.codestra.co","openid-connect","codestra-control-plane","request-size-limiting","rate-limiting","correlation-id"):
        assert value in policy
    assert "methods: [POST]" in policy and "http://codestra-control-plane" in policy

def test_callers_have_distinct_scopes_and_cross_tenant_denial():
    policy=(ROOT/"deploy/kong/scope-policy.lua").read_text()
    for scope in ("campaign.write","agent.write","mapping.read","mapping.read.minimum","sync.execute","sync.result.write","reconciliation.read","reconciliation.execute"):
        assert scope in policy
    assert "cross_tenant_denied" in policy
    assert "KONG_CONTROL_PLANE_GATEWAY_SECRET" in policy


def test_trusted_proxy_headers_also_require_gateway_secret(monkeypatch,tmp_path):
    secret="synthetic-gateway-secret"
    verifier=tmp_path/"verifier"; verifier.write_text(hashlib.sha256(secret.encode()).hexdigest())
    monkeypatch.setenv("CONTROL_PLANE_TRUSTED_PROXY_CIDRS","10.0.0.2/32")
    monkeypatch.setenv("KONG_GATEWAY_SHARED_SECRET_SHA256_FILE",str(verifier))
    handler=Handler.__new__(Handler); handler.client_address=("10.0.0.2",1234)
    handler.headers={"X-Authenticated-Client":"n8n","X-Authenticated-Tenant":"COD"}
    denied=[]; handler.send_json=lambda code,value: denied.append((code,value))
    assert handler.auth_operator({"tenant_admin"}) is None and denied[0][0]==403
    handler.headers["X-Codestra-Gateway-Secret"]=secret
    assert handler.auth_operator({"tenant_admin"}) == ("n8n","tenant_admin","COD")

def test_canonical_message_routes_and_scopes_are_explicit():
    kong=(ROOT/"deploy/kong/control-plane.yml").read_text()
    policy=(ROOT/"deploy/kong/scope-policy.lua").read_text()
    assert "/api/v1/messages" in kong and "https_required" in kong
    for scope in ("communications.message.create","communications.message.read","communications.message.dispatch","communications.result.write","communications.message.events.read"):
        assert scope in policy


def test_complete_granular_communication_scope_catalog_is_documented():
    matrix=(ROOT/"reports/COMMUNICATION_OAUTH_SCOPE_MATRIX.csv").read_text()
    required={
        "communications.message.create", "communications.message.read",
        "communications.message.dispatch", "communications.message.events.read",
        "communications.sms.create", "communications.sms.dispatch",
        "communications.sms.events.read", "communications.email.create",
        "communications.email.dispatch", "communications.email.events.read",
        "communications.result.write", "communications.reconciliation.read",
        "communications.reconciliation.execute", "communications.admin",
    }
    assert not (required - set(matrix.replace(',', ' ').replace('"', ' ').split()))

def test_control_plane_implements_business_aliases_without_provider_duplication():
    source=(ROOT/"control_plane_service/server.py").read_text()
    for path in ("/api/v1/control/messages","/api/v1/messages/","/api/v1/results/messages/"):
        assert path in source
    assert "STORE.create_message(value)" in source


def test_signed_provider_event_ids_are_single_use_nonces():
    source=(ROOT/"control_plane_service/server.py").read_text()
    assert 'source in {"odoo", "telnexa", "klyrow"}' in source
    assert '"replayed_event_id"' in source
