"""Production adapters for campaign mailbox provisioning.

All calls use a dedicated mTLS identity plus a short-lived, tenant-bound
Keycloak service token. Provider credentials never cross this boundary.
"""
from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .core import ControlPlaneError


CANONICAL_ISSUER = "https://auth.codestra.co/realms/codestra"
KLYROW_PRIVATE_ENDPOINT = "https://10.40.0.4:18000"
ODOO_PRIVATE_ENDPOINT = "https://10.40.0.1:8443"
FORBIDDEN_AGENT_MAIL_ROLES = {"email-admin", "codestra-email-admin", "mail-admin"}


def _private_file(path: str) -> str:
    try:
        info = os.stat(path, follow_symlinks=False)
        if not os.path.isfile(path) or info.st_mode & 0o077:
            raise ControlPlaneError("adapter_secret_file_permissions_invalid")
        value = Path(path).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ControlPlaneError("adapter_secret_file_unavailable") from exc
    if not value:
        raise ControlPlaneError("adapter_secret_file_empty")
    return value


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ARG002
        raise ControlPlaneError("adapter_redirect_denied")


class MtlsJsonClient:
    def __init__(self, *, ca_file: str, cert_file: str, key_file: str, timeout: int = 10):
        if not all((ca_file, cert_file, key_file)):
            raise ControlPlaneError("adapter_mtls_identity_required")
        context = ssl.create_default_context(cafile=ca_file)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(cert_file, key_file)
        self.opener = urllib.request.build_opener(
            NoRedirect(), urllib.request.HTTPSHandler(context=context)
        )
        self.timeout = timeout

    def request(self, method: str, url: str, *, token: str, body: Any = None,
                headers: dict[str, str] | None = None, expected=(200, 201, 202, 204)) -> Any:
        payload = None if body is None else json.dumps(
            body, sort_keys=True, separators=(",", ":")
        ).encode()
        request_headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            **(headers or {}),
        }
        request = urllib.request.Request(url, data=payload, method=method, headers=request_headers)
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read(1_048_577)
                if response.status not in expected:
                    raise ControlPlaneError(f"adapter_http_{response.status}")
                if len(raw) > 1_048_576:
                    raise ControlPlaneError("adapter_response_too_large")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            if exc.code == 409:
                raise ControlPlaneError("adapter_idempotency_conflict") from exc
            raise ControlPlaneError(f"adapter_http_{exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise ControlPlaneError("adapter_request_failed") from exc


class ServiceTokenProvider:
    def __init__(self, client: MtlsJsonClient, *, issuer: str, client_id: str,
                 client_secret_file: str, audience: str, scopes: tuple[str, ...]):
        if issuer.rstrip("/") != CANONICAL_ISSUER:
            raise ControlPlaneError("noncanonical_keycloak_issuer")
        if not client_id or not audience or not scopes:
            raise ControlPlaneError("service_identity_policy_incomplete")
        self.client, self.issuer, self.client_id = client, issuer.rstrip("/"), client_id
        self.secret_file, self.audience, self.scopes = client_secret_file, audience, scopes
        self._tokens: dict[str, tuple[str, float]] = {}

    def token(self, tenant_id: str) -> str:
        if not tenant_id or len(tenant_id) > 64:
            raise ControlPlaneError("invalid_tenant")
        cached_token, cached_expiry = self._tokens.get(tenant_id, ("", 0.0))
        if cached_token and time.time() < cached_expiry - 30:
            return cached_token
        form = urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": _private_file(self.secret_file),
            "scope": " ".join(self.scopes),
            "audience": self.audience,
            "tenant_id": tenant_id,
        }).encode()
        request = urllib.request.Request(
            f"{self.issuer}/protocol/openid-connect/token",
            data=form,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with self.client.opener.open(request, timeout=self.client.timeout) as response:
                value = json.loads(response.read(65537))
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as exc:
            raise ControlPlaneError("service_token_unavailable") from exc
        token, expires = str(value.get("access_token") or ""), int(value.get("expires_in") or 0)
        if not token or not 30 <= expires <= 900:
            raise ControlPlaneError("invalid_service_token_response")
        self._tokens[tenant_id] = (token, time.time() + expires)
        return token


class KeycloakIdentityAdapter:
    def __init__(self, client: MtlsJsonClient, tokens: ServiceTokenProvider):
        self.client, self.tokens = client, tokens
        self.base = f"{CANONICAL_ISSUER.rsplit('/realms/', 1)[0]}/admin/realms/codestra"

    def _call(self, command, method, path, body=None, expected=(200, 201, 204)):
        return self.client.request(
            method, self.base + path, token=self.tokens.token(command["tenant_id"]),
            body=body, headers={"X-Codestra-Tenant": command["tenant_id"],
                                "X-Correlation-ID": command["correlation_id"]}, expected=expected,
        )

    def reconcile(self, command: dict[str, Any]) -> dict[str, Any]:
        user_id = str(command.get("keycloak_user_id") or "").strip()
        if not user_id:
            raise ControlPlaneError("authoritative_keycloak_subject_required")
        user = self._call(command, "GET", f"/users/{urllib.parse.quote(user_id)}")
        if user.get("id") != user_id or user.get("enabled") is not True:
            raise ControlPlaneError("keycloak_identity_readback_failed")
        roles = [self._call(command, "GET", f"/roles/{urllib.parse.quote(role)}")
                 for role in command["roles"]]
        self._call(command, "POST", f"/users/{user_id}/role-mappings/realm", roles, expected=(204,))
        effective = self._call(command, "GET", f"/users/{user_id}/role-mappings/realm/composite")
        names = {str(role.get("name")) for role in effective}
        if not set(command["roles"]).issubset(names) or names & FORBIDDEN_AGENT_MAIL_ROLES:
            raise ControlPlaneError("keycloak_grant_readback_failed")
        return {"user_id": user_id}

    def revoke_mailbox_grants(self, command: dict[str, Any]) -> None:
        user_id = str(command.get("keycloak_user_id") or "").strip()
        if not user_id:
            raise ControlPlaneError("authoritative_keycloak_subject_required")
        user = self._call(command, "GET", f"/users/{urllib.parse.quote(user_id)}")
        if user.get("id") != user_id:
            raise ControlPlaneError("keycloak_identity_readback_failed")
        roles = [self._call(command, "GET", f"/roles/{urllib.parse.quote(role)}")
                 for role in command["roles"]]
        self._call(
            command, "DELETE", f"/users/{user_id}/role-mappings/realm",
            roles, expected=(204,),
        )
        effective = self._call(command, "GET", f"/users/{user_id}/role-mappings/realm/composite")
        if set(command["roles"]) & {str(role.get("name")) for role in effective}:
            raise ControlPlaneError("keycloak_grant_revocation_readback_failed")


class KlyrowMailboxAdapter:
    def __init__(self, client: MtlsJsonClient, tokens: ServiceTokenProvider,
                 base_url: str = KLYROW_PRIVATE_ENDPOINT):
        if base_url.rstrip("/") != KLYROW_PRIVATE_ENDPOINT:
            raise ControlPlaneError("unapproved_klyrow_endpoint")
        self.client, self.tokens, self.base = client, tokens, base_url.rstrip("/")

    def _call(self, command, method, path, body=None, expected=(200, 201, 202, 204)):
        return self.client.request(
            method, self.base + path, token=self.tokens.token(command["tenant_id"]),
            body=body, headers={"X-Klyrow-Tenant-ID": command["tenant_id"],
                                "X-Correlation-ID": command["correlation_id"],
                                "Idempotency-Key": command["idempotency_key"]}, expected=expected,
        )

    def provision_identity(self, command):
        return self._call(command, "PUT", f"/v1/email/mailboxes/{urllib.parse.quote(command['primary_email'])}", command)

    def provision_inbound_route(self, command):
        return self._call(command, "PUT", f"/v1/email/inbound-routes/{urllib.parse.quote(command['primary_email'])}", {
            **command, "match": "EXACT", "catch_all": False,
        })

    def authorize_sender(self, command):
        return self._call(command, "PUT", f"/v1/email/sender-authorizations/{urllib.parse.quote(command['primary_email'])}", command)

    def validate_send_path(self, command):
        value = self._call(command, "POST", "/v1/email/validations/outbound", command)
        return value.get("authorized") is True and value.get("external_delivery") is False

    def validate_inbound_route(self, command):
        value = self._call(command, "POST", "/v1/email/validations/inbound", command)
        return value.get("matched") is True and value.get("match") == "EXACT"

    def destination_readback(self, command):
        address = urllib.parse.quote(command["primary_email"])
        mailbox = self._call(command, "GET", f"/v1/email/mailboxes/{address}")
        route = self._call(command, "GET", f"/v1/email/inbound-routes/{address}")
        sender = self._call(command, "GET", f"/v1/email/sender-authorizations/{address}")
        return (
            mailbox.get("primary_email") == command["primary_email"]
            and mailbox.get("tenant_id") == command["tenant_id"]
            and mailbox.get("campaign_id") == command["campaign_id"]
            and mailbox.get("agent_id") == command["agent_id"]
            and route.get("recipient") == command["primary_email"]
            and route.get("match") == "EXACT" and route.get("catch_all") is False
            and sender.get("from_address") == command["primary_email"]
            and sender.get("authorized") is True
        )

    def disable(self, command: dict[str, Any]) -> None:
        self._call(
            command, "POST",
            f"/v1/email/mailboxes/{urllib.parse.quote(command['primary_email'])}/suspend",
            {"reason": "agent_lifecycle", "sending_enabled": False, "receiving_enabled": False},
        )


class OdooMailboxAdapter:
    def __init__(self, client: MtlsJsonClient, tokens: ServiceTokenProvider,
                 base_url: str = ODOO_PRIVATE_ENDPOINT):
        if base_url.rstrip("/") != ODOO_PRIVATE_ENDPOINT:
            raise ControlPlaneError("unapproved_odoo_endpoint")
        self.client, self.tokens, self.base = client, tokens, base_url.rstrip("/")

    def write_mailbox(self, command: dict[str, Any]) -> None:
        allowed = {
            "mailbox_id", "agent_id", "employee_id", "odoo_user_id", "campaign_id",
            "tenant_id", "primary_email", "mailbox_status", "sending_enabled",
            "receiving_enabled", "quota", "rate_limit", "correlation_id",
            "idempotency_key", "failure_state_safe",
        }
        projection = {key: value for key, value in command.items() if key in allowed}
        value = self.client.request(
            "PUT", self.base + "/internal/v1/odoo/mailbox-projections",
            token=self.tokens.token(command["tenant_id"]), body=projection,
            headers={"X-Codestra-Tenant": command["tenant_id"],
                     "X-Correlation-ID": command["correlation_id"],
                     "Idempotency-Key": command["idempotency_key"]},
        )
        if (value.get("tenant_id") != command["tenant_id"]
                or value.get("primary_email") != command["primary_email"]
                or value.get("mailbox_id") != command["mailbox_id"]
                or value.get("mailbox_status") != command["mailbox_status"]):
            raise ControlPlaneError("odoo_projection_readback_mismatch")
