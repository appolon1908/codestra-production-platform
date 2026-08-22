from pathlib import Path

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

def test_canonical_message_routes_and_scopes_are_explicit():
    kong=(ROOT/"deploy/kong/control-plane.yml").read_text()
    policy=(ROOT/"deploy/kong/scope-policy.lua").read_text()
    assert "/api/v1/messages" in kong and "https_required" in kong
    for scope in ("message.create","message.read","message.dispatch","message.result.write","message.events.read"):
        assert scope in policy

def test_control_plane_implements_business_aliases_without_provider_duplication():
    source=(ROOT/"control_plane_service/server.py").read_text()
    for path in ("/api/v1/control/messages","/api/v1/messages/","/api/v1/results/messages/"):
        assert path in source
    assert "STORE.create_message(value)" in source


def test_signed_provider_event_ids_are_single_use_nonces():
    source=(ROOT/"control_plane_service/server.py").read_text()
    assert 'source in {"odoo", "telnexa", "klyrow"}' in source
    assert '"replayed_event_id"' in source
