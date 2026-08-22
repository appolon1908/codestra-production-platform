import importlib.util
from pathlib import Path


PATH = Path("scripts/codestra_campaign_reconcile.py")
SPEC = importlib.util.spec_from_file_location("campaign_reconcile", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_apply_sql_is_always_disabled_and_non_dialing():
    sql = MODULE.sql_for({
        "campaign_creates": [{"physical_id": "COD12345", "canonical_code": "COD-X-OUT"}],
        "campaign_safety_updates": [{"physical_id": "CODSAFE1", "hopper_before": "1"}],
        "group_creates": [{"id": "COD_AGENTS", "campaigns": ["COD12345"]}],
        "ingroup_creates": [{"id": "COD1234I", "name": "COD-X-IN"}],
        "ingroup_safety_updates": [{"id": "TEST_IN"}],
    })
    assert "'N','MANUAL'" in sql
    assert "hopper_level,auto_dial_level" in sql
    assert ",0,'0')" in sql
    assert "vicidial_lists" not in sql
    assert "active,group_color" in sql
    assert "hopper_level=0 WHERE campaign_id='CODSAFE1'" in sql
    assert "active='N' WHERE group_id='TEST_IN'" in sql


def test_sql_quotes_external_identifiers():
    assert MODULE.quote("a'b") == "'a''b'"
