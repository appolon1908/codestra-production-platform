from __future__ import annotations

import os
from http.server import ThreadingHTTPServer
from urllib.parse import urlparse

from .api.auth import resolve_operator
from .api.http import (
    is_form_preflight_allowed,
    read_request_body,
    write_form_preflight,
    write_json_response,
)
from .forms import ORIGINS
from .server import MAX_BODY, Handler as LegacyHandler, operator, verifier


class ApplicationHandler(LegacyHandler):
    """Compatibility entrypoint with shared HTTP and auth behavior extracted."""

    def send_json(self, code: int, value: object, origin: str = "") -> None:
        write_json_response(
            self,
            code,
            value,
            origin=origin,
            allowed_origins=ORIGINS,
        )

    def body(self, maximum: int = MAX_BODY) -> bytes:
        return read_request_body(self.headers, self.rfile, maximum)

    def do_OPTIONS(self) -> None:
        origin = self.headers.get("Origin", "")
        path = urlparse(self.path).path
        if not is_form_preflight_allowed(origin, path, ORIGINS):
            return self.send_json(403, {"error": "origin_denied"})
        write_form_preflight(self, origin)

    def auth_operator(self, roles: set[str]) -> tuple[str, str, str | None] | None:
        resolution = resolve_operator(
            self.headers,
            self.client_address[0],
            roles,
            trusted_proxy_cidrs=os.getenv("CONTROL_PLANE_TRUSTED_PROXY_CIDRS", ""),
            gateway_verifier=verifier("KONG_GATEWAY_SHARED_SECRET"),
            fallback_operator=operator,
        )
        if not resolution.authorized:
            self.send_json(403, {"error": resolution.error or "forbidden"})
            return None
        return resolution.identity


def main() -> None:
    address = (
        os.getenv("CONTROL_PLANE_BIND", "127.0.0.1"),
        int(os.getenv("CONTROL_PLANE_PORT", "8096")),
    )
    ThreadingHTTPServer(address, ApplicationHandler).serve_forever()


if __name__ == "__main__":
    main()
