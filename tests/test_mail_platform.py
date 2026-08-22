import sqlite3

import pytest

from mail_platform import MailRegistry, PolicyError


@pytest.fixture
def registry():
    value = MailRegistry()
    value.migrate()
    value.register_domain(domain="a.example", brand="A", domain_type="AGENT_CAMPAIGN", business_unit_id="A",
                          campaign_id="CAMPAIGN_A", active=True, allow_agent_send=True, allow_agent_receive=True,
                          allow_standalone_users=True, allow_shared_mailboxes=True, admin_override_allowed=True)
    value.register_domain(domain="b.example", brand="B", domain_type="AGENT_CAMPAIGN", business_unit_id="B",
                          campaign_id="CAMPAIGN_B", active=True, allow_agent_send=True, allow_agent_receive=True,
                          allow_standalone_users=True, allow_shared_mailboxes=True, admin_override_allowed=True)
    return value


def user(registry, address, campaign, subject, *, kind="STANDALONE", role="STANDALONE_MAIL_USER", odoo=None):
    return registry.create_user(keycloak_subject=subject, display_name=subject, primary_address=address,
                                user_type=kind, role=role, quota=1_000_000, odoo_user_id=odoo,
                                campaign_id=campaign, business_unit_id=campaign[-1] if campaign else None)


def test_domain_can_belong_to_only_one_campaign(registry):
    with pytest.raises(PolicyError, match="domain_campaign_conflict"):
        registry.register_domain(domain="a.example", brand="A", domain_type="AGENT_CAMPAIGN",
                                 campaign_id="CAMPAIGN_B", active=True)


def test_standalone_user_has_nullable_odoo_link_and_can_link_later(registry):
    standalone = user(registry, "alice@a.example", "CAMPAIGN_A", "kc-alice")
    assert standalone["odoo_user_id"] is None
    same_uuid = standalone["mail_user_uuid"]
    registry.link_odoo(same_uuid, 42, "kc-admin")
    linked = registry.db.execute("SELECT * FROM mail_user WHERE mail_user_uuid=?", (same_uuid,)).fetchone()
    assert linked["mail_user_uuid"] == same_uuid and linked["odoo_user_id"] == 42
    assert linked["user_type"] == "ODOO_LINKED"


def test_agent_sender_domain_security_matrix(registry):
    agent_a = user(registry, "agent@a.example", "CAMPAIGN_A", "kc-agent-a", kind="ODOO_LINKED", role="AGENT", odoo=1)
    agent_b = user(registry, "agent@b.example", "CAMPAIGN_B", "kc-agent-b", kind="ODOO_LINKED", role="AGENT", odoo=2)
    assert registry.authorize_sender(agent_a["mail_user_uuid"], "agent@a.example")["allowed"]
    with pytest.raises(PolicyError, match="sender_domain_denied"):
        registry.authorize_sender(agent_a["mail_user_uuid"], "agent@b.example")
    with pytest.raises(PolicyError, match="sender_domain_denied"):
        registry.authorize_sender(agent_b["mail_user_uuid"], "agent@a.example")


def test_admin_override_is_explicit_and_audited(registry):
    admin = user(registry, "owner@a.example", None, "kc-owner", kind="ADMIN", role="EMAIL_OWNER")
    with pytest.raises(PolicyError, match="admin_override_reason_required"):
        registry.authorize_sender(admin["mail_user_uuid"], "owner@b.example")
    assert registry.authorize_sender(admin["mail_user_uuid"], "owner@b.example", reason="tenant support case 123")["override"]
    row = registry.db.execute("SELECT * FROM mail_audit WHERE action='mail.domain.override'").fetchone()
    assert row["reason"] == "tenant support case 123" and row["outcome"] == "ALLOW"


def test_standalone_alias_is_domain_scoped(registry):
    alice = user(registry, "alice@a.example", "CAMPAIGN_A", "kc-alice")
    registry.add_alias(alice["mail_user_uuid"], "a.smith@a.example", alice["mail_user_uuid"])
    assert registry.authorize_sender(alice["mail_user_uuid"], "a.smith@a.example")["allowed"]
    with pytest.raises(PolicyError, match="alias_domain_denied"):
        registry.add_alias(alice["mail_user_uuid"], "alice@b.example", alice["mail_user_uuid"])


def test_inbound_campaign_comes_from_recipient_domain(registry):
    route = registry.route_inbound("support@a.example")
    assert route["campaign_id"] == "CAMPAIGN_A"
    assert "sender" not in route


def test_suspension_preserves_user_and_denies_send(registry):
    alice = user(registry, "alice@a.example", "CAMPAIGN_A", "kc-alice")
    registry.suspend(alice["mail_user_uuid"], "kc-admin", "offboarding")
    with pytest.raises(PolicyError, match="mail_user_suspended"):
        registry.authorize_sender(alice["mail_user_uuid"], "alice@a.example")
    assert registry.db.execute("SELECT count(*) FROM mail_user WHERE mail_user_uuid=?", (alice["mail_user_uuid"],)).fetchone()[0] == 1


def test_reconciliation_detects_no_drift(registry):
    user(registry, "alice@a.example", "CAMPAIGN_A", "kc-alice")
    assert registry.reconcile()["status"] == "PASS"


def test_database_enforces_unique_identities(registry):
    user(registry, "alice@a.example", "CAMPAIGN_A", "kc-alice")
    with pytest.raises(sqlite3.IntegrityError):
        user(registry, "other@a.example", "CAMPAIGN_A", "kc-alice")
