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


def test_app_password_is_random_hashed_revocable_and_not_recoverable(registry):
    alice = user(registry, "alice@a.example", "CAMPAIGN_A", "kc-alice")
    credential, secret = registry.create_app_password(alice["mail_user_uuid"], "Thunderbird", "kc-alice")
    row = registry.db.execute("SELECT * FROM mail_app_password WHERE credential_uuid=?", (credential,)).fetchone()
    assert secret not in tuple(str(value) for value in row)
    assert registry.verify_app_password(alice["mail_user_uuid"], secret)
    registry.revoke_app_password(credential, "kc-alice")
    assert not registry.verify_app_password(alice["mail_user_uuid"], secret)


def test_shared_inbox_rejects_cross_campaign_member(registry):
    supervisor = user(registry, "supervisor@a.example", "CAMPAIGN_A", "kc-super", kind="ODOO_LINKED", role="SUPERVISOR", odoo=10)
    member = user(registry, "member@a.example", "CAMPAIGN_A", "kc-member", kind="ODOO_LINKED", role="AGENT", odoo=11)
    outsider = user(registry, "outsider@b.example", "CAMPAIGN_B", "kc-outsider", kind="ODOO_LINKED", role="AGENT", odoo=12)
    mailbox = registry.create_shared_mailbox(actor_uuid=supervisor["mail_user_uuid"], address="support@a.example",
        campaign_id="CAMPAIGN_A", supervisor_uuid=supervisor["mail_user_uuid"], members=[(member["mail_user_uuid"], "SEND")])
    assert mailbox
    with pytest.raises(PolicyError, match="shared_mailbox_member_denied"):
        registry.create_shared_mailbox(actor_uuid=supervisor["mail_user_uuid"], address="billing@a.example",
            campaign_id="CAMPAIGN_A", supervisor_uuid=supervisor["mail_user_uuid"], members=[(outsider["mail_user_uuid"], "READ")])


def test_threading_and_idempotency_preserve_one_thread(registry):
    agent = user(registry, "agent@a.example", "CAMPAIGN_A", "kc-agent", kind="ODOO_LINKED", role="AGENT", odoo=1)
    first = registry.register_message(tenant="COD", direction="OUTBOUND", sender="agent@a.example",
        recipients=["internal@a.example"], correlation_id="corr-1", idempotency_key="idem-1",
        message_id="<message-1@test>", actor_uuid=agent["mail_user_uuid"])
    reply = registry.register_message(tenant="COD", direction="INBOUND", sender="internal@a.example",
        recipients=["agent@a.example"], correlation_id="corr-2", idempotency_key="idem-2",
        message_id="<message-2@test>", in_reply_to="<message-1@test>", references=["<message-1@test>"])
    duplicate = registry.register_message(tenant="COD", direction="OUTBOUND", sender="agent@a.example",
        recipients=["internal@a.example"], correlation_id="changed", idempotency_key="idem-1",
        actor_uuid=agent["mail_user_uuid"])
    assert first["thread_uuid"] == reply["thread_uuid"]
    assert duplicate["message_uuid"] == first["message_uuid"] and duplicate["duplicate"]
    assert registry.db.execute("SELECT count(DISTINCT thread_uuid) FROM mail_message").fetchone()[0] == 1
    assert registry.db.execute("SELECT count(*) FROM mail_message").fetchone()[0] == 2
