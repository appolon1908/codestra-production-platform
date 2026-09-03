from pathlib import Path


SOURCE = Path("operations/caddy/klyrow-events.caddy").read_text()


def test_klyrow_receiver_is_private_mtls_and_method_scoped() -> None:
    assert "bind 10.40.0.1" in SOURCE
    assert "mode require_and_verify" in SOURCE
    assert "trust_pool file /etc/caddy/private/klyrow-events/klyrow-client.crt" in SOURCE
    assert "remote_ip 10.40.0.4" in SOURCE
    assert "method POST" in SOURCE
    assert "path /internal/provider-events/klyrow" in SOURCE


def test_klyrow_receiver_uses_only_loopback_application_upstream() -> None:
    assert "reverse_proxy 127.0.0.1:18181" in SOURCE
    assert "reverse_proxy http" not in SOURCE
    assert "respond \"Forbidden\" 403" in SOURCE


def test_klyrow_receiver_redacts_authentication_material() -> None:
    for header in (
        "Authorization",
        "Cookie",
        "X-Api-Key",
        "X-Signature",
        "X-Klyrow-Signature",
    ):
        assert f"request>headers>{header} delete" in SOURCE
