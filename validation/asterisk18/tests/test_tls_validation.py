import socket
import ssl
import subprocess

import pytest

from harness import HOST, PORT_OFFSET, RUNTIME, TLS_HOSTNAME, login, record


def connect(port: int, *, cafile: str = "test-ca.pem", hostname: str = TLS_HOSTNAME):
    ctx = ssl.create_default_context(cafile=str(RUNTIME / "pki" / cafile))
    raw = socket.create_connection((HOST, port + PORT_OFFSET), timeout=3)
    return ctx.wrap_socket(raw, server_hostname=hostname)


def rejected(name: str, port: int, **kwargs):
    with pytest.raises((ssl.SSLError, ssl.CertificateError)):
        connect(port, **kwargs)
    record(name, result="PASS", port=port)


def test_valid_chain_and_hostname():
    with connect(15039) as conn:
        assert conn.version() in {"TLSv1.2", "TLSv1.3"}
    record("valid_chain_and_hostname", result="PASS")


def test_wrong_hostname_rejected():
    rejected("wrong_hostname", 15039, hostname="wrong.test.invalid")


def test_unknown_ca_rejected():
    rejected("unknown_ca", 15043)


def test_expired_rejected():
    rejected("expired_certificate", 15040)


def test_not_yet_valid_rejected():
    rejected("not_yet_valid_certificate", 15041)


def test_missing_san_rejected():
    # Python/OpenSSL still permits CN fallback in some builds; require strict SAN presence first.
    decoded = ssl._ssl._test_decode_cert(str(RUNTIME / "pki/missing-san.pem"))
    assert "subjectAltName" not in decoded
    ctx = ssl.create_default_context(cafile=str(RUNTIME / "pki/test-ca.pem"))
    ctx.hostname_checks_common_name = False
    raw = socket.create_connection((HOST, 15042), timeout=3)
    with pytest.raises(ssl.CertificateError):
        ctx.wrap_socket(raw, server_hostname=TLS_HOSTNAME)
    record("missing_san", result="PASS")


def test_plaintext_to_tls_rejected_and_no_downgrade():
    with socket.create_connection((HOST, 15039 + PORT_OFFSET), timeout=3) as conn:
        conn.sendall(b"Action: Ping\r\n\r\n")
        data = conn.recv(256)
    assert b"Asterisk Call Manager" not in data
    record("plaintext_to_tls_no_downgrade", result="PASS")


def test_tls_to_plaintext_rejected():
    with pytest.raises(ssl.SSLError):
        connect(15038)
    record("tls_to_plaintext_protocol_confusion", result="PASS")


def test_prohibited_tls10_rejected():
    result = subprocess.run(
        ["openssl", "s_client", "-connect", f"{HOST}:{15039 + PORT_OFFSET}", "-tls1", "-brief"],
        text=True, capture_output=True, timeout=5,
    )
    assert result.returncode != 0
    record("prohibited_tls_protocol", result="PASS")


def test_prohibited_cipher_rejected_where_supported():
    result = subprocess.run(
        ["openssl", "s_client", "-connect", f"{HOST}:{15039 + PORT_OFFSET}", "-tls1_2",
         "-cipher", "AES128-SHA", "-brief"],
        text=True, capture_output=True, timeout=5,
    )
    assert result.returncode != 0
    record("prohibited_tls_cipher", result="PASS")


def test_missing_ca_secret_and_unreachable_fail_closed():
    with pytest.raises((ssl.SSLError, FileNotFoundError)):
        connect(15039, cafile="absent-ca.pem")
    assert login(password="").get("Response") == "Error"
    with pytest.raises(OSError):
        socket.create_connection((HOST, 15999 + PORT_OFFSET), timeout=.2)
    record("fail_closed_ca_secret_unreachable", result="PASS")
