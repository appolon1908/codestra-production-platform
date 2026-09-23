from pathlib import Path


SOURCE = Path("operations/caddy/telnexa-events.caddy").read_text()


def test_telnexa_callback_receiver_is_private_mtls_and_exact_route_scoped() -> None:
    assert "bind 10.40.0.1" in SOURCE
    assert "mode require_and_verify" in SOURCE
    assert (
        "trust_pool file /etc/caddy/private/telnexa-events/"
        "telnexa-callback-client.crt"
    ) in SOURCE
    assert "remote_ip 10.40.0.4" in SOURCE
    assert "method POST" in SOURCE
    assert "path /api/v1/events/telnexa" in SOURCE


def test_telnexa_callback_receiver_uses_host_loopback_upstream_only() -> None:
    assert "reverse_proxy 127.0.0.1:18112" in SOURCE
    assert "respond \"Forbidden\" 403" in SOURCE


def test_telnexa_callback_receiver_redacts_authentication_material() -> None:
    for header in (
        "Authorization",
        "Cookie",
        "Idempotency-Key",
        "X-Signature",
        "X-Event-Id",
    ):
        assert f"request>headers>{header} delete" in SOURCE


def test_telnexa_callback_receiver_is_not_imported_by_container_caddy() -> None:
    root = Path("operations/caddy/Caddyfile").read_text()
    assert "import telnexa-events.caddy" not in root
    assert "Host-Caddy-only" in SOURCE



def test_telnexa_callback_client_identity_is_declared_in_pki_inventory() -> None:
    manifest = Path("operations/tls/certificates.tsv").read_text()
    row = next(
        line for line in manifest.splitlines()
        if line.startswith("telnexa-callback-client|")
    )
    fields = row.split("|")
    assert fields[1] == "client"
    assert fields[2] == "/etc/codestra/pki/telnexa-callback-client/client.crt"
    assert fields[3] == "/etc/codestra/pki/telnexa-callback-client/client.key"
    assert fields[4] == "/etc/codestra/pki/private-integration-ca/ca.crt"
    assert fields[5] == "/etc/codestra/pki/private-integration-ca/ca.key"
    assert fields[8] == "URI:spiffe://codestra/internal/telnexa/callback"
