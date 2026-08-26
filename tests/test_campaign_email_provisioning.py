import sqlite3
import uuid

import pytest

from control_plane_service.core import ControlPlaneError
from control_plane_service.email_provisioning import (
    ADDRESS_CONFLICT,
    BLOCKED_DOMAIN,
    CampaignMailboxRegistry,
    normalize_first_name,
)


class Identity:
    def __init__(self): self.created = []; self.revoked = []
    def reconcile(self, command):
        self.created.append(command)
        return {"user_id": "kc-agent-1"}
    def revoke_mailbox_grants(self, command):
        self.revoked.append(command)


class Mail:
    def __init__(self, send=True, receive=True):
        self.send, self.receive = send, receive
        self.identities = []; self.routes = []; self.senders = []; self.disabled = []
    def provision_identity(self, command): self.identities.append(command); return {"id":"mail-1"}
    def provision_inbound_route(self, command): self.routes.append(command); return {"id":"route-1"}
    def authorize_sender(self, command): self.senders.append(command); return {"id":"sender-1"}
    def validate_send_path(self, command):
        assert command["external_delivery"] is False
        return self.send
    def validate_inbound_route(self, command): return self.receive
    def destination_readback(self, command): return self.send and self.receive
    def disable(self, command): self.disabled.append(command["primary_email"])


class Odoo:
    def __init__(self): self.writes = []
    def write_mailbox(self, command): self.writes.append(command)


@pytest.fixture
def registry(tmp_path):
    return CampaignMailboxRegistry(str(tmp_path / "mailbox.sqlite3"))


def campaign_id(): return str(uuid.uuid4())
def agent_id(): return str(uuid.uuid4())


def approve(registry, campaign, **overrides):
    value = {"tenant_id":"COD","campaign_id":campaign,"campaign_name":"Codestra Sales",
             "primary_domain":"codestra.co","alias_domains":["codestra.agency"],
             "sender_domain_verified":True,"inbound_domain_verified":True,
             "sending_enabled":True,"receiving_enabled":True,"approved_by":"platform-admin"}
    value.update(overrides)
    return registry.approve_domain(value)


def request(campaign, agent=None, key="agent-created-1", first="María José"):
    return {"tenant_id":"COD","agent_id":agent or agent_id(),"employee_id":"5",
            "odoo_user_id":"63","keycloak_user_id":str(uuid.UUID(int=1)),
            "vicidial_user_id":"cod00016","campaign_id":campaign,
            "first_name":first,"last_name":"Santos","display_name":f"{first} Santos",
            "supervisor_id":"supervisor-1","active":True,"idempotency_key":key,
            "correlation_id":str(uuid.uuid4())}


@pytest.mark.parametrize(("source","expected"), [
    ("José","jose"),("María José","mariajose"),("Jean-Pierre","jean-pierre"),("D’Angelo","dangelo")
])
def test_first_name_normalization(source, expected):
    assert normalize_first_name(source) == expected


@pytest.mark.parametrize("source", ["", "A", "'", "--"])
def test_invalid_short_local_part(source):
    with pytest.raises(ControlPlaneError, match="invalid_first_name_local_part"):
        normalize_first_name(source)


def test_missing_mapping_blocks_without_downstream_calls(registry):
    result, duplicate = registry.provision(request(campaign_id()), Identity(), Mail(), Odoo())
    assert not duplicate and result["mailbox_status"] == BLOCKED_DOMAIN


def test_unverified_domain_blocks(registry):
    campaign = campaign_id(); approve(registry,campaign,inbound_domain_verified=False)
    result, _ = registry.provision(request(campaign), Identity(), Mail(), Odoo())
    assert result["mailbox_status"] == BLOCKED_DOMAIN


def test_agent_provisions_firstname_domain_only_after_both_validations(registry):
    campaign = campaign_id(); approve(registry,campaign)
    identity, mail, odoo = Identity(), Mail(), Odoo()
    result, duplicate = registry.provision(request(campaign),identity,mail,odoo)
    assert not duplicate
    assert result["primary_email"] == "mariajose@codestra.co"
    assert result["mailbox_status"] == "ACTIVE"
    assert result["sending_enabled"] == 1 and result["receiving_enabled"] == 1
    assert identity.created[0]["roles"] == ["codestra-email-agent"]
    assert all(scope.endswith(".own") for scope in identity.created[0]["scopes"])
    assert len(mail.identities) == len(mail.routes) == len(mail.senders) == 1
    assert [write["mailbox_status"] for write in odoo.writes] == ["PROVISIONING", "ACTIVE"]


def test_exact_replay_returns_existing_mailbox_without_duplicate_effects(registry):
    campaign = campaign_id(); approve(registry,campaign)
    identity, mail, odoo, value = Identity(), Mail(), Odoo(), request(campaign)
    first, _ = registry.provision(value,identity,mail,odoo)
    second, duplicate = registry.provision(value,identity,mail,odoo)
    assert duplicate and second["mailbox_id"] == first["mailbox_id"]
    assert len(identity.created) == len(mail.routes) == 1


