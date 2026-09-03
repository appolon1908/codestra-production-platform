#!/usr/bin/env python3
"""Apply the reviewed PR #223 redirect hardening exactly once."""

from __future__ import annotations

from pathlib import Path


GATEWAY = Path("services/private-integration-gateway/gateway.py")
TESTS = Path("tests/test_private_integration_gateway.py")
README = Path("services/private-integration-gateway/README.md")


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    if source.count(old) != 1:
        raise SystemExit(f"{label}: expected one replacement marker")
    return source.replace(old, new, 1)


def main() -> int:
    gateway = GATEWAY.read_text(encoding="utf-8")
    import_marker = (
        'from typing import Any, Callable\n\n\n'
        'LOG = logging.getLogger("private_integration_gateway")'
    )
    transport_support = '''from typing import Any, Callable


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject redirects before forwarding credentials or client identity."""

    def redirect_request(
        self,
        request,
        file_pointer,
        code,
        message,
        headers,
        new_url,
    ):
        return None


def open_middleware_request(
    request: urllib.request.Request,
    *,
    timeout: float,
    context: ssl.SSLContext | object,
    urlopen: Callable[..., Any] = urllib.request.urlopen,
):
    """Open one middleware request without allowing redirects."""

    if urlopen is not urllib.request.urlopen:
        # Injected transports own their synthetic boundary and retain the
        # production call signature so tests can assert the verified context.
        return urlopen(request, timeout=timeout, context=context)
    opener = urllib.request.build_opener(
        _NoRedirectHandler(),
        urllib.request.HTTPSHandler(context=context),
    )
    return opener.open(request, timeout=timeout)


LOG = logging.getLogger("private_integration_gateway")'''
    gateway = replace_once(
        gateway,
        import_marker,
        transport_support,
        "gateway transport support",
    )

    old_open = '''                    with self.urlopen(
                        request,
                        timeout=10,
                        context=self.middleware_tls_context,
                    ) as response:'''
    new_open = '''                    with open_middleware_request(
                        request,
                        timeout=10,
                        context=self.middleware_tls_context,
                        urlopen=self.urlopen,
                    ) as response:'''
    gateway = replace_once(
        gateway,
        old_open,
        new_open,
        "gateway middleware opener",
    )
    GATEWAY.write_text(gateway, encoding="utf-8")

    tests = TESTS.read_text(encoding="utf-8")
    test_marker = "def test_only_private_jasmin_service_is_accepted(tmp_path: Path):"
    redirect_tests = '''def test_middleware_transport_refuses_redirects_before_presenting_identity(
    monkeypatch: pytest.MonkeyPatch,
):
    handlers = []
    calls = []

    class Response:
        status = 202

    class Opener:
        def open(self, request, timeout):
            calls.append((request, timeout))
            return Response()

    def build_opener(*supplied_handlers):
        handlers.extend(supplied_handlers)
        return Opener()

    monkeypatch.setattr(gateway.urllib.request, "build_opener", build_opener)
    request = urllib.request.Request(
        "https://middleware.invalid/v1/events",
        data=b"{}",
        headers={"Authorization": "Bearer synthetic"},
        method="POST",
    )
    context = gateway.ssl.SSLContext(gateway.ssl.PROTOCOL_TLS_CLIENT)
    response = gateway.open_middleware_request(
        request,
        timeout=10,
        context=context,
        urlopen=gateway.urllib.request.urlopen,
    )

    assert response.status == 202
    assert calls == [(request, 10)]
    assert any(
        isinstance(handler, gateway._NoRedirectHandler)
        for handler in handlers
    )
    assert any(
        isinstance(handler, urllib.request.HTTPSHandler)
        for handler in handlers
    )
    redirect_handler = next(
        handler
        for handler in handlers
        if isinstance(handler, gateway._NoRedirectHandler)
    )
    assert redirect_handler.redirect_request(
        request,
        None,
        302,
        "Found",
        {},
        "https://other.invalid/capture",
    ) is None


def test_only_private_jasmin_service_is_accepted(tmp_path: Path):'''
    tests = replace_once(
        tests,
        test_marker,
        redirect_tests,
        "redirect regression",
    )
    TESTS.write_text(tests, encoding="utf-8")

    readme = README.read_text(encoding="utf-8")
    old_readme = (
        "TLS 1.2-or-newer context at startup and refuses to start forwarding "
        "when the\nCA, certificate, or private key is unavailable."
    )
    new_readme = (
        "TLS 1.2-or-newer context at startup, refuses every HTTP redirect "
        "before\npresenting credentials or the client identity, and refuses "
        "to start forwarding\nwhen the CA, certificate, or private key is "
        "unavailable."
    )
    readme = replace_once(
        readme,
        old_readme,
        new_readme,
        "README redirect boundary",
    )
    README.write_text(readme, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
