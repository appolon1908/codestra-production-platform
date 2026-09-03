#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    value = path.read_text(encoding="utf-8")
    if value.count(old) != 1:
        raise SystemExit(f"{path}: expected one replacement for {old[:80]!r}")
    path.write_text(value.replace(old, new), encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: apply_pr223_redirect_fix.py TARGET_ROOT")
    root = Path(sys.argv[1]).resolve()
    gateway = root / "services/private-integration-gateway/gateway.py"
    tests = root / "tests/test_private_integration_gateway.py"

    replace_once(
        gateway,
        '''def validate_outbound(
    payload: dict[str, Any], now_utc: float
) -> tuple[str, str, str, str, str | None]:
    authorization = validate_outbound_authorization(payload, now_utc)
    return (
        authorization.customer_id,
        authorization.sender,
        authorization.destination,
        authorization.route,
        authorization.correlation_id,
    )


class Gateway:
''',
        '''def validate_outbound(
    payload: dict[str, Any], now_utc: float
) -> tuple[str, str, str, str, str | None]:
    authorization = validate_outbound_authorization(payload, now_utc)
    return (
        authorization.customer_id,
        authorization.sender,
        authorization.destination,
        authorization.route,
        authorization.correlation_id,
    )


class RejectMiddlewareRedirects(urllib.request.HTTPRedirectHandler):
    """Fail closed before urllib can replay credentials to a redirect target."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        del newurl
        raise urllib.error.HTTPError(
            req.full_url,
            code,
            "middleware forwarding redirects are forbidden",
            headers,
            fp,
        )


def open_middleware_request(
    request: urllib.request.Request,
    *,
    timeout: float,
    context: ssl.SSLContext,
):
    """Open exactly one reviewed HTTPS origin with redirects disabled."""

    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=context),
        RejectMiddlewareRedirects(),
    )
    return opener.open(request, timeout=timeout)


class Gateway:
''',
    )
    replace_once(
        gateway,
        '''            # entrypoint always injects a real verified context.
            self.middleware_tls_context = object()

    def jasmin_health(self) -> str:
''',
        '''            # entrypoint always injects a real verified context.
            self.middleware_tls_context = object()

    def open_middleware(self, request: urllib.request.Request, *, timeout: float):
        """Use injected test transport or the production no-redirect opener."""

        if self.middleware_tls_context is None:
            raise RuntimeError("outbound middleware mTLS is unavailable")
        if self.urlopen is not urllib.request.urlopen:
            return self.urlopen(
                request,
                timeout=timeout,
                context=self.middleware_tls_context,
            )
        if not isinstance(self.middleware_tls_context, ssl.SSLContext):
            raise RuntimeError("outbound middleware mTLS context is invalid")
        return open_middleware_request(
            request,
            timeout=timeout,
            context=self.middleware_tls_context,
        )

    def jasmin_health(self) -> str:
''',
    )
    replace_once(
        gateway,
        '''                    if self.middleware_tls_context is None:
                        raise RuntimeError("outbound middleware mTLS is unavailable")
                    with self.urlopen(
                        request,
                        timeout=10,
                        context=self.middleware_tls_context,
                    ) as response:
''',
        '''                    with self.open_middleware(request, timeout=10) as response:
''',
    )

    test_block = '''\n\ndef test_middleware_forwarding_rejects_redirects_before_identity_reuse(\n    tmp_path: Path, monkeypatch: pytest.MonkeyPatch\n) -> None:\n    request = urllib.request.Request(\n        "https://middleware.invalid/v1/events",\n        b"{}",\n        {\n            "Authorization": "Bearer private-test-identity",\n            "X-Signature": "sha256=test-signature",\n        },\n        method="POST",\n    )\n    handler = gateway.RejectMiddlewareRedirects()\n    with pytest.raises(urllib.error.HTTPError, match="redirects are forbidden") as error:\n        handler.redirect_request(\n            request,\n            BytesIO(b"redirect body"),\n            307,\n            "Temporary Redirect",\n            {"Location": "https://attacker.invalid/capture"},\n            "https://attacker.invalid/capture",\n        )\n    assert error.value.url == "https://middleware.invalid/v1/events"\n\n    captured = {}\n\n    class Response:\n        status = 202\n\n        def __enter__(self):\n            return self\n\n        def __exit__(self, *_args):\n            return None\n\n    class Opener:\n        def open(self, supplied, *, timeout):\n            captured["request"] = supplied\n            captured["timeout"] = timeout\n            return Response()\n\n    def build_opener(*handlers):\n        captured["handlers"] = handlers\n        return Opener()\n\n    monkeypatch.setattr(gateway.urllib.request, "build_opener", build_opener)\n    context = gateway.ssl.create_default_context()\n    response = gateway.open_middleware_request(request, timeout=10, context=context)\n    assert response.status == 202\n    assert captured["request"] is request\n    assert captured["timeout"] == 10\n    assert any(\n        isinstance(item, gateway.RejectMiddlewareRedirects)\n        for item in captured["handlers"]\n    )\n    https_handlers = [\n        item\n        for item in captured["handlers"]\n        if isinstance(item, gateway.urllib.request.HTTPSHandler)\n    ]\n    assert len(https_handlers) == 1\n    assert https_handlers[0]._context is context\n'''
    value = tests.read_text(encoding="utf-8")
    if "test_middleware_forwarding_rejects_redirects_before_identity_reuse" in value:
        raise SystemExit("redirect regression already exists")
    tests.write_text(value + test_block, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
