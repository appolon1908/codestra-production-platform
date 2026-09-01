from __future__ import annotations

import json
import os
import sqlite3
from functools import lru_cache
from typing import Any

import jwt
from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from jwt import PyJWKClient
from pydantic import BaseModel, Field

from .registry import MailRegistry, PolicyError

ISSUER = os.getenv("MAIL_OIDC_ISSUER", "https://auth.codestra.co/realms/codestra")
AUDIENCE = os.getenv("MAIL_OIDC_AUDIENCE", "codestra-mail-api")
DATABASE = os.getenv("MAIL_REGISTRY_DATABASE", "/var/lib/codestra-mail/registry.db")


class Principal(BaseModel):
    subject: str
    email: str
    tenant: str
    scopes: set[str]
    roles: set[str]


class MessageCommand(BaseModel):
    sender: str
    recipients: list[str] = Field(min_length=1, max_length=50)
    correlation_id: str = Field(min_length=8, max_length=200)
    idempotency_key: str = Field(min_length=8, max_length=200)
    message_id: str | None = None
    in_reply_to: str | None = None
    references: list[str] = Field(default_factory=list, max_length=100)


@lru_cache
def jwks() -> PyJWKClient:
    return PyJWKClient(f"{ISSUER}/protocol/openid-connect/certs", cache_keys=True)


def decode_token(raw: str) -> dict[str, Any]:
    try:
        key = jwks().get_signing_key_from_jwt(raw)
        return jwt.decode(raw, key.key, algorithms=["RS256", "PS256"], audience=AUDIENCE, issuer=ISSUER)
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="invalid_access_token") from exc


def principal(request: Request, x_tenant: str | None = Header(default=None)) -> Principal:
    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="bearer_token_required")
    claims = decode_token(authorization[7:])
    tenant = str(claims.get("organization_id", ""))
    if not tenant or not x_tenant or x_tenant != tenant:
        raise HTTPException(status_code=403, detail="tenant_denied")
    roles = set(claims.get("mail_roles", []))
    if "codestra_mail_user" not in roles and not roles.intersection({"codestra_mail_admin", "codestra_mail_owner"}):
        raise HTTPException(status_code=403, detail="mail_role_required")
    return Principal(subject=claims["sub"], email=claims.get("email", ""), tenant=tenant,
                     scopes=set(str(claims.get("scope", "")).split()), roles=roles)


def require_scope(name: str):
    def dependency(value: Principal = Depends(principal)) -> Principal:
        if name not in value.scopes:
            raise HTTPException(status_code=403, detail="scope_denied")
        return value
    return dependency


app = FastAPI(title="Codestra Mail Control Plane", version="1.0.0")


def registry() -> MailRegistry:
    value = MailRegistry(DATABASE)
    value.migrate()
    return value


def actor(reg: MailRegistry, subject: str) -> str:
    row = reg.db.execute("SELECT mail_user_uuid FROM mail_user WHERE keycloak_subject=? AND active=1", (subject,)).fetchone()
    if not row:
        raise HTTPException(status_code=403, detail="mailbox_not_provisioned")
    return row[0]


@app.get("/healthz/ready")
def ready() -> dict[str, str]:
    reg = registry()
    result = reg.db.execute("PRAGMA integrity_check").fetchone()[0]
    if result != "ok":
        raise HTTPException(status_code=503, detail="registry_unhealthy")
    return {"status": "ready"}


@app.get("/api/v1/mail/messages")
def list_messages(value: Principal = Depends(require_scope("mail.read"))) -> list[dict[str, Any]]:
    reg = registry(); user_id = actor(reg, value.subject)
    rows = reg.messages_for_user(tenant=value.tenant, mail_user_uuid=user_id)
    return [dict(row) for row in rows]


@app.post("/api/v1/mail/messages", status_code=status.HTTP_202_ACCEPTED)
def create_message(command: MessageCommand, value: Principal = Depends(require_scope("mail.send"))) -> dict[str, Any]:
    reg = registry(); user_id = actor(reg, value.subject)
    try:
        message = reg.register_message(tenant=value.tenant, direction="OUTBOUND", sender=command.sender,
            recipients=command.recipients, correlation_id=command.correlation_id,
            idempotency_key=command.idempotency_key, message_id=command.message_id,
            in_reply_to=command.in_reply_to, references=command.references, actor_uuid=user_id)
    except PolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"message_uuid": message["message_uuid"], "thread_uuid": message["thread_uuid"],
            "state": message["actual_state"], "duplicate": message["duplicate"]}


@app.get("/api/v1/mail/messages/{message_uuid}")
def get_message(message_uuid: str, value: Principal = Depends(require_scope("mail.read"))) -> dict[str, Any]:
    reg = registry(); user_id = actor(reg, value.subject)
    rows = reg.messages_for_user(tenant=value.tenant, mail_user_uuid=user_id, message_uuid=message_uuid)
    if not rows:
        raise HTTPException(status_code=404, detail="message_not_found")
    return dict(rows[0])


@app.get("/api/v1/mail/mailboxes")
def list_mailboxes(value: Principal = Depends(require_scope("mailbox.manage.self"))) -> list[dict[str, Any]]:
    reg = registry(); user_id = actor(reg, value.subject); user = dict(reg._user(user_id))
    shared = reg.db.execute("""SELECT s.mailbox_uuid,s.address,s.campaign_id,m.permission FROM shared_mailbox s
        JOIN shared_mailbox_member m USING(mailbox_uuid) WHERE m.mail_user_uuid=? AND s.active=1""", (user_id,)).fetchall()
    return [{"mailbox_uuid": user_id, "address": user["primary_address"], "campaign_id": user["campaign_id"], "permission": "OWNER"},
            *[dict(row) for row in shared]]


@app.get("/api/v1/admin/mail/domain-mappings")
def domain_mappings(value: Principal = Depends(require_scope("mail.admin"))) -> list[dict[str, Any]]:
    if not value.roles.intersection({"codestra_mail_admin", "codestra_mail_owner"}):
        raise HTTPException(status_code=403, detail="admin_role_required")
    reg = registry()
    return [dict(row) for row in reg.db.execute("SELECT * FROM mail_domain ORDER BY domain")]


@app.exception_handler(sqlite3.IntegrityError)
def integrity_error(_: Request, exc: sqlite3.IntegrityError):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=409, content={"detail": "registry_conflict"})
