from __future__ import annotations

import hashlib, ipaddress, secrets, socket, uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlparse

ROLES = {"owner", "admin", "billing", "developer", "support", "viewer"}
PROTECTED_SENDERS = {"alphanumeric", "short_code", "toll_free"}


class PortalError(ValueError): pass


def now(): return datetime.now(timezone.utc).isoformat()


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def validate_callback_url(url: str, resolver=socket.getaddrinfo) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise PortalError("callback_must_be_public_https")
    if parsed.port not in (None, 443): raise PortalError("callback_port_not_allowed")
    try: addresses = {row[4][0] for row in resolver(parsed.hostname, 443, type=socket.SOCK_STREAM)}
    except OSError as exc: raise PortalError("callback_dns_failed") from exc
    if not addresses: raise PortalError("callback_dns_failed")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global: raise PortalError("callback_private_address_denied")
    return url


@dataclass
class MemoryStore:
    organizations: dict = field(default_factory=dict); users: dict = field(default_factory=dict)
    credentials: dict = field(default_factory=dict); senders: dict = field(default_factory=dict)
    domains: dict = field(default_factory=dict); webhooks: dict = field(default_factory=dict)
    messages: dict = field(default_factory=dict); ledger: list = field(default_factory=list)
    audits: list = field(default_factory=list); sessions: dict = field(default_factory=dict)
    invoices: dict = field(default_factory=dict); kyc: dict = field(default_factory=dict)
    anomaly_flags: dict = field(default_factory=dict); idempotency: dict = field(default_factory=dict)


