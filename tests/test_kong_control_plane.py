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
