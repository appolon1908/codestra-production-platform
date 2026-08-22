from pathlib import Path


def test_first_campaign_channel_migration_is_exact_and_fail_closed():
    sql=(Path(__file__).parents[1]/"migrations/control_plane/004_campaign_scoped_channel_gate.sql").read_text()
    assert "'COD-WEB-OUT',6,id,'EMAIL','CANARY_READY','CANARY',true,false" in sql
    assert "REFERENCES control_plane.campaign(id)" in sql
    assert "FROM control_plane.campaign" in sql
    assert "public.campaign_registry" not in sql
    assert "PRIMARY KEY(tenant_id,campaign_code,channel)" in sql
    assert "customer_traffic_allowed" in sql
    assert "COD-TEST-OUT" not in sql
    assert "'SMS','CANARY_READY'" not in sql
    assert "'VOICE','CANARY_READY'" not in sql
