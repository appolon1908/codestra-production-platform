import importlib.util
from pathlib import Path


PATH = Path("scripts/codestra_campaign_reconcile.py")
SPEC = importlib.util.spec_from_file_location("campaign_reconcile", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def row(code="COD-SERVICE-OUT", actual="COD12345", group="COD_AGENTS", ingroup=""):
    return {"CODE": code, "EXPECTED_VICIDIAL_CAMPAIGN": actual,
            "EXPECTED_USER_GROUP": group, "EXPECTED_INGROUP": ingroup}


def test_adapter_command_is_disabled_and_has_no_customer_list():
    campaign = MODULE.adapter_command(row())["campaign"]
    assert campaign["active"] is False
    assert campaign["dial_method"] == "MANUAL"
    assert campaign["callback_enabled"] is False
    assert campaign["lists"] == []
    assert campaign["groups"][0]["active"] is False


def test_test_syn_uses_short_campaign_scoped_statuses():
    command = MODULE.adapter_command(row("TEST_SYN", "TEST_SYN", "WEBTEST_SYN", "TEST_IN"))
    assert command["campaign"]["business_unit"] == "TEST"
    assert {item["code"] for item in command["campaign"]["dispositions"]} == {"ANS", "APPT", "WN"}


def test_apply_uses_restricted_adapter():
    class Client:
        def __init__(self): self.calls = []
        def reconcile_campaign(self, key, command):
            self.calls.append((key, command))
            return {"status": "complete_disabled"}
    client = Client()
    state = {"campaigns": {}, "groups": {}, "ingroups": {}}
    assert MODULE.apply_via_adapter(
        [row()], state, client, plan_sha256="a" * 64,
        authorization_reference="CHG-20260821-CAMPAIGN-RECONCILIATION",
        backup_reference="backup/20260822T120000Z",
    ) == [{"status": "complete_disabled"}]
    assert client.calls[0][0] == "campaign-reconcile:COD12345"
    assert client.calls[0][1]["plan_sha256"] == "a" * 64


def test_plan_blocks_unowned_collision_active_ingroup_and_repairs_membership():
    state = {
        "campaigns": {"COD12345": {"id": "COD12345", "name": "Other", "active": "N",
            "dial_method": "MANUAL", "call_time": "9am-5pm", "auto": "0", "hopper": "0",
            "recording": "ONDEMAND", "callbacks": "N", "description": "unowned"}},
        "groups": {"COD_AGENTS": {"id": "COD_AGENTS", "name": "Codestra COD_AGENTS", "allowed": " -"}},
        "ingroups": {"COD12345I": {"id": "COD12345I", "name": "COD-SERVICE-IN", "active": "Y"}},
        "statuses": {},
    }
    plan = MODULE.build_plan([row("COD-SERVICE-IN", ingroup="COD12345I")], state)
    assert {item["reason"] for item in plan["blockers"]} == {"existing inbound group is active"}
    assert plan["campaign_legacy_adoptions"] == [{
        "resource": "COD12345", "reason": "explicit fingerprint-gated migration"}]
    assert plan["group_updates"][0]["campaigns"] == ["COD12345"]


def test_read_mysql_rejects_mutations():
    try:
        MODULE.read_mysql("UPDATE a SET b=1")
    except RuntimeError as error:
        assert "read-only" in str(error)
    else:
        raise AssertionError("mutation was not rejected")
