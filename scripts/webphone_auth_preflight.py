#!/usr/bin/env python3
"""Check production webphone authentication without creating sessions or calls."""
from __future__ import annotations

import argparse
import json
import stat
from pathlib import Path
from uuid import uuid4

import jwt

CLIENT_ID = "codestra-provisioning-service"
ISSUER = "https://auth.codestra.co/realms/codestra"
TOKEN_URL = ISSUER + "/protocol/openid-connect/token"
JWKS_URL = ISSUER + "/protocol/openid-connect/certs"
PROVISIONING_URL = "https://provisioning-service-production:8443"
SCOPES = {"identity:rotate", "provisioning:execute", "provisioning:read"}
READ_ONLY_ROLES = {"view-users", "query-users", "query-groups"}


class PreflightFailure(Exception):
    def __init__(self, reason, http_status=None):
        self.reason = reason
        self.http_status = http_status
        super().__init__(reason)


def validate_configuration(client_id, token_url, provisioning_url):
    if client_id != CLIENT_ID:
        raise PreflightFailure("production_client_id_mismatch")
    if token_url != TOKEN_URL:
        raise PreflightFailure("canonical_token_url_required")
    if provisioning_url != PROVISIONING_URL:
        raise PreflightFailure("production_provisioning_url_required")


def validate_token(token, jwks):
    try:
        header = jwt.get_unverified_header(token)
        if header.get("alg") != "RS256" or not header.get("kid"):
            raise ValueError("header")
        keys = [key for key in jwks["keys"] if key.get("kid") == header["kid"]
                and key.get("kty") == "RSA" and key.get("use", "sig") == "sig"
                and key.get("alg", "RS256") == "RS256"]
        if len(keys) != 1:
            raise ValueError("signing key")
        claims = jwt.decode(
            token, jwt.PyJWK.from_dict(keys[0]).key, algorithms=["RS256"],
            issuer=ISSUER, audience=CLIENT_ID, leeway=10,
            options={"require": ["iss", "aud", "sub", "exp", "iat", "jti", "azp", "typ"]},
        )
        audiences = claims["aud"] if isinstance(claims["aud"], list) else [claims["aud"]]
        if (audiences != [CLIENT_ID] or claims["azp"] != CLIENT_ID
                or not isinstance(claims["sub"], str) or not claims["sub"]
                or not isinstance(claims["jti"], str) or not claims["jti"]
                or type(claims["iat"]) is not int or type(claims["exp"]) is not int
                or not 0 < claims["exp"] - claims["iat"] <= 300
                or claims["typ"] not in {"Bearer", "at+jwt"}
                or not isinstance(claims.get("codestra_scopes"), str)
                or set(claims["codestra_scopes"].split()) != SCOPES):
            raise ValueError("claims")
        if claims.get("realm_access", {}).get("roles", []):
            raise ValueError("realm roles")
        resources = claims.get("resource_access", {})
        if set(resources) - {"realm-management"}:
            raise ValueError("additional client roles")
        roles = set(resources.get("realm-management", {}).get("roles", []))
        if "view-users" not in roles or not roles <= READ_ONLY_ROLES:
            raise ValueError("user lookup roles")
        return claims
    except (jwt.PyJWTError, ValueError, TypeError, KeyError, AttributeError):
        raise PreflightFailure("production_token_contract_rejected") from None


def response_json(response):
    try:
        return response.json()
    except (ValueError, TypeError):
        raise PreflightFailure("invalid_json_response", response.status_code) from None


