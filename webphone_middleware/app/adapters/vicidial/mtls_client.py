from __future__ import annotations

import json
import logging
import socket
import ssl
from ipaddress import ip_address
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from app.core.config import Settings, VICIDIAL_PRIVATE_HOSTS, VICIDIAL_PRIVATE_PORT


LOGGER = logging.getLogger("codestra.vicidial_mtls")
MAX_PAYLOAD_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 64 * 1024
CONNECT_TIMEOUT_SECONDS = 3.0
RESPONSE_TIMEOUT_SECONDS = 8.0

APPROVED_ROUTES = frozenset(
    {
        (
            "POST",
            "authorization.internal.codestra.agency",
            "/api/v1/transfers/authorize",
        ),
        ("POST", "edge.internal.codestra.agency", "/v1/transfers/execute"),
    }
)


class VicidialMtlsError(RuntimeError):
    """A secret-safe, fail-closed VICIdial transport error."""


class VicidialMtlsClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
        resolver: Callable[[str], Sequence[str]] | None = None,
    ):
        self._settings = settings
        self._resolver = resolver or self._resolve_addresses
        self._ensure_configured()
        ssl_context = self._build_ssl_context()
        if transport is None:
            transport = httpx.HTTPTransport(verify=ssl_context, retries=0)
        self._client = httpx.Client(
            transport=transport,
            timeout=httpx.Timeout(
                connect=CONNECT_TIMEOUT_SECONDS,
                read=RESPONSE_TIMEOUT_SECONDS,
                write=RESPONSE_TIMEOUT_SECONDS,
                pool=CONNECT_TIMEOUT_SECONDS,
            ),
            follow_redirects=False,
            trust_env=False,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> VicidialMtlsClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def authorize(
        self,
        payload: Mapping[str, Any],
        *,
        correlation_id: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        if (
            not self._settings.transfer_control_enabled
            or not self._settings.vicidial_read_enabled
        ):
            raise VicidialMtlsError("VICidial authorization is disabled")
        return self.request(
            "POST",
            f"{self._settings.vicidial_authorization_url}/api/v1/transfers/authorize",
            payload,
            correlation_id=correlation_id,
            request_id=request_id,
        )

    def execute(
        self,
        payload: Mapping[str, Any],
        *,
        correlation_id: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        if not (
            self._settings.transfer_control_enabled
            and self._settings.vicidial_write_enabled
            and self._settings.live_writes_enabled
        ):
            raise VicidialMtlsError("VICIdial transfer execution is disabled")
        return self.request(
            "POST",
            f"{self._settings.vicidial_edge_url}/v1/transfers/execute",
            payload,
            correlation_id=correlation_id,
            request_id=request_id,
        )

    def request(
        self,
        method: str,
        url: str,
        payload: Mapping[str, Any],
        *,
        correlation_id: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        parsed = urlsplit(url)
        route = (method.upper(), parsed.hostname or "", parsed.path)
        if (
            route not in APPROVED_ROUTES
            or parsed.scheme != "https"
            or parsed.port != VICIDIAL_PRIVATE_PORT
            or parsed.hostname not in VICIDIAL_PRIVATE_HOSTS
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise VicidialMtlsError("VICIdial method or route is not approved")
        self._assert_private_resolution(parsed.hostname)

        try:
            body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode(
                "utf-8"
            )
        except (TypeError, ValueError) as exc:
            raise VicidialMtlsError(
                "VICIdial payload is not JSON serializable"
            ) from exc
        if len(body) > MAX_PAYLOAD_BYTES:
            raise VicidialMtlsError("VICidial payload exceeds the configured limit")

        correlation = correlation_id or str(uuid4())
        request = request_id or str(uuid4())
        LOGGER.info(
            "vicidial_request_started",
            extra={
                "correlation_id": correlation,
                "request_id": request,
                "route": parsed.path,
            },
        )
        try:
            with self._client.stream(
                "POST",
                url,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Correlation-ID": correlation,
                    "X-Request-ID": request,
                },
            ) as response:
                response.raise_for_status()
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_RESPONSE_BYTES:
                        raise VicidialMtlsError(
                            "VICidial response exceeds the configured limit"
                        )
                    chunks.append(chunk)
        except VicidialMtlsError:
            raise
        except (
            httpx.TimeoutException,
            httpx.NetworkError,
            httpx.HTTPStatusError,
        ) as exc:
            LOGGER.warning(
                "vicidial_request_failed",
                extra={
                    "correlation_id": correlation,
                    "request_id": request,
                    "route": parsed.path,
                    "error_type": type(exc).__name__,
                },
            )
            raise VicidialMtlsError("VICidial private request failed closed") from exc

        try:
            decoded = json.loads(b"".join(chunks))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise VicidialMtlsError("VICidial response is not valid JSON") from exc
        if not isinstance(decoded, dict):
            raise VicidialMtlsError("VICidial response must be a JSON object")
        LOGGER.info(
            "vicidial_request_completed",
            extra={
                "correlation_id": correlation,
                "request_id": request,
                "route": parsed.path,
                "status_code": response.status_code,
            },
        )
        return decoded

    def _ensure_configured(self) -> None:
        if not self._settings.vicidial_mtls_configured:
            raise VicidialMtlsError("VICidial private mTLS is not configured")

    def _build_ssl_context(self) -> ssl.SSLContext:
        ca_file = self._required_file(self._settings.vicidial_ca_file, "CA bundle")
        cert_file = self._required_file(
            self._settings.vicidial_client_cert_file, "client certificate"
        )
        key_file = self._required_file(
            self._settings.vicidial_client_key_file, "client key"
        )
        try:
            context = ssl.create_default_context(
                ssl.Purpose.SERVER_AUTH, cafile=str(ca_file)
            )
            context.check_hostname = True
            context.verify_mode = ssl.CERT_REQUIRED
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(certfile=str(cert_file), keyfile=str(key_file))
            if self._settings.vicidial_crl_file:
                crl_file = self._required_file(self._settings.vicidial_crl_file, "CRL")
                context.load_verify_locations(cafile=str(crl_file))
                context.verify_flags |= ssl.VERIFY_CRL_CHECK_CHAIN
            return context
        except (OSError, ssl.SSLError) as exc:
            raise VicidialMtlsError(
                "VICidial mTLS credentials are invalid or unreadable"
            ) from exc

    @staticmethod
    def _required_file(value: str, label: str) -> Path:
        path = Path(value)
        if not path.is_file():
            raise VicidialMtlsError(f"VICidial {label} is missing")
        return path

    def _assert_private_resolution(self, hostname: str) -> None:
        try:
            addresses = self._resolver(hostname)
            parsed = [ip_address(address) for address in addresses]
        except (OSError, ValueError) as exc:
            raise VicidialMtlsError(
                "VICidial private DNS resolution failed closed"
            ) from exc
        if not parsed or any(not address.is_private for address in parsed):
            raise VicidialMtlsError(
                "VICidial hostname did not resolve exclusively to the private IP"
            )

    @staticmethod
    def _resolve_addresses(hostname: str) -> list[str]:
        return sorted(
            {
                str(result[4][0])
                for result in socket.getaddrinfo(
                    hostname,
                    VICIDIAL_PRIVATE_PORT,
                    family=socket.AF_INET,
                    type=socket.SOCK_STREAM,
                )
            }
        )
