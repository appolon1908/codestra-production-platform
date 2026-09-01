from __future__ import annotations

import hashlib
import json
import re
import secrets
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
        domain_usable = bool(domain["active"] and domain["assignment_status"] != "BLOCKED_MISSING_CAMPAIGN_ASSIGNMENT")
        allowed = bool(domain_usable and (override or (owned and domain["id"] == user["domain_id"] and domain["campaign_id"] == user["campaign_id"] and domain["allow_agent_send"])))
        if override and not reason:
            raise PolicyError("admin_override_reason_required")
        self._audit(user["keycloak_subject"], "mail.send.authorize" if not override else "mail.domain.override",
                    domain["id"], domain["campaign_id"], reason, None, "ALLOW" if allowed else "DENY")
        self.db.commit()
        if not allowed:
            raise PolicyError("sender_domain_denied")
        return {"allowed": True, "override": bool(override), "domain": domain["domain"], "campaign_id": domain["campaign_id"]}

    def route_inbound(self, recipient: str) -> dict[str, Any]:
        recipient = recipient.lower().strip()
        domain = self.domain(address_domain(recipient))
        if not domain["active"] or not domain["allow_agent_receive"]:
            raise PolicyError("inbound_domain_denied")
        target = self.db.execute(
            "SELECT mail_user_uuid AS mailbox_uuid,campaign_id FROM mail_user WHERE primary_address=? AND active=1",
            (recipient,),
        ).fetchone()
        if not target:
            target = self.db.execute("""SELECT u.mail_user_uuid AS mailbox_uuid,u.campaign_id
                FROM mail_alias a JOIN mail_user u ON u.mail_user_uuid=a.target_mail_user_uuid
                WHERE a.address=? AND a.active=1 AND u.active=1""", (recipient,)).fetchone()
        if not target:
            target = self.db.execute(
                "SELECT mailbox_uuid,campaign_id FROM shared_mailbox WHERE address=? AND active=1",
                (recipient,),
            ).fetchone()
        if not target or target["campaign_id"] != domain["campaign_id"]:
            raise PolicyError("inbound_recipient_not_found")
        return {"domain_id": domain["id"], "domain": domain["domain"],
                "campaign_id": domain["campaign_id"], "business_unit_id": domain["business_unit_id"],
                "mailbox_uuid": target["mailbox_uuid"]}

    def messages_for_user(self, *, tenant: str, mail_user_uuid: str,
                          message_uuid: str | None = None) -> list[sqlite3.Row]:
        user = self._user(mail_user_uuid)
        parameters: list[Any] = [mail_user_uuid, mail_user_uuid, mail_user_uuid, tenant]
        message_filter = ""
        if message_uuid:
            message_filter = " AND m.message_uuid=?"
            parameters.append(message_uuid)
        return self.db.execute(f"""SELECT m.* FROM mail_message m
            WHERE (m.mailbox_uuid=? OR EXISTS (
                SELECT 1 FROM shared_mailbox s
                LEFT JOIN shared_mailbox_member sm ON sm.mailbox_uuid=s.mailbox_uuid
                    AND sm.mail_user_uuid=? AND sm.permission IN ('READ','SEND','MANAGE')
                WHERE s.mailbox_uuid=m.mailbox_uuid AND s.active=1
                    AND (sm.mail_user_uuid IS NOT NULL OR s.supervisor_mail_user_uuid=?)))
              AND m.tenant=?{message_filter}
            ORDER BY m.created_at DESC LIMIT 200""", parameters).fetchall()

    def register_message(self, *, tenant: str, direction: str, sender: str,
                         recipients: list[str], correlation_id: str,
                         idempotency_key: str, message_id: str | None = None,
                         in_reply_to: str | None = None,
                         references: list[str] | None = None,
                         mailbox_uuid: str | None = None,
                         actor_uuid: str | None = None) -> dict[str, Any]:
        if direction not in {"INBOUND", "OUTBOUND"} or not recipients:
            raise PolicyError("invalid_message")
        if direction == "INBOUND":
            route = self.route_inbound(recipients[0])
            mailbox_uuid = route["mailbox_uuid"]
        else:
            if not actor_uuid:
                raise PolicyError("authenticated_actor_required")
            route = self.authorize_sender(actor_uuid, sender)
            route["business_unit_id"] = self._user(actor_uuid)["business_unit_id"]
            mailbox_uuid = mailbox_uuid or actor_uuid
        refs = references or []
        normalized_recipients = [value.lower() for value in recipients]
        duplicate = self.db.execute(
            "SELECT * FROM mail_message WHERE tenant=? AND idempotency_key=?",
            (tenant, idempotency_key),
        ).fetchone()
        if duplicate:
            replay_matches = (
                duplicate["mailbox_uuid"] == mailbox_uuid
                and duplicate["direction"] == direction
                and duplicate["sender"] == sender.lower()
                and json.loads(duplicate["recipients_json"]) == normalized_recipients
                and duplicate["correlation_id"] == correlation_id
                and duplicate["message_id_header"] == message_id
                and duplicate["in_reply_to"] == in_reply_to
                and json.loads(duplicate["references_json"]) == refs
            )
            if not replay_matches:
                raise PolicyError("idempotency_conflict")
            return {**dict(duplicate), "duplicate": True}
        parent_ids = [value for value in [in_reply_to, *refs] if value]
        parent = None
        for parent_id in parent_ids:
            parent = self.db.execute(
                "SELECT thread_uuid FROM mail_message WHERE message_id_header=?", (parent_id,)
            ).fetchone()
            if parent:
                break
        stamp = now(); message_uuid = str(uuid.uuid4())
        thread_uuid = parent["thread_uuid"] if parent else str(uuid.uuid4())
        self.db.execute(
            """INSERT INTO mail_message(message_uuid,mailbox_uuid,tenant,campaign,domain,channel,direction,
               sender,recipients_json,thread_uuid,message_id_header,in_reply_to,references_json,desired_state,
               actual_state,correlation_id,idempotency_key,created_at,updated_at)
               VALUES(?,?,?,?,?,'EMAIL',?,?,?,?,?,?,?,'REGISTERED','PENDING',?,?,?,?)""",
            (message_uuid, mailbox_uuid, tenant, route["campaign_id"], route["domain"], direction,
             sender.lower(), json.dumps(normalized_recipients), thread_uuid, message_id,
             in_reply_to, json.dumps(refs), correlation_id, idempotency_key, stamp, stamp),
        )
        outbox_payload = {
            "event_type": "OutboundMailRequestedV1" if direction == "OUTBOUND" else "InboundMailReceivedV1",
            "message_uuid": message_uuid, "thread_uuid": thread_uuid, "tenant": tenant,
            "campaign": route["campaign_id"], "domain": route["domain"], "correlation_id": correlation_id,
            "idempotency_key": idempotency_key, "direction": direction,
        }
        self.db.execute("""INSERT INTO mail_outbox(outbox_uuid,aggregate_uuid,event_type,payload_json,
            correlation_id,idempotency_key,state,attempts,available_at,created_at)
            VALUES(?,?,?,?,?,?,'PENDING',0,?,?)""",
            (str(uuid.uuid4()), message_uuid, outbox_payload["event_type"],
             json.dumps(outbox_payload, sort_keys=True), correlation_id, idempotency_key, stamp, stamp))
        self._audit(actor_uuid or "inbound-mail-adapter", "mail.message.registered", route.get("domain_id"),
                    route["campaign_id"], None, message_uuid, "ALLOW")
        self.db.commit()
        return {**dict(self.db.execute("SELECT * FROM mail_message WHERE message_uuid=?", (message_uuid,)).fetchone()),
                "duplicate": False}

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

    def create_shared_mailbox(self, *, actor_uuid: str, address: str, campaign_id: str,
                              supervisor_uuid: str, members: list[tuple[str, str]]) -> str:
        actor = self._user(actor_uuid); domain = self.domain(address_domain(address))
        if actor["role"] not in ADMIN_ROLES | {"CAMPAIGN_MANAGER", "SUPERVISOR"}:
            raise PolicyError("shared_mailbox_manage_denied")
        if not domain["allow_shared_mailboxes"] or domain["campaign_id"] != campaign_id:
            raise PolicyError("shared_mailbox_domain_denied")
        self._user(supervisor_uuid); mailbox_uuid = str(uuid.uuid4())
        self.db.execute("INSERT INTO shared_mailbox VALUES(?,?,?,?,?,?,?)", (
            mailbox_uuid, address.lower(), domain["id"], campaign_id, supervisor_uuid, 1, now()))
        for member_uuid, permission in members:
            member = self._user(member_uuid)
            if member["campaign_id"] != campaign_id or permission not in {"READ", "SEND", "MANAGE"}:
                raise PolicyError("shared_mailbox_member_denied")
            self.db.execute("INSERT INTO shared_mailbox_member VALUES(?,?,?)", (mailbox_uuid, member_uuid, permission))
        self._audit(actor["keycloak_subject"], "mail.shared.created", domain["id"], campaign_id, None, None, "ALLOW")
        self.db.commit(); return mailbox_uuid

    def create_app_password(self, mail_user_uuid: str, label: str, actor: str) -> tuple[str, str]:
        user = self._user(mail_user_uuid)
        if not user["active"]: raise PolicyError("mail_user_suspended")
        secret = secrets.token_urlsafe(32); salt = secrets.token_hex(16)
        digest = hashlib.scrypt(secret.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1).hex()
        credential_uuid = str(uuid.uuid4())
        self.db.execute("INSERT INTO mail_app_password VALUES(?,?,?,?,?,?,?,?,?)", (
            credential_uuid, mail_user_uuid, label, salt, digest, 1, now(), None, None))
        self._audit(actor, "mail.app_password.created", user["domain_id"], user["campaign_id"], label, None, "ALLOW")
        self.db.commit(); return credential_uuid, secret

    def verify_app_password(self, mail_user_uuid: str, secret: str) -> bool:
        for row in self.db.execute("SELECT * FROM mail_app_password WHERE mail_user_uuid=? AND active=1", (mail_user_uuid,)):
            digest = hashlib.scrypt(secret.encode(), salt=bytes.fromhex(row["secret_salt"]), n=2**14, r=8, p=1).hex()
            if secrets.compare_digest(digest, row["secret_hash"]): return True
        return False

    def revoke_app_password(self, credential_uuid: str, actor: str) -> None:
        row = self.db.execute("SELECT p.*,u.domain_id,u.campaign_id FROM mail_app_password p JOIN mail_user u USING(mail_user_uuid) WHERE credential_uuid=?", (credential_uuid,)).fetchone()
        if not row: raise PolicyError("app_password_not_found")
        self.db.execute("UPDATE mail_app_password SET active=0,revoked_at=? WHERE credential_uuid=?", (now(), credential_uuid))
        self._audit(actor, "mail.app_password.revoked", row["domain_id"], row["campaign_id"], row["label"], None, "ALLOW")
        self.db.commit()

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
