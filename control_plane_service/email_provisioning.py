"""Fail-closed campaign mailbox registry and idempotent provisioning workflow."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from typing import Any, Protocol

from .core import ControlPlaneError
from .database import Connection, IntegrityError, is_postgres


DOMAIN_ACTIVE = "ACTIVE"
MAILBOX_ACTIVE = "ACTIVE"
BLOCKED_DOMAIN = "BLOCKED_DOMAIN_MAPPING_REQUIRED"
ADDRESS_CONFLICT = "EMAIL_ADDRESS_CONFLICT"
PROVISIONING_FAILED = "PROVISIONING_FAILED"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def normalize_first_name(value: str) -> str:
    transliterated = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode()
    local = re.sub(r"[^a-z0-9.-]", "", transliterated.lower())
    local = re.sub(r"[.-]{2,}", lambda m: m.group(0)[0], local).strip(".-")
    if len(local) < 2:
        raise ControlPlaneError("invalid_first_name_local_part")
    return local


def normalize_domain(value: str) -> str:
    domain = (value or "").strip().lower().rstrip(".")
    if not re.fullmatch(r"(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", domain):
        raise ControlPlaneError("invalid_email_domain")
    return domain


def db_bool(value: bool) -> bool | int:
    return value if is_postgres() else int(value)


SCHEMA = """
CREATE TABLE IF NOT EXISTS cp_campaign_email_domain(
 id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,campaign_id TEXT NOT NULL,campaign_name TEXT NOT NULL,
 primary_domain TEXT NOT NULL,alias_domains TEXT NOT NULL DEFAULT '[]',sender_domain_verified INTEGER NOT NULL DEFAULT 0,
 inbound_domain_verified INTEGER NOT NULL DEFAULT 0,sending_enabled INTEGER NOT NULL DEFAULT 0,
 receiving_enabled INTEGER NOT NULL DEFAULT 0,default_reply_to TEXT,support_address TEXT,billing_address TEXT,
 status TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,approved_by TEXT,approved_at TEXT,
 UNIQUE(tenant_id,campaign_id),UNIQUE(tenant_id,primary_domain));
CREATE TABLE IF NOT EXISTS cp_agent_mailbox(
 mailbox_id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,agent_id TEXT NOT NULL,employee_id TEXT,
 keycloak_user_id TEXT,odoo_user_id TEXT,vicidial_user_id TEXT,campaign_id TEXT NOT NULL,
 campaign_name TEXT NOT NULL,domain TEXT NOT NULL,local_part TEXT NOT NULL,primary_email TEXT NOT NULL,
 display_name TEXT NOT NULL,sending_enabled INTEGER NOT NULL DEFAULT 0,receiving_enabled INTEGER NOT NULL DEFAULT 0,
 mailbox_status TEXT NOT NULL,quota INTEGER NOT NULL,rate_limit INTEGER NOT NULL,created_at TEXT NOT NULL,
 activated_at TEXT,suspended_at TEXT,deactivated_at TEXT,last_send_at TEXT,last_receive_at TEXT,
 provisioning_correlation_id TEXT NOT NULL,provisioning_error TEXT,audit_version INTEGER NOT NULL DEFAULT 1,
 previous_mailbox_id TEXT,UNIQUE(tenant_id,domain,local_part),UNIQUE(tenant_id,agent_id,campaign_id));
CREATE TABLE IF NOT EXISTS cp_mailbox_provisioning_event(
 event_id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,idempotency_key TEXT NOT NULL,payload_hash TEXT NOT NULL,
 mailbox_id TEXT,status TEXT NOT NULL,correlation_id TEXT NOT NULL,error_detail_safe TEXT,created_at TEXT NOT NULL,
 UNIQUE(tenant_id,idempotency_key));
