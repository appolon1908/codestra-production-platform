from pathlib import Path


ROOT = Path(__file__).parents[1]
SECURITY = (ROOT / "operations/caddy/snippets/security.caddy").read_text()
PROXY = (ROOT / "operations/caddy/snippets/proxy-common.caddy").read_text()
SYSTEMD = (
    ROOT / "operations/systemd/caddy.service.d/production-hardening.conf"
).read_text()
CERTIFIER = (ROOT / "operations/caddy/certify-caddy-production.sh").read_text()


def test_security_headers_hide_server_identity():
    assert "\t\t-Server" in SECURITY
    assert "Strict-Transport-Security" in SECURITY
    assert "X-Content-Type-Options nosniff" in SECURITY


def test_proxy_common_does_not_override_caddy_forwarded_proto():
    assert "X-Real-IP" in PROXY
    assert "X-Forwarded-Proto" not in PROXY


def test_caddy_service_restarts_and_is_sandboxed():
    assert "Restart=on-failure" in SYSTEMD
    assert "UMask=0027" in SYSTEMD
    assert "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6" in SYSTEMD
    assert "ProtectProc=invisible" in SYSTEMD


def test_certifier_uses_adapted_hosts_and_internal_hour_threshold():
    assert "caddy adapt" in CERTIFIER
    assert ".. | objects | .host? // empty" in CERTIFIER
    assert "INTERNAL_MIN_HOURS" in CERTIFIER
    assert "api.staging.internal.codestra.agency" in CERTIFIER
    assert "grep -RhoE" not in CERTIFIER
