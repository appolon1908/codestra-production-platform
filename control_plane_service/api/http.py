from __future__ import annotations

import json
from collections.abc import Collection
from typing import BinaryIO, Protocol

from ..core import ControlPlaneError


class HeaderLookup(Protocol):
    def get(self, name: str, default: str = "") -> str | None: ...


class ResponseTransport(Protocol):
    wfile: BinaryIO

    def send_response(self, code: int) -> None: ...

    def send_header(self, name: str, value: str) -> None: ...

    def end_headers(self) -> None: ...


def write_json_response(
    transport: ResponseTransport,
    code: int,
    value: object,
    *,
    origin: str = "",
    allowed_origins: Collection[str] = (),
) -> None:
    """Write the existing compact JSON response contract without adding policy."""
    raw = json.dumps(value, separators=(",", ":")).encode()
    transport.send_response(code)
    transport.send_header("Content-Type", "application/json")
    transport.send_header("Content-Length", str(len(raw)))
    if origin in allowed_origins:
        transport.send_header("Access-Control-Allow-Origin", origin)
        transport.send_header("Vary", "Origin")
    transport.end_headers()
    transport.wfile.write(raw)


def read_request_body(
    headers: HeaderLookup,
    stream: BinaryIO,
    maximum: int,
) -> bytes:
    """Read one bounded request body using the legacy fail-closed size contract."""
    length = int(headers.get("Content-Length", "0") or "0")
    if length < 1 or length > maximum:
        raise ControlPlaneError("invalid_body_size")
    return stream.read(length)


def is_form_preflight_allowed(
    origin: str,
    path: str,
    allowed_origins: Collection[str],
) -> bool:
    return origin in allowed_origins and path.startswith("/v1/forms/")


def write_form_preflight(transport: ResponseTransport, origin: str) -> None:
    transport.send_response(204)
    transport.send_header("Access-Control-Allow-Origin", origin)
    transport.send_header("Vary", "Origin")
    transport.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
    transport.send_header(
        "Access-Control-Allow-Headers",
        "Content-Type, Idempotency-Key, X-Correlation-ID",
    )
    transport.send_header("Access-Control-Max-Age", "600")
    transport.end_headers()