def test_same_key_changed_payload_is_rejected(registry):
    campaign = campaign_id(); approve(registry,campaign)
    value = request(campaign); registry.provision(value,Identity(),Mail(),Odoo())
    value["first_name"] = "Carlos"
    with pytest.raises(ControlPlaneError, match="idempotency_conflict"):
        registry.provision(value,Identity(),Mail(),Odoo())


def test_duplicate_first_name_conflicts_without_shared_access(registry):
    campaign = campaign_id(); approve(registry,campaign)
    registry.provision(request(campaign,agent_id(),"first"),Identity(),Mail(),Odoo())
    second_mail = Mail()
    result, _ = registry.provision(request(campaign,agent_id(),"second"),Identity(),second_mail,Odoo())
    assert result["mailbox_status"] == ADDRESS_CONFLICT
    assert not second_mail.identities and not second_mail.routes
    with sqlite3.connect(registry.path) as db:
        assert db.execute("select count(*) from cp_agent_mailbox").fetchone()[0] == 1


def test_validation_failure_disables_mailbox_and_revokes_grants(registry):
    campaign = campaign_id(); approve(registry,campaign)
    identity, mail = Identity(), Mail(send=False)
    result, _ = registry.provision(request(campaign),identity,mail,Odoo())
    assert result["mailbox_status"] == "PROVISIONING_FAILED"
    assert result["sending_enabled"] == 0 and result["receiving_enabled"] == 0
    assert mail.disabled == ["mariajose@codestra.co"] and identity.revoked


def test_suspension_passes_stored_keycloak_subject(registry):
    campaign = campaign_id(); approve(registry, campaign)
    identity, mail = Identity(), Mail()
    created, _ = registry.provision(request(campaign), identity, mail, Odoo())
    registry.suspend("COD", created["mailbox_id"], identity, mail)
    assert identity.revoked[-1]["keycloak_user_id"] == "kc-agent-1"


def test_compensation_failures_never_leave_registry_provisioning(registry):
    campaign = campaign_id(); approve(registry,campaign)

    class BrokenIdentity(Identity):
        def revoke_mailbox_grants(self, command):
            raise RuntimeError("provider detail must be redacted")

    class BrokenMail(Mail):
        def disable(self, command):
            raise RuntimeError("provider detail must be redacted")

    result, _ = registry.provision(request(campaign), BrokenIdentity(), BrokenMail(send=False), Odoo())
    assert result["mailbox_status"] == "PROVISIONING_FAILED"
    assert "mail_disable_failed" in result["provisioning_error"]
    assert "identity_revoke_failed" in result["provisioning_error"]
    assert "provider detail" not in result["provisioning_error"]


def test_suspension_revokes_access_but_preserves_record(registry):
    campaign = campaign_id(); approve(registry,campaign)
    identity, mail = Identity(), Mail()
    active, _ = registry.provision(request(campaign),identity,mail,Odoo())
    suspended = registry.suspend("COD",active["mailbox_id"],identity,mail)
    assert suspended["mailbox_status"] == "SUSPENDED"
    assert suspended["sending_enabled"] == 0 and suspended["receiving_enabled"] == 0


def test_campaign_and_tenant_are_part_of_address_ownership(registry):
    first, second = campaign_id(), campaign_id()
    approve(registry,first)
    approve(registry,second,primary_domain="codestra.agency")
    one, _ = registry.provision(request(first,agent_id(),"one",first="Evelin"),Identity(),Mail(),Odoo())
    two, _ = registry.provision(request(second,agent_id(),"two",first="Evelin"),Identity(),Mail(),Odoo())
    assert one["primary_email"] == "evelin@codestra.co"
    assert two["primary_email"] == "evelin@codestra.agency"


def test_sender_and_inbound_route_are_exactly_isolated(registry):
    campaign, agent = campaign_id(), agent_id(); approve(registry,campaign)
    mailbox, _ = registry.provision(request(campaign,agent,first="Carlos"),Identity(),Mail(),Odoo())
    assert registry.authorize_from("COD",agent,campaign,"carlos@codestra.co")["mailbox_id"] == mailbox["mailbox_id"]
    assert registry.route_inbound("Carlos@Codestra.Co")["agent_id"] == agent
    for tenant, owner, assigned_campaign, sender in [
        ("OTHER",agent,campaign,"carlos@codestra.co"),
        ("COD",agent_id(),campaign,"carlos@codestra.co"),
        ("COD",agent,campaign_id(),"carlos@codestra.co"),
        ("COD",agent,campaign,"evelin@codestra.co"),
    ]:
        with pytest.raises(ControlPlaneError, match="mailbox_sender_not_authorized"):
            registry.authorize_from(tenant,owner,assigned_campaign,sender)
    with pytest.raises(ControlPlaneError, match="inbound_recipient_not_found"):
        registry.route_inbound("unknown@codestra.co")
