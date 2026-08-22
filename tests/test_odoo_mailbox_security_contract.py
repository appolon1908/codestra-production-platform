import csv
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).parents[1] / "odoo_addons/codestra_control_plane"


def _records():
    tree = ET.parse(ROOT / "security/mailbox_security.xml")
    return {node.attrib["id"]: node for node in tree.findall(".//record")}


def _field(record, name):
    return next(node for node in record.findall("field") if node.attrib["name"] == name)


def test_generic_call_center_groups_have_no_mailbox_acl():
    with (ROOT / "security/ir.model.access.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    mailbox_rows = [row for row in rows if row["model_id:id"] in {
        "model_codestra_agent_mailbox",
        "model_codestra_agent_mail_message",
        "model_codestra_campaign_email_domain",
    }]
    assert mailbox_rows
    assert all(row["group_id:id"].startswith("codestra_control_plane.group_codestra_email_") for row in mailbox_rows)
    assert all(row["perm_write"] == row["perm_create"] == row["perm_unlink"] == "0" for row in mailbox_rows)


def test_agent_cannot_enumerate_other_or_suspended_mailboxes():
    rule = _records()["rule_agent_mailbox_own"]
    domain = (_field(rule, "domain_force").text or "")
    assert "('user_id', '=', user.id)" in domain
    assert "('user_id.active', '=', True)" in domain
    assert "SUSPENDED" in domain and "DEACTIVATED" in domain
    assert "('company_id', 'in', company_ids)" in domain


def test_supervisor_and_campaign_manager_are_campaign_scoped():
    records = _records()
    for rule_id in ("rule_supervisor_mailbox_campaign", "rule_supervisor_message_campaign", "rule_supervisor_domain_campaign"):
        domain = (_field(records[rule_id], "domain_force").text or "")
        assert "user.codestra_email_campaign_ids.ids" in domain
        assert "('company_id', 'in', company_ids)" in domain


def test_messages_follow_active_mailbox_owner_and_company():
    rule = _records()["rule_agent_message_own"]
    domain = (_field(rule, "domain_force").text or "")
    assert "('mailbox_id.user_id', '=', user.id)" in domain
    assert "('mailbox_id.user_id.active', '=', True)" in domain
    assert "mailbox_id.mailbox_status" in domain


def test_tenant_and_platform_administration_are_separate_groups():
    records = _records()
    tenant = _field(records["rule_tenant_admin_mailbox"], "domain_force").text or ""
    platform = _field(records["rule_platform_admin_mailbox"], "domain_force").text or ""
    assert "company_ids" in tenant
    assert platform.strip() == "[(1, '=', 1)]"
    platform_group = _field(records["group_codestra_email_platform_admin"], "name").text
    assert platform_group == "Callback Email Platform Administrator"


def test_models_require_tenant_company_and_consistency_constraints():
    source = (ROOT / "models/mailbox.py").read_text()
    assert source.count('tenant_id = fields.Char(required=True') >= 3
    assert source.count('"res.company", required=True') >= 3
    assert "Mailbox tenant must match its owning company" in source
    assert "Campaign email tenant must match its owning company" in source
    assert "Message ownership must match its mailbox" in source
