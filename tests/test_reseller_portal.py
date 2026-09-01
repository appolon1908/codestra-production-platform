import pytest
from reseller_portal.core import MemoryStore, PortalError, PortalService, hash_secret, validate_callback_url


def public_resolver(*args, **kwargs): return [(2,1,6,"",("93.184.216.34",443))]
def private_resolver(*args, **kwargs): return [(2,1,6,"",("10.0.0.8",443))]


def test_synthetic_reseller_onboarding_and_isolation():
    store=MemoryStore(); svc=PortalService(store)
    parent=svc.organization("Synthetic Reseller"); owner=svc.user(parent["id"],"oidc-parent","owner@synthetic.invalid")
    session=svc.login("oidc-parent"); assert hash_secret(session) in store.sessions
    child=svc.organization("Synthetic Subaccount",parent=parent["id"]); child_user=svc.user(child["id"],"oidc-child","child@synthetic.invalid")
    issued=svc.credential(child["id"],child_user["id"],"production"); assert issued["secret"].startswith("csk_")
    assert "secret" not in store.credentials[issued["id"]]
    sender=svc.sender(child["id"],child_user["id"],"SYNTHETIC","alphanumeric",["DO"],["sms"]); assert sender["approval"]=="review_required"
    domain=svc.domain(child["id"],child_user["id"],"synthetic.invalid"); assert domain["dkim"]=="pending"
    hook=svc.webhook(child["id"],child_user["id"],"https://hooks.example.test/events",public_resolver); assert hook["signing_secret"]
    sms=svc.synthetic_message(child["id"],child_user["id"],"sms","sms-1"); email=svc.synthetic_message(child["id"],child_user["id"],"email","email-1")
    assert sms["dlr"]=="delivered" and email["status"]=="synthetic_delivered"
    dash=svc.dashboard(child["id"]); assert len(dash["messages"])==2 and len(dash["ledger"])==2
    assert svc.dashboard(parent["id"])["messages"]==[]
    replacement=svc.rotate(child["id"],child_user["id"],issued["id"]); assert store.credentials[issued["id"]]["status"]=="revoked"
    svc.revoke(child["id"],child_user["id"],replacement["id"]); assert store.credentials[replacement["id"]]["status"]=="revoked"
    svc.suspend(child["id"],child_user["id"])
    with pytest.raises(PortalError): svc.synthetic_message(child["id"],child_user["id"],"sms","blocked")
    assert {x["action"] for x in svc.dashboard(child["id"])["audit"]} >= {"credential.create","credential.rotate","credential.revoke","sender.request","domain.register","webhook.create","sms.synthetic","email.synthetic","account.suspend"}


@pytest.mark.parametrize("url",["http://example.com/x","https://127.0.0.1/x","https://user:pass@example.com/x","https://example.com:8443/x"])
def test_webhook_ssrf_policy(url):
    with pytest.raises(PortalError): validate_callback_url(url,private_resolver)


def test_cross_tenant_credential_denied():
    svc=PortalService(MemoryStore()); a=svc.organization("A"); b=svc.organization("B"); u=svc.user(a["id"],"a","a@x")
    key=svc.credential(a["id"],u["id"],"key")
    with pytest.raises(PortalError): svc.revoke(b["id"],"b",key["id"])


def test_login_tenant_is_server_derived_from_unique_subject():
    svc=PortalService(MemoryStore()); a=svc.organization("A"); b=svc.organization("B")
    user=svc.user(a["id"],"subject-a","a@example.test")
    session=svc.login("subject-a")
    assert svc.s.sessions[hash_secret(session)] == {"user":user["id"],"tenant":a["id"]}
    with pytest.raises(PortalError): svc.login("unknown-subject")
    with pytest.raises(PortalError): svc.user(b["id"],"subject-a","other@example.test")
