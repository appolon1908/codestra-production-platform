from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DOMAIN_TYPES = {"AGENT_CAMPAIGN", "SHARED_INBOX", "CORPORATE_ADMIN", "SYSTEM_TRANSACTIONAL", "SERVICE_ONLY"}
ROLES = {"EMAIL_OWNER", "EMAIL_ADMIN", "DOMAIN_ADMIN", "CAMPAIGN_MANAGER", "SUPERVISOR", "AGENT", "STANDALONE_MAIL_USER", "SHARED_INBOX_USER", "READ_ONLY_AUDITOR", "SERVICE_ACCOUNT"}
ADMIN_ROLES = {"EMAIL_OWNER", "EMAIL_ADMIN"}
ADDRESS = re.compile(r"^[^@\s]+@([a-z0-9.-]+)$", re.I)


class PolicyError(ValueError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def address_domain(address: str) -> str:
    match = ADDRESS.fullmatch(address.strip())
    if not match:
        raise PolicyError("invalid_email_address")
    return match.group(1).lower().rstrip(".")


class MailRegistry:
    def __init__(self, database: str | Path = ":memory:") -> None:
        self.db = sqlite3.connect(str(database))
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")

    def migrate(self) -> None:
        self.db.executescript(Path(__file__).with_name("schema.sql").read_text())

    def register_domain(self, *, domain: str, brand: str, domain_type: str,
                        business_unit_id: str | None = None, campaign_id: str | None = None,
                        active: bool = False, assignment_status: str | None = None,
                        **flags: Any) -> dict[str, Any]:
        domain = domain.lower().strip().rstrip(".")
        if domain_type not in DOMAIN_TYPES or not re.fullmatch(r"[a-z0-9.-]+", domain):
            raise PolicyError("invalid_domain")
        status = assignment_status or ("SYSTEM_ONLY" if domain_type in {"SYSTEM_TRANSACTIONAL", "SERVICE_ONLY"} else "ASSIGNED" if campaign_id else "BLOCKED_MISSING_CAMPAIGN_ASSIGNMENT")
        if status == "ASSIGNED" and not campaign_id:
            raise PolicyError("campaign_assignment_required")
        existing = self.db.execute("SELECT * FROM mail_domain WHERE domain=?", (domain,)).fetchone()
        if existing and existing["campaign_id"] != campaign_id:
            raise PolicyError("domain_campaign_conflict")
        stamp = now(); domain_id = existing["id"] if existing else str(uuid.uuid4())
        values = (
            domain_id, domain, business_unit_id, campaign_id, brand, domain_type, int(active),
            int(flags.get("allow_agent_send", False)), int(flags.get("allow_agent_receive", False)),
            int(flags.get("allow_standalone_users", False)), int(flags.get("allow_shared_mailboxes", False)),
            int(flags.get("admin_override_allowed", False)), flags.get("mailbox_backend", "stalwart"), status,
            existing["created_at"] if existing else stamp, stamp,
        )
        self.db.execute("""INSERT INTO mail_domain(id,domain,business_unit_id,campaign_id,brand,domain_type,active,
          allow_agent_send,allow_agent_receive,allow_standalone_users,allow_shared_mailboxes,admin_override_allowed,
          mailbox_backend,assignment_status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(domain) DO UPDATE SET business_unit_id=excluded.business_unit_id,campaign_id=excluded.campaign_id,
          brand=excluded.brand,domain_type=excluded.domain_type,active=excluded.active,allow_agent_send=excluded.allow_agent_send,
          allow_agent_receive=excluded.allow_agent_receive,allow_standalone_users=excluded.allow_standalone_users,
          allow_shared_mailboxes=excluded.allow_shared_mailboxes,admin_override_allowed=excluded.admin_override_allowed,
          mailbox_backend=excluded.mailbox_backend,assignment_status=excluded.assignment_status,updated_at=excluded.updated_at""", values)
        self.db.commit()
        return self.domain(domain)

    def domain(self, domain: str) -> dict[str, Any]:
        row = self.db.execute("SELECT * FROM mail_domain WHERE domain=?", (domain.lower(),)).fetchone()
        if not row:
            raise PolicyError("domain_not_found")
        return dict(row)

    def create_user(self, *, keycloak_subject: str, display_name: str, primary_address: str,
                    user_type: str, role: str, quota: int, odoo_user_id: int | None = None,
                    campaign_id: str | None = None, business_unit_id: str | None = None) -> dict[str, Any]:
        if role not in ROLES or user_type not in {"ODOO_LINKED", "STANDALONE", "SHARED_INBOX_MEMBER", "ADMIN"}:
            raise PolicyError("invalid_user_authority")
        if user_type == "ODOO_LINKED" and odoo_user_id is None:
            raise PolicyError("odoo_link_required")
        domain = self.domain(address_domain(primary_address))
        if not domain["active"] or domain["assignment_status"] == "BLOCKED_MISSING_CAMPAIGN_ASSIGNMENT":
            raise PolicyError("domain_not_provisionable")
        if user_type == "STANDALONE" and not domain["allow_standalone_users"]:
            raise PolicyError("standalone_user_denied")
        if role not in ADMIN_ROLES and domain["campaign_id"] != campaign_id:
            raise PolicyError("campaign_domain_mismatch")
        stamp = now(); user_id = str(uuid.uuid4())
        self.db.execute("INSERT INTO mail_user VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            user_id, keycloak_subject, odoo_user_id, display_name, primary_address.lower(), domain["id"],
            campaign_id, business_unit_id, user_type, role, quota, 1, 1, stamp, stamp, None))
        self._audit(keycloak_subject, "mail.user.created", domain["id"], campaign_id, None, None, "ALLOW")
        self.db.commit()
        return dict(self.db.execute("SELECT * FROM mail_user WHERE mail_user_uuid=?", (user_id,)).fetchone())

    def link_odoo(self, mail_user_uuid: str, odoo_user_id: int, actor: str) -> None:
        row = self._user(mail_user_uuid)
        if row["odoo_user_id"] not in (None, odoo_user_id):
            raise PolicyError("odoo_link_conflict")
        self.db.execute("UPDATE mail_user SET odoo_user_id=?,user_type='ODOO_LINKED',updated_at=? WHERE mail_user_uuid=?", (odoo_user_id, now(), mail_user_uuid))
        self._audit(actor, "mail.user.odoo_linked", row["domain_id"], row["campaign_id"], None, None, "ALLOW")
        self.db.commit()

    def authorize_sender(self, mail_user_uuid: str, from_address: str, *, reason: str | None = None) -> dict[str, Any]:
        user = self._user(mail_user_uuid)
        if not user["active"]:
            raise PolicyError("mail_user_suspended")
        domain = self.domain(address_domain(from_address))
        owned = from_address.lower() == user["primary_address"].lower() or self.db.execute(
            "SELECT 1 FROM mail_alias WHERE target_mail_user_uuid=? AND address=? AND active=1", (mail_user_uuid, from_address.lower())).fetchone()
        override = user["role"] in ADMIN_ROLES and domain["admin_override_allowed"]
        allowed = bool(override or (owned and domain["id"] == user["domain_id"] and domain["campaign_id"] == user["campaign_id"] and domain["allow_agent_send"]))
        if override and not reason:
            raise PolicyError("admin_override_reason_required")
        self._audit(user["keycloak_subject"], "mail.send.authorize" if not override else "mail.domain.override",
                    domain["id"], domain["campaign_id"], reason, None, "ALLOW" if allowed else "DENY")
        self.db.commit()
        if not allowed:
            raise PolicyError("sender_domain_denied")
        return {"allowed": True, "override": bool(override), "domain": domain["domain"], "campaign_id": domain["campaign_id"]}

    def route_inbound(self, recipient: str) -> dict[str, Any]:
        domain = self.domain(address_domain(recipient))
        if not domain["active"] or not domain["allow_agent_receive"]:
            raise PolicyError("inbound_domain_denied")
        # Campaign authority comes only from the server-side recipient domain.
        return {"domain_id": domain["id"], "domain": domain["domain"], "campaign_id": domain["campaign_id"], "business_unit_id": domain["business_unit_id"]}

    def add_alias(self, actor_uuid: str, address: str, target_uuid: str) -> str:
        actor, target = self._user(actor_uuid), self._user(target_uuid)
        domain = self.domain(address_domain(address))
        admin = actor["role"] in ADMIN_ROLES
        if not admin and (actor_uuid != target_uuid or domain["id"] != target["domain_id"] or domain["campaign_id"] != target["campaign_id"]):
            raise PolicyError("alias_domain_denied")
        alias_id = str(uuid.uuid4())
        self.db.execute("INSERT INTO mail_alias VALUES(?,?,?,?,?,?,?)", (alias_id,address.lower(),domain["id"],target_uuid,domain["campaign_id"],1,now()))
        self._audit(actor["keycloak_subject"], "mail.alias.created", domain["id"], domain["campaign_id"], None, None, "ALLOW")
        self.db.commit(); return alias_id

    def suspend(self, mail_user_uuid: str, actor: str, reason: str) -> None:
        user = self._user(mail_user_uuid)
        self.db.execute("UPDATE mail_user SET active=0,updated_at=? WHERE mail_user_uuid=?", (now(), mail_user_uuid))
        self._audit(actor, "mail.user.suspended", user["domain_id"], user["campaign_id"], reason, None, "ALLOW")
        self.db.commit()

    def reconcile(self) -> dict[str, Any]:
        findings: list[dict[str, str]] = []
        for row in self.db.execute("SELECT * FROM mail_user"):
            domain = self.db.execute("SELECT * FROM mail_domain WHERE id=?", (row["domain_id"],)).fetchone()
            if not domain: findings.append({"code": "MISSING_DOMAIN", "user": row["mail_user_uuid"]})
            elif row["role"] not in ADMIN_ROLES and row["campaign_id"] != domain["campaign_id"]:
                findings.append({"code": "WRONG_CAMPAIGN", "user": row["mail_user_uuid"]})
        run_id = str(uuid.uuid4()); stamp = now(); status = "DRIFT" if findings else "PASS"
        self.db.execute("INSERT INTO reconciliation_run VALUES(?,?,?,?,?)", (run_id,stamp,stamp,status,json.dumps(findings,sort_keys=True)))
        self.db.commit(); return {"run_uuid": run_id, "status": status, "findings": findings}

    def _user(self, user_uuid: str) -> sqlite3.Row:
        row = self.db.execute("SELECT * FROM mail_user WHERE mail_user_uuid=?", (user_uuid,)).fetchone()
        if not row: raise PolicyError("mail_user_not_found")
        return row

    def _audit(self, actor: str, action: str, domain_id: str | None, campaign_id: str | None,
               reason: str | None, message_uuid: str | None, outcome: str) -> None:
        self.db.execute("INSERT INTO mail_audit VALUES(?,?,?,?,?,?,?,?,?,?)", (
            str(uuid.uuid4()), actor, action, domain_id, campaign_id, reason, message_uuid, outcome, "{}", now()))
