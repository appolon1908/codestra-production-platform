import pytest
from fastapi import HTTPException
from starlette.requests import Request

from mail_platform import MailRegistry
from mail_platform import api


def seeded_database(path):
    reg = MailRegistry(path); reg.migrate()
    reg.register_domain(domain="mail.test", brand="TEST_SYN", domain_type="AGENT_CAMPAIGN",
        business_unit_id="TEST", campaign_id="TEST_SYN", active=True, allow_agent_send=True,
        allow_agent_receive=True, allow_standalone_users=True, allow_shared_mailboxes=True)
    return reg.create_user(keycloak_subject="subject-1", display_name="Agent", primary_address="agent@mail.test",
        user_type="ODOO_LINKED", role="AGENT", quota=1024, odoo_user_id=1,
        campaign_id="TEST_SYN", business_unit_id="TEST")


def test_api_denies_missing_authentication(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "DATABASE", str(tmp_path / "registry.db"))
    seeded_database(api.DATABASE)
    request = Request({"type": "http", "headers": []})
    with pytest.raises(HTTPException) as exc:
        api.principal(request, "tenant-1")
    assert exc.value.status_code == 401


def test_api_enforces_scope_sender_policy_and_idempotency(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "DATABASE", str(tmp_path / "registry.db"))
    seeded_database(api.DATABASE)
    denied = api.Principal(subject="subject-1", email="agent@mail.test", tenant="tenant-1",
        scopes={"mail.read"}, roles={"codestra_mail_agent", "codestra_mail_user"})
    with pytest.raises(HTTPException) as exc:
        api.require_scope("mail.send")(denied)
    assert exc.value.status_code == 403
    payload = api.MessageCommand(sender="agent@mail.test", recipients=["internal@mail.test"],
        correlation_id="correlation-1", idempotency_key="idempotency-1")  # gitleaks:allow -- synthetic test value
    allowed = denied.model_copy(update={"scopes": {"mail.read", "mail.send"}})
    first = api.create_message(payload, allowed)
    second = api.create_message(payload, allowed)
    assert first["message_uuid"] == second["message_uuid"]
    assert second["duplicate"] is True
    check = MailRegistry(api.DATABASE)
    assert check.db.execute("SELECT count(*) FROM mail_outbox").fetchone()[0] == 1
