import logging
import subprocess
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from app.adapters.vicidial.mtls_client import (
    MAX_PAYLOAD_BYTES,
    VicidialMtlsClient,
    VicidialMtlsError,
)
from app.core.config import Settings


AUTH_URL = "https://authorization.internal.codestra.agency:8443"
EDGE_URL = "https://edge.internal.codestra.agency:8443"


def _certificate_files(tmp_path: Path) -> tuple[Path, Path, Path]:
    key = tmp_path / "client.key"
    cert = tmp_path / "client.crt"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=non-production-mtls-test",
            "-keyout",
            str(key),
            "-out",
            str(cert),
        ],
        check=True,
        capture_output=True,
    )
    return cert, cert, key


def _signed_server_certificate(
    tmp_path: Path, *, hostname: str, expired: bool = False
) -> tuple[Path, Path]:
    ca_key = tmp_path / "ca.key"
    ca_cert = tmp_path / "ca.crt"
    server_key = tmp_path / "server.key"
    server_csr = tmp_path / "server.csr"
    server_cert = tmp_path / "server.crt"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "2",
            "-subj",
            "/CN=non-production-test-ca",
            "-keyout",
            str(ca_key),
            "-out",
            str(ca_cert),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "openssl",
            "req",
            "-new",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-subj",
            f"/CN={hostname}",
            "-keyout",
            str(server_key),
            "-out",
            str(server_csr),
        ],
        check=True,
        capture_output=True,
    )
    extension = tmp_path / "server.ext"
    extension.write_text(
        f"subjectAltName=DNS:{hostname}\nextendedKeyUsage=serverAuth\n"
    )
    if not expired:
        subprocess.run(
            [
                "openssl",
                "x509",
                "-req",
                "-in",
                str(server_csr),
                "-CA",
                str(ca_cert),
                "-CAkey",
                str(ca_key),
                "-CAcreateserial",
                "-days",
                "1",
                "-sha256",
                "-extfile",
                str(extension),
                "-out",
                str(server_cert),
            ],
            check=True,
            capture_output=True,
        )
        return ca_cert, server_cert

    (tmp_path / "index.txt").write_text("")
    (tmp_path / "serial").write_text("1000\n")
    (tmp_path / "newcerts").mkdir()
    ca_config = tmp_path / "ca.cnf"
    ca_config.write_text(
        "[ca]\ndefault_ca=local_ca\n[local_ca]\n"
        f"dir={tmp_path}\ndatabase=$dir/index.txt\nnew_certs_dir=$dir/newcerts\n"
        "certificate=$dir/ca.crt\nprivate_key=$dir/ca.key\nserial=$dir/serial\n"
        "default_md=sha256\ndefault_days=1\npolicy=policy\nx509_extensions=server\n"
        "[policy]\ncommonName=supplied\n[server]\nextendedKeyUsage=serverAuth\n"
        f"subjectAltName=DNS:{hostname}\n"
    )
    subprocess.run(
        [
            "openssl",
            "ca",
            "-batch",
            "-config",
            str(ca_config),
            "-in",
            str(server_csr),
            "-out",
            str(server_cert),
            "-startdate",
            "20200101000000Z",
            "-enddate",
            "20210101000000Z",
        ],
        check=True,
        capture_output=True,
    )
    return ca_cert, server_cert


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    ca, cert, key = _certificate_files(tmp_path)
    values: dict[str, object] = {
        "vicidial_authorization_url": AUTH_URL,
        "vicidial_edge_url": EDGE_URL,
        "vicidial_ca_file": str(ca),
        "vicidial_client_cert_file": str(cert),
        "vicidial_client_key_file": str(key),
        "transfer_control_enabled": True,
        "vicidial_read_enabled": True,
    }
    values.update(overrides)
    # Temporary certificate paths are intentionally limited to tests. Production
    # Settings validation requires /run/secrets/vicidial-mtls.
    return Settings.model_construct(**values)


def _client(settings: Settings, transport: httpx.BaseTransport) -> VicidialMtlsClient:
    return VicidialMtlsClient(
        settings,
        transport=transport,
        resolver=lambda _: ["10.42.0.20"],
    )


def test_settings_accept_only_canonical_private_https_urls():
    settings = Settings(
        vicidial_authorization_url=AUTH_URL,
        vicidial_edge_url=EDGE_URL,
    )
    assert settings.vicidial_authorization_url == AUTH_URL
    for invalid in (
        "http://authorization.internal.codestra.agency:8443",
        "https://65.21.67.207:8443",
        "https://authorization.internal.codestra.agency:8095",
        "https://authorization.internal.codestra.agency:8443/unapproved",
        "https://api.codestra.agency:8443",
    ):
        with pytest.raises(ValidationError):
            Settings(vicidial_authorization_url=invalid)


def test_settings_require_secret_mount_paths():
    with pytest.raises(ValidationError):
        Settings(vicidial_ca_file="/tmp/ca.crt")
    settings = Settings(vicidial_ca_file="/run/secrets/vicidial-mtls/ca.crt")
    assert settings.vicidial_ca_file.endswith("/ca.crt")


def test_valid_mtls_request_has_ids_and_exact_route(tmp_path: Path):
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"allowed": True})

    client = _client(_settings(tmp_path), httpx.MockTransport(handler))
    try:
        assert client.authorize({"lead_id": 42}) == {"allowed": True}
    finally:
        client.close()
    request = captured[0]
    assert request.method == "POST"
    assert request.url.path == "/api/v1/transfers/authorize"
    assert request.headers["X-Correlation-ID"]
    assert request.headers["X-Request-ID"]


