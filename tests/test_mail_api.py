from fastapi.testclient import TestClient

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
    response = TestClient(api.app).get("/api/v1/mail/mailboxes", headers={"X-Tenant": "tenant-1"})
    assert response.status_code == 401


def test_api_enforces_scope_sender_policy_and_idempotency(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "DATABASE", str(tmp_path / "registry.db"))
    seeded_database(api.DATABASE)
    denied = api.Principal(subject="subject-1", email="agent@mail.test", tenant="tenant-1",
        scopes={"mail.read"}, roles={"codestra_mail_agent", "codestra_mail_user"})
    api.app.dependency_overrides[api.principal] = lambda: denied
    client = TestClient(api.app)
    payload = {"sender": "agent@mail.test", "recipients": ["internal@mail.test"],
               "correlation_id": "correlation-1", "idempotency_key": "idempotency-1"}
    assert client.post("/api/v1/mail/messages", json=payload).status_code == 403
    allowed = denied.model_copy(update={"scopes": {"mail.read", "mail.send"}})
    api.app.dependency_overrides[api.principal] = lambda: allowed
    first = client.post("/api/v1/mail/messages", json=payload)
    second = client.post("/api/v1/mail/messages", json=payload)
    assert first.status_code == 202 and second.status_code == 202
    assert first.json()["message_uuid"] == second.json()["message_uuid"]
    assert second.json()["duplicate"] is True
    check = MailRegistry(api.DATABASE)
    assert check.db.execute("SELECT count(*) FROM mail_outbox").fetchone()[0] == 1
    api.app.dependency_overrides.clear()