def run_preflight(http, client_id, secret, token_url, provisioning_url):
    validate_configuration(client_id, token_url, provisioning_url)
    response = http.post(token_url, data={
        "grant_type": "client_credentials", "client_id": client_id, "client_secret": secret,
    })
    if response.status_code != 200:
        # Never include upstream bodies: they can contain credentials or user data.
        raise PreflightFailure("client_authentication_rejected", response.status_code)
    token = response_json(response).get("access_token")
    if not isinstance(token, str) or not token:
        raise PreflightFailure("access_token_missing")
    response = http.get(JWKS_URL)
    if response.status_code != 200:
        raise PreflightFailure("jwks_unavailable", response.status_code)
    validate_token(token, response_json(response))
    headers = {"Authorization": "Bearer " + token}

    # A random nonexistent user establishes the existing read-only Admin permission
    # without enumerating users or returning a real user's identity.
    response = http.get(
        "https://auth.codestra.co/admin/realms/codestra/users/" + str(uuid4()),
        headers=headers,
    )
    if response.status_code != 404 or response_json(response).get("error") != "User not found":
        raise PreflightFailure("keycloak_user_lookup_not_verified", response.status_code)

    # The GET route requires a RequestEnvelope body. Missing-body validation occurs
    # only after authentication. Pair a 401 control with its authenticated 422;
    # never submit a provisioning command or create a webphone session.
    probe_url = provisioning_url + "/v1/provisioning/requests/" + str(uuid4())
    response = http.get(probe_url)
    if response.status_code != 401:
        raise PreflightFailure("provisioning_authentication_boundary_unverified",
                               response.status_code)
    response = http.get(probe_url, headers=headers)
    detail = response_json(response).get("detail")
    if (response.status_code != 422 or not isinstance(detail, list) or len(detail) != 1
            or detail[0].get("loc") != ["body"]
            or detail[0].get("type") not in {"missing", "value_error.missing"}):
        raise PreflightFailure("provisioning_authenticated_read_not_verified",
                               response.status_code)

    response = http.get(provisioning_url + "/ready")
    if response.status_code != 200:
        raise PreflightFailure("provisioning_readiness_failed", response.status_code)
    ready = response_json(response)
    if (ready.get("status") != "ready" or ready.get("environment") != "production"
            or not isinstance(ready.get("degraded_capabilities"), list)):
        raise PreflightFailure("provisioning_readiness_contract_rejected")
    degraded = ready["degraded_capabilities"]
    return {
        "status": "pass", "machine_authentication": "pass",
        "keycloak_user_lookup": "pass", "provisioning_authenticated_read": "pass",
        "degraded_capabilities": degraded,
        "call_readiness": "not_tested" if not degraded else "blocked",
        "sessions_created": 0, "calls_placed": 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-id")
    parser.add_argument("--secret-file", type=Path)
    args = parser.parse_args()
    try:
        from app.core.config import settings
        import httpx
        client_id = args.client_id or settings.provisioning_service_client_id
        secret_file = args.secret_file or Path(settings.provisioning_service_client_secret_file)
        validate_configuration(client_id, settings.provisioning_service_token_url,
                               settings.provisioning_service_url)
        if not secret_file.exists():
            raise PreflightFailure("production_credential_file_missing")
        file_stat = secret_file.lstat()
        mode = file_stat.st_mode
        if not stat.S_ISREG(mode) or mode & 0o077 or not 0 < file_stat.st_size <= 8192:
            raise PreflightFailure("private_regular_credential_file_required")
        secret = secret_file.read_text().strip()
        if not secret:
            raise PreflightFailure("production_credential_empty")
        with httpx.Client(verify=settings.provisioning_service_ca_file, timeout=15,
                          follow_redirects=False, trust_env=False) as http:
            result = run_preflight(
                http, client_id, secret, settings.provisioning_service_token_url,
                settings.provisioning_service_url)
        print(json.dumps(result, sort_keys=True))
        return 0
    except PreflightFailure as exc:
        print(json.dumps({"status": "blocked", "reason": exc.reason,
                          "http_status": exc.http_status, "calls_placed": 0}))
        return 1
    except Exception:
        # Do not print exception strings: HTTP/config errors can contain secrets.
        print(json.dumps({"status": "blocked", "reason": "preflight_runtime_unavailable",
                          "calls_placed": 0}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