class PortalService:
    def __init__(self, store: MemoryStore): self.s = store
    def audit(self, tenant, actor, action, resource, outcome="success", detail=None):
        self.s.audits.append({"id":str(uuid.uuid4()),"tenant_id":tenant,"actor":actor,"action":action,"resource":resource,"outcome":outcome,"detail":detail or {},"at":now()})
    def organization(self, name, *, parent=None, services=("sms","email","crm","reporting")):
        oid=str(uuid.uuid4()); self.s.organizations[oid]={"id":oid,"name":name,"parent_id":parent,"status":"active","services":list(services),"credit_policy":"prepaid","balance_minor":0,"rate_limits":{"requests_per_minute":60},"compliance_state":"pending","countries":[],"usage_cap_minor":100000,"kill_switch":False}; return self.s.organizations[oid]
    def subaccount(self, tenant, actor, name, services=("sms","email")):
        child=self.organization(name,parent=tenant,services=services); self.audit(tenant,actor,"subaccount.create",child["id"]); return child
    def user(self, tenant, subject, email, role="owner"):
        if role not in ROLES: raise PortalError("invalid_role")
        if any(u["subject"] == subject for u in self.s.users.values()):
            raise PortalError("subject_already_mapped")
        uid=str(uuid.uuid4()); self.s.users[uid]={"id":uid,"tenant_id":tenant,"subject":subject,"email":email,"role":role,"status":"active"}; return self.s.users[uid]
    def login(self, subject):
        """Resolve tenant exclusively from the authoritative subject mapping."""
        matches=[u for u in self.s.users.values() if u["subject"]==subject]
        if len(matches) != 1: raise PortalError("login_denied")
        user=matches[0]
        tenant=user["tenant_id"]
        org=self.s.organizations.get(tenant)
        if not user or user["status"]!="active" or not org or org["status"]!="active": raise PortalError("login_denied")
        token=secrets.token_urlsafe(32); self.s.sessions[hash_secret(token)]={"user":user["id"],"tenant":tenant}; self.audit(tenant,user["id"],"login","session"); return token
    def credential(self, tenant, actor, name):
        raw="csk_"+secrets.token_urlsafe(32); cid=str(uuid.uuid4()); prefix=raw[:12]
        self.s.credentials[cid]={"id":cid,"tenant_id":tenant,"name":name,"prefix":prefix,"secret_hash":hash_secret(raw),"status":"active","created_at":now(),"last_used_at":None}; self.audit(tenant,actor,"credential.create",cid); return {"id":cid,"prefix":prefix,"secret":raw}
    def rotate(self, tenant, actor, cid):
        row=self._tenant(self.s.credentials,cid,tenant); row["status"]="revoked"; value=self.credential(tenant,actor,row["name"]+" (rotated)"); self.audit(tenant,actor,"credential.rotate",cid,detail={"replacement":value["id"]}); return value
    def revoke(self, tenant, actor, cid):
        self._tenant(self.s.credentials,cid,tenant)["status"]="revoked"; self.audit(tenant,actor,"credential.revoke",cid)
    def sender(self, tenant, actor, value, sender_type, countries, services):
        sid=str(uuid.uuid4()); protected=sender_type in PROTECTED_SENDERS
        self.s.senders[sid]={"id":sid,"tenant_id":tenant,"value":value,"type":sender_type,"countries":countries,"services":services,"approval":"review_required" if protected else "pending","state":"inactive"}; self.audit(tenant,actor,"sender.request",sid); return self.s.senders[sid]
    def domain(self, tenant, actor, domain):
        did=str(uuid.uuid4()); self.s.domains[did]={"id":did,"tenant_id":tenant,"domain":domain.lower(),"dns_token":secrets.token_urlsafe(24),"spf":"pending","dkim":"pending","verification":"pending","state":"inactive"}; self.audit(tenant,actor,"domain.register",did); return self.s.domains[did]
    def webhook(self, tenant, actor, url, resolver=socket.getaddrinfo):
        validate_callback_url(url,resolver); wid=str(uuid.uuid4()); secret=secrets.token_urlsafe(32)
        self.s.webhooks[wid]={"id":wid,"tenant_id":tenant,"url":url,"secret_hash":hash_secret(secret),"prefix":secret[:8],"status":"pending_verification","max_attempts":5,"backoff":"exponential-jitter"}; self.audit(tenant,actor,"webhook.create",wid); return {**self.s.webhooks[wid],"signing_secret":secret}
    def synthetic_message(self, tenant, actor, channel, reference):
        org=self.s.organizations[tenant]
        if org["status"]!="active" or org["kill_switch"] or channel not in org["services"]: raise PortalError("account_or_service_disabled")
        mid=str(uuid.uuid4()); price=1 if channel=="email" else 2
        self.s.messages[mid]={"id":mid,"tenant_id":tenant,"channel":channel,"recipient":"synthetic.invalid","sender":"synthetic","status":"synthetic_delivered","dlr":"delivered" if channel=="sms" else None,"bounce":None,"complaint":None,"suppression":False,"segments":1,"price_minor":price,"customer_reference":reference,"created_at":now(),"updated_at":now()}
        self.s.ledger.append({"id":str(uuid.uuid4()),"tenant_id":tenant,"type":"finalized_charge","amount_minor":-price,"message_id":mid,"at":now()}); self.audit(tenant,actor,f"{channel}.synthetic",mid); return self.s.messages[mid]
    def dashboard(self, tenant):
        return {"organization":self.s.organizations[tenant],"messages":[m for m in self.s.messages.values() if m["tenant_id"]==tenant],"ledger":[x for x in self.s.ledger if x["tenant_id"]==tenant],"audit":[x for x in self.s.audits if x["tenant_id"]==tenant],"credentials":self.list_tenant(self.s.credentials,tenant),"senders":self.list_tenant(self.s.senders,tenant),"domains":self.list_tenant(self.s.domains,tenant),"webhooks":self.list_tenant(self.s.webhooks,tenant),"subaccounts":[o for o in self.s.organizations.values() if o.get("parent_id")==tenant],"kyc":self.list_tenant(self.s.kyc,tenant),"invoices":self.list_tenant(self.s.invoices,tenant),"anomaly_flags":self.list_tenant(self.s.anomaly_flags,tenant)}
    def suspend(self, tenant, actor): self.s.organizations[tenant]["status"]="suspended"; self.audit(tenant,actor,"account.suspend",tenant)
    def update_limits(self, tenant, actor, *, requests_per_minute, usage_cap_minor, countries):
        row=self.s.organizations[tenant]; row["rate_limits"]={"requests_per_minute":requests_per_minute}; row["usage_cap_minor"]=usage_cap_minor; row["countries"]=countries; self.audit(tenant,actor,"limits.update",tenant); return row
    def set_kill_switch(self, tenant, actor, enabled):
        self.s.organizations[tenant]["kill_switch"]=enabled; self.audit(tenant,actor,"kill_switch.update",tenant,detail={"enabled":enabled}); return self.s.organizations[tenant]
    def kyc_submit(self, tenant, actor, identity, documents):
        kid=str(uuid.uuid4()); self.s.kyc[kid]={"id":kid,"tenant_id":tenant,"business_identity":identity,"document_metadata":documents,"review_state":"submitted","messaging_permissions":[],"created_at":now()}; self.s.organizations[tenant]["compliance_state"]="submitted"; self.audit(tenant,actor,"kyc.submit",kid); return self.s.kyc[kid]
    def webhook_test(self, tenant, actor, wid):
        row=self._tenant(self.s.webhooks,wid,tenant); row["last_test"]={"at":now(),"status":"synthetic_verified","network_request_sent":False}; row["status"]="verified_synthetic"; self.audit(tenant,actor,"webhook.test",wid); return row["last_test"]
    def invoice(self, tenant, actor, period, amount_minor=0):
        iid=str(uuid.uuid4()); self.s.invoices[iid]={"id":iid,"tenant_id":tenant,"period":period,"amount_minor":amount_minor,"currency":"USD","status":"draft","created_at":now()}; self.audit(tenant,actor,"invoice.create",iid); return self.s.invoices[iid]
    def credit(self, tenant, actor, amount_minor, reference):
        if amount_minor <= 0: raise PortalError("credit_must_be_positive")
        self.s.organizations[tenant]["balance_minor"] += amount_minor; row={"id":str(uuid.uuid4()),"tenant_id":tenant,"type":"credit","amount_minor":amount_minor,"reference":reference,"at":now()}; self.s.ledger.append(row); self.audit(tenant,actor,"credit.create",row["id"]); return row
    @staticmethod
    def list_tenant(rows, tenant): return [{k:v for k,v in row.items() if k not in {"secret_hash","signing_secret_hash"}} for row in rows.values() if row.get("tenant_id")==tenant]
    @staticmethod
    def _tenant(rows, key, tenant):
        row=rows.get(key)
        if not row or row["tenant_id"]!=tenant: raise PortalError("not_found")
        return row
