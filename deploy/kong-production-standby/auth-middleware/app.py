from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from pathlib import Path

import jwt
import psycopg
from fastapi import FastAPI, Header, HTTPException, Request
from jwt import PyJWKClient

ISSUER = "https://auth.codestra.agency/realms/codestra"
AUDIENCE = "codestra-api"
JWKS = ISSUER + "/protocol/openid-connect/certs"
DATABASE_URL = Path(os.environ["DATABASE_URL_FILE"]).read_text().strip()
HMAC_KEY = Path(os.environ["WEBHOOK_HMAC_FILE"]).read_bytes().strip()
TRUSTED_HEADERS = {"x-codestra-subject", "x-codestra-tenant", "x-codestra-roles", "x-codestra-scopes", "x-authenticated-user"}
SCOPES = {"sms": "sms.send", "email": "email.send"}
jwks = PyJWKClient(JWKS, cache_keys=True, lifespan=300)
idempotency: dict[tuple[str, str, str], tuple[str, dict]] = {}
replays: dict[str, int] = {}
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


def deny(code: int, reason: str):
    raise HTTPException(code, reason)


def identity(request: Request, required_scope: str) -> dict:
    if any(name in request.headers for name in TRUSTED_HEADERS):
        deny(403, "spoofed_identity_header")
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        deny(401, "missing_token")
    token = auth[7:]
    try:
        header = jwt.get_unverified_header(token)
        if header.get("alg") != "RS256" or not header.get("kid"):
            deny(401, "algorithm_or_kid_denied")
        claims = jwt.decode(token, jwks.get_signing_key_from_jwt(token).key,
                            algorithms=["RS256"], issuer=ISSUER, audience=AUDIENCE,
                            options={"require": ["iss", "aud", "sub", "iat", "exp"]}, leeway=0)
    except HTTPException:
        raise
    except Exception:
        deny(401, "invalid_token")
    scopes = set(str(claims.get("scope", "")).split())
    if required_scope not in scopes:
        deny(403, "scope_denied")
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute("SELECT tenant_key,status,allowed_scopes FROM oidc_tenant_registry WHERE issuer=%s AND subject=%s", (ISSUER, claims["sub"]))
        row = cur.fetchone()
    if not row or row[1] != "active" or required_scope not in set(row[2] or []):
        deny(403, "identity_or_scope_unmapped")
    return {"subject": claims["sub"], "tenant": row[0], "scope": required_scope}


@app.get("/health")
def health():
    return {"status": "healthy", "mode": "mock-only", "external_actions": False}


@app.post("/v1/{family}")
async def command(family: str, request: Request, idempotency_key: str | None = Header(None)):
    if family not in SCOPES:
        deny(404, "not_found")
    if not idempotency_key or len(idempotency_key) > 128:
        deny(400, "idempotency_key_required")
    context = identity(request, SCOPES[family])
    body = await request.body()
    if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
        deny(415, "content_type_denied")
    try:
        payload = json.loads(body)
    except Exception:
        deny(400, "malformed_json")
    if payload.get("tenant") != context["tenant"]:
        deny(404, "tenant_not_found")
    digest = hashlib.sha256(body).hexdigest()
    key = (context["tenant"], family, idempotency_key)
    if key in idempotency:
        if idempotency[key][0] != digest:
            deny(409, "idempotency_conflict")
        return idempotency[key][1]
    result = {"status": "accepted_mock", "external_action": False, "request_digest": digest[:16]}
    idempotency[key] = (digest, result)
    return result


@app.post("/v1/webhooks/{family}")
async def webhook(family: str, request: Request,
                  x_signature_version: str | None = Header(None),
                  x_key_id: str | None = Header(None),
                  x_timestamp: str | None = Header(None),
                  x_event_id: str | None = Header(None),
                  x_signature: str | None = Header(None)):
    if family not in {"sms", "email"}:
        deny(404, "not_found")
    if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
        deny(415, "content_type_denied")
    if x_signature_version != "v1" or not all((x_key_id, x_timestamp, x_event_id, x_signature)):
        deny(401, "signature_missing")
    try:
        timestamp = int(x_timestamp)
    except ValueError:
        deny(401, "timestamp_invalid")
    now = int(time.time())
    if abs(now - timestamp) > 300:
        deny(401, "timestamp_stale")
    if x_event_id in replays and replays[x_event_id] >= now - 300:
        deny(409, "event_replay")
    body = await request.body()
    signed = f"v1.{x_timestamp}.{x_event_id}.".encode() + body
    expected = hmac.new(HMAC_KEY, signed, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, x_signature):
        deny(401, "signature_invalid")
    replays[x_event_id] = now
    return {"status": "accepted_mock", "external_action": False}