def test_missing_client_certificate_fails_closed(tmp_path: Path):
    settings = _settings(
        tmp_path, vicidial_client_cert_file=str(tmp_path / "missing.crt")
    )
    with pytest.raises(VicidialMtlsError, match="client certificate is missing"):
        _client(settings, httpx.MockTransport(lambda _: httpx.Response(200)))


def test_untrusted_ca_fails_closed(tmp_path: Path):
    invalid_ca = tmp_path / "invalid-ca.crt"
    invalid_ca.write_text("not a certificate")
    settings = _settings(tmp_path, vicidial_ca_file=str(invalid_ca))
    with pytest.raises(VicidialMtlsError, match="invalid or unreadable"):
        _client(settings, httpx.MockTransport(lambda _: httpx.Response(200)))


def test_wrong_hostname_certificate_is_rejected(tmp_path: Path):
    ca, server = _signed_server_certificate(
        tmp_path, hostname="wrong.internal.codestra.agency"
    )
    result = subprocess.run(
        [
            "openssl",
            "verify",
            "-CAfile",
            str(ca),
            "-verify_hostname",
            "authorization.internal.codestra.agency",
            str(server),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "hostname mismatch" in (result.stdout + result.stderr).lower()


def test_expired_server_certificate_is_rejected(tmp_path: Path):
    ca, server = _signed_server_certificate(
        tmp_path, hostname="authorization.internal.codestra.agency", expired=True
    )
    result = subprocess.run(
        ["openssl", "verify", "-CAfile", str(ca), str(server)],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "expired" in (result.stdout + result.stderr).lower()


def test_crl_validation_is_fail_closed_when_crl_is_invalid(tmp_path: Path):
    crl = tmp_path / "revoked.crl"
    crl.write_text("invalid CRL")
    settings = _settings(tmp_path, vicidial_crl_file=str(crl))
    with pytest.raises(VicidialMtlsError, match="invalid or unreadable"):
        _client(settings, httpx.MockTransport(lambda _: httpx.Response(200)))


def test_unapproved_route_and_method_are_rejected(tmp_path: Path):
    client = _client(
        _settings(tmp_path), httpx.MockTransport(lambda _: httpx.Response(200))
    )
    try:
        with pytest.raises(VicidialMtlsError, match="method or route"):
            client.request("GET", f"{AUTH_URL}/api/v1/transfers/authorize", {})
        with pytest.raises(VicidialMtlsError, match="method or route"):
            client.request("POST", f"{AUTH_URL}/health", {})
    finally:
        client.close()


def test_timeout_and_connection_refusal_do_not_retry(tmp_path: Path):
    calls = 0

    def timeout(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectTimeout("test timeout", request=request)

    client = _client(_settings(tmp_path), httpx.MockTransport(timeout))
    try:
        with pytest.raises(VicidialMtlsError, match="failed closed"):
            client.authorize({"lead_id": 42})
    finally:
        client.close()
    assert calls == 1

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = _client(_settings(tmp_path), httpx.MockTransport(refused))
    try:
        with pytest.raises(VicidialMtlsError, match="failed closed"):
            client.authorize({"lead_id": 42})
    finally:
        client.close()


def test_payload_limit_is_enforced_before_transport(tmp_path: Path):
    client = _client(
        _settings(tmp_path), httpx.MockTransport(lambda _: httpx.Response(200))
    )
    try:
        with pytest.raises(VicidialMtlsError, match="payload exceeds"):
            client.authorize({"secret": "x" * MAX_PAYLOAD_BYTES})
    finally:
        client.close()


def test_logs_do_not_contain_payload_or_credentials(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    marker = "DO-NOT-LOG-THIS-SECRET"
    client = _client(
        _settings(tmp_path),
        httpx.MockTransport(lambda _: httpx.Response(200, json={"ok": True})),
    )
    try:
        with caplog.at_level(logging.INFO, logger="codestra.vicidial_mtls"):
            client.authorize({"token": marker})
    finally:
        client.close()
    assert marker not in caplog.text
    assert "client.key" not in caplog.text


def test_disabled_flags_fail_closed_before_network(tmp_path: Path):
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200)

    settings = _settings(
        tmp_path,
        transfer_control_enabled=False,
        vicidial_read_enabled=False,
        vicidial_write_enabled=False,
        live_writes_enabled=False,
    )
    client = _client(settings, httpx.MockTransport(handler))
    try:
        with pytest.raises(VicidialMtlsError, match="authorization is disabled"):
            client.authorize({})
        with pytest.raises(VicidialMtlsError, match="execution is disabled"):
            client.execute({})
    finally:
        client.close()
    assert calls == 0


def test_public_or_mixed_dns_resolution_fails_before_network(tmp_path: Path):
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200)

    for addresses in (["65.21.67.207"], ["10.42.0.20", "65.21.67.207"], []):
        client = VicidialMtlsClient(
            _settings(tmp_path),
            transport=httpx.MockTransport(handler),
            resolver=lambda _, result=addresses: result,
        )
        try:
            with pytest.raises(VicidialMtlsError, match="private IP"):
                client.authorize({})
        finally:
            client.close()
    assert calls == 0