"""


class IdentityAdapter(Protocol):
    def reconcile(self, command: dict[str, Any]) -> dict[str, Any]: ...
    def revoke_mailbox_grants(self, command: dict[str, Any]) -> None: ...


class MailAdapter(Protocol):
    def provision_identity(self, command: dict[str, Any]) -> dict[str, Any]: ...
    def provision_inbound_route(self, command: dict[str, Any]) -> dict[str, Any]: ...
    def authorize_sender(self, command: dict[str, Any]) -> dict[str, Any]: ...
    def validate_send_path(self, command: dict[str, Any]) -> bool: ...
    def validate_inbound_route(self, command: dict[str, Any]) -> bool: ...
    def disable(self, command: dict[str, Any]) -> None: ...


class OdooAdapter(Protocol):
    def write_mailbox(self, command: dict[str, Any]) -> None: ...


class CampaignMailboxRegistry:
    def __init__(self, path: str):
        self.path = path
        if not is_postgres():
            with Connection(path) as db:
                db.executescript(SCHEMA)

    def _tenant(self, db: Connection, tenant: str) -> None:
        if not tenant or len(tenant) > 64:
            raise ControlPlaneError("invalid_tenant")
        if is_postgres():
            db.execute("SELECT set_config('app.tenant_id', ?, true)", (tenant,))

    def approve_domain(self, value: dict[str, Any]) -> dict[str, Any]:
        tenant, campaign = str(value["tenant_id"]), str(value["campaign_id"])
        domain, stamp = normalize_domain(value["primary_domain"]), now()
        aliases = sorted({normalize_domain(x) for x in value.get("alias_domains", []) if x})
        approved_by = str(value.get("approved_by") or "").strip()
        if not approved_by:
            raise ControlPlaneError("domain_approval_required")
        gates = all(bool(value.get(x)) for x in (
            "sender_domain_verified", "inbound_domain_verified", "sending_enabled", "receiving_enabled"
        ))
        status = DOMAIN_ACTIVE if gates else "UNVERIFIED"
        row_id = str(value.get("id") or uuid.uuid4())
        try:
            with Connection(self.path) as db:
                self._tenant(db, tenant)
                prior = db.execute("SELECT id,created_at FROM cp_campaign_email_domain WHERE tenant_id=? AND campaign_id=?", (tenant,campaign)).fetchone()
                if prior:
                    row_id = prior["id"]
                    db.execute("UPDATE cp_campaign_email_domain SET campaign_name=?,primary_domain=?,alias_domains=?,sender_domain_verified=?,inbound_domain_verified=?,sending_enabled=?,receiving_enabled=?,default_reply_to=?,support_address=?,billing_address=?,status=?,updated_at=?,approved_by=?,approved_at=? WHERE id=?", (
                        value["campaign_name"],domain,canonical(aliases),db_bool(bool(value.get("sender_domain_verified"))),db_bool(bool(value.get("inbound_domain_verified"))),db_bool(bool(value.get("sending_enabled"))),db_bool(bool(value.get("receiving_enabled"))),value.get("default_reply_to"),value.get("support_address"),value.get("billing_address"),status,stamp,approved_by,stamp,row_id))
                else:
                    db.execute("INSERT INTO cp_campaign_email_domain VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                        row_id,tenant,campaign,value["campaign_name"],domain,canonical(aliases),db_bool(bool(value.get("sender_domain_verified"))),db_bool(bool(value.get("inbound_domain_verified"))),db_bool(bool(value.get("sending_enabled"))),db_bool(bool(value.get("receiving_enabled"))),value.get("default_reply_to"),value.get("support_address"),value.get("billing_address"),status,stamp,stamp,approved_by,stamp))
            return {"id":row_id,"tenant_id":tenant,"campaign_id":campaign,"primary_domain":domain,"status":status}
        except IntegrityError as exc:
            raise ControlPlaneError("campaign_domain_collision") from exc

    def get_mailbox(self, tenant: str, mailbox_id: str) -> dict[str, Any] | None:
        with Connection(self.path) as db:
            self._tenant(db, tenant)
            row = db.execute("SELECT * FROM cp_agent_mailbox WHERE tenant_id=? AND mailbox_id=?", (tenant,mailbox_id)).fetchone()
            return dict(row) if row else None

    def provision(self, value: dict[str, Any], identity: IdentityAdapter, mail: MailAdapter,
                  odoo: OdooAdapter) -> tuple[dict[str, Any], bool]:
        tenant, key = str(value["tenant_id"]), str(value["idempotency_key"])
        correlation = str(value.get("correlation_id") or uuid.uuid4())
        request_hash, stamp = digest(value.get("immutable_payload", value)), now()
        if not value.get("active") or not value.get("campaign_id") or not value.get("supervisor_id") or not value.get("last_name"):
            raise ControlPlaneError("invalid_agent_business_state")
        local = normalize_first_name(str(value.get("first_name") or ""))
        with Connection(self.path) as db:
            self._tenant(db, tenant)
            event = db.execute("SELECT * FROM cp_mailbox_provisioning_event WHERE tenant_id=? AND idempotency_key=?", (tenant,key)).fetchone()
            if event:
                if event["payload_hash"] != request_hash:
                    raise ControlPlaneError("idempotency_conflict")
                mailbox = self.get_mailbox(tenant,event["mailbox_id"]) if event["mailbox_id"] else None
                return mailbox or {"mailbox_status":event["status"],"provisioning_error":event["error_detail_safe"]}, True
            domain = db.execute("SELECT * FROM cp_campaign_email_domain WHERE tenant_id=? AND campaign_id=?", (tenant,str(value["campaign_id"]))).fetchone()
            if not domain or domain["status"] != DOMAIN_ACTIVE:
                event_id = str(uuid.uuid4())
                db.execute("INSERT INTO cp_mailbox_provisioning_event VALUES(?,?,?,?,?,?,?,?,?)", (event_id,tenant,key,request_hash,None,BLOCKED_DOMAIN,correlation,"approved verified domain mapping required",stamp))
                return {"mailbox_status":BLOCKED_DOMAIN,"provisioning_error":"approved verified domain mapping required"}, False
            mailbox_id, primary = str(uuid.uuid4()), f"{local}@{domain['primary_domain']}"
            reserved = db.execute("INSERT INTO cp_agent_mailbox VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING RETURNING mailbox_id", (
                mailbox_id,tenant,str(value["agent_id"]),value.get("employee_id"),value.get("keycloak_user_id"),value.get("odoo_user_id"),value.get("vicidial_user_id"),str(value["campaign_id"]),domain["campaign_name"],domain["primary_domain"],local,primary,value["display_name"],db_bool(False),db_bool(False),"PROVISIONING",int(value.get("quota",2048)),int(value.get("rate_limit",60)),stamp,None,None,None,None,None,correlation,None,1,value.get("previous_mailbox_id"))).fetchone()
            if not reserved:
                event_id = str(uuid.uuid4())
                db.execute("INSERT INTO cp_mailbox_provisioning_event VALUES(?,?,?,?,?,?,?,?,?)", (event_id,tenant,key,request_hash,None,ADDRESS_CONFLICT,correlation,"address already reserved",stamp))
                return {"mailbox_status":ADDRESS_CONFLICT,"primary_email":primary,"provisioning_error":"address already reserved"}, False
            db.execute("INSERT INTO cp_mailbox_provisioning_event VALUES(?,?,?,?,?,?,?,?,?)", (str(uuid.uuid4()),tenant,key,request_hash,mailbox_id,"PROVISIONING",correlation,None,stamp))

        command = {"tenant_id":tenant,"campaign_id":str(value["campaign_id"]),"agent_id":str(value["agent_id"]),"primary_email":primary,"display_name":value["display_name"],"correlation_id":correlation,"idempotency_key":key,"roles":["codestra-email-agent"],"scopes":["klyrow.email.send.own","klyrow.email.read.own","klyrow.email.reply.own","klyrow.email.attachments.own"],"quota":int(value.get("quota",2048)),"rate_limit":int(value.get("rate_limit",60))}
        try:
            kc = identity.reconcile(command)
            mail.provision_identity(command)
            mail.provision_inbound_route(command)
            mail.authorize_sender(command)
            odoo.write_mailbox(command)
            if not mail.validate_send_path({**command,"external_delivery":False}):
                raise ControlPlaneError("send_path_validation_failed")
            if not mail.validate_inbound_route(command):
                raise ControlPlaneError("inbound_route_validation_failed")
            with Connection(self.path) as db:
                self._tenant(db,tenant)
                db.execute("UPDATE cp_agent_mailbox SET keycloak_user_id=?,sending_enabled=?,receiving_enabled=?,mailbox_status=?,activated_at=?,audit_version=audit_version+1 WHERE mailbox_id=?", (kc.get("user_id"),db_bool(True),db_bool(True),MAILBOX_ACTIVE,now(),mailbox_id))
                db.execute("UPDATE cp_mailbox_provisioning_event SET status=? WHERE tenant_id=? AND idempotency_key=?", (MAILBOX_ACTIVE,tenant,key))
            return self.get_mailbox(tenant,mailbox_id) or {}, False
        except Exception as exc:
            safe = str(exc)[:240] if isinstance(exc, ControlPlaneError) else "downstream provisioning failure"
            try:
                mail.disable(command)
            finally:
                identity.revoke_mailbox_grants(command)
            with Connection(self.path) as db:
                self._tenant(db,tenant)
                db.execute("UPDATE cp_agent_mailbox SET sending_enabled=?,receiving_enabled=?,mailbox_status=?,provisioning_error=?,audit_version=audit_version+1 WHERE mailbox_id=?", (db_bool(False),db_bool(False),PROVISIONING_FAILED,safe,mailbox_id))
                db.execute("UPDATE cp_mailbox_provisioning_event SET status=?,error_detail_safe=? WHERE tenant_id=? AND idempotency_key=?", (PROVISIONING_FAILED,safe,tenant,key))
            return self.get_mailbox(tenant,mailbox_id) or {}, False

    def suspend(self, tenant: str, mailbox_id: str, identity: IdentityAdapter, mail: MailAdapter) -> dict[str, Any]:
        mailbox = self.get_mailbox(tenant,mailbox_id)
        if not mailbox:
            raise ControlPlaneError("mailbox_not_found")
        command = {
            "tenant_id": tenant, "agent_id": mailbox["agent_id"],
            "campaign_id": mailbox["campaign_id"], "primary_email": mailbox["primary_email"],
            "correlation_id": str(uuid.uuid4()),
            "idempotency_key": f"suspend:{mailbox_id}:{mailbox['audit_version']}",
            "roles": ["codestra-email-agent"],
            "scopes": ["klyrow.email.send.own", "klyrow.email.read.own",
                       "klyrow.email.reply.own", "klyrow.email.attachments.own"],
        }
        mail.disable(command)
        identity.revoke_mailbox_grants(command)
        with Connection(self.path) as db:
            self._tenant(db,tenant)
            db.execute("UPDATE cp_agent_mailbox SET sending_enabled=?,receiving_enabled=?,mailbox_status='SUSPENDED',suspended_at=?,audit_version=audit_version+1 WHERE mailbox_id=?", (db_bool(False),db_bool(False),now(),mailbox_id))
        return self.get_mailbox(tenant,mailbox_id) or {}

    def authorize_from(self, tenant: str, agent_id: str, campaign_id: str,
                       from_address: str) -> dict[str, Any]:
        """Enforce exact tenant/campaign/agent sender ownership; no impersonation."""
        with Connection(self.path) as db:
            self._tenant(db,tenant)
            row = db.execute("SELECT * FROM cp_agent_mailbox WHERE tenant_id=? AND agent_id=? AND campaign_id=? AND lower(primary_email)=?", (tenant,agent_id,campaign_id,from_address.strip().lower())).fetchone()
        if not row or row["mailbox_status"] != MAILBOX_ACTIVE or not bool(row["sending_enabled"]):
            raise ControlPlaneError("mailbox_sender_not_authorized")
        return dict(row)

    def route_inbound(self, recipient: str) -> dict[str, Any]:
        """Resolve one exact active recipient. Deliberately provides no catch-all."""
        normalized = recipient.strip().lower()
        with Connection(self.path) as db:
            row = db.execute("SELECT * FROM cp_agent_mailbox WHERE lower(primary_email)=? AND mailbox_status='ACTIVE' AND receiving_enabled=?", (normalized,db_bool(True))).fetchone()
        if not row:
            raise ControlPlaneError("inbound_recipient_not_found")
        return dict(row)
