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
    assert "ON CONFLICT(tenant_id,campaign_code,channel) DO NOTHING" in sql
    assert "DO UPDATE SET" not in sql
    assert "required COD-WEB-OUT EMAIL channel gate was not created" in sql


def test_registry_parent_key_uses_the_authoritative_campaign_id_type():
    sql=(Path(__file__).parents[1]/"migrations/control_plane/004_campaign_scoped_channel_gate.sql").read_text()
    assert "format_type(a.atttypid,a.atttypmod)" in sql
    assert "a.attrelid='control_plane.campaign'::regclass" in sql
    assert "parent_campaign_id %s NOT NULL REFERENCES control_plane.campaign(id)" in sql
    assert "parent_campaign_id uuid" not in sql
