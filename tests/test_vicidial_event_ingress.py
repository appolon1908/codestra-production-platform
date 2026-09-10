"""Offline security and durable inbox/outbox tests; no provider or host contact."""

import hashlib
import hmac
import json
import ssl
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from email.message import Message
from io import BytesIO

import pytest

from control_plane_service import calling_ingress as ingress
from control_plane_service.core import Store

EVENT_ID = "11111111-1111-4111-8111-111111111111"
CORR = "22222222-2222-4222-8222-222222222222"
STAMP = "2026-09-07T19:00:00Z"
NOW = datetime.fromisoformat(STAMP.replace("Z", "+00:00")).timestamp()
SECRET = b"isolated-adapter-signing-test-material-32-bytes"


def event():
    payload = dict(
        event_id=EVENT_ID,
        type="telephony.call.ringing.v1",
        tenant_id="tenant-a",
        business_unit_id="unit-a",
        campaign_id="campaign-a",
        agent_id="agent-a",
        operation_id="33333333-3333-4333-8333-333333333333",
        correlation_id=CORR,
        schema_version=1,
        occurred_at=STAMP,
        sequence=1,
    )
    return dict(
        event_type=payload["type"],
        event_version="1.0",
        occurred_at=STAMP,
        tenant_id="tenant-a",
        idempotency_key="accept-1",
        correlation_id=CORR,
        payload=payload,
    )


def headers(raw, value=None):
    value = value or event()
    digest = hashlib.sha256(raw).hexdigest()
    material = "\n".join(
        (
            "v1",
            STAMP,
            "POST",
            ingress.PATH,
            value["idempotency_key"],
            value["payload"]["event_id"],
            digest,
            "",
        )
    )
    result = Message()
    for key, val in {
        "Content-Type": "application/json",
        "Content-Length": str(len(raw)),
        "Idempotency-Key": value["idempotency_key"],
        "X-Correlation-ID": value["correlation_id"],
        "X-Codestra-Timestamp": STAMP,
        "X-Codestra-Content-SHA256": digest,
        "X-Codestra-Signature": "v1="
        + hmac.new(SECRET, material.encode(), hashlib.sha256).hexdigest(),
    }.items():
        result[key] = val
    return result


@pytest.fixture
def binding(tmp_path):
    secret = tmp_path / "secret"
    secret.write_bytes(SECRET)
    return {
        "hmac_secret_file": str(secret),
        "grants": [{k: event()["payload"][k] for k in ingress.GRANT_FIELDS}],
    }


def test_byte_exact_signing_and_canonical_schema(binding):
    raw = json.dumps(event()).encode()
    assert ingress.validate_body(raw, headers(raw), binding, now=NOW) == event()


@pytest.mark.parametrize("delta", [-301, 301])
def test_stale_future_timestamps_rejected(binding, delta):
    raw = json.dumps(event()).encode()
    with pytest.raises(ingress.IngressError, match="EXPIRED_SIGNATURE"):
        ingress.validate_body(raw, headers(raw), binding, now=NOW + delta)


@pytest.mark.parametrize(
    "header,bad",
    [
        ("X-Codestra-Content-SHA256", "a" * 64),
        ("X-Codestra-Signature", "v1=" + "a" * 64),
        ("X-Codestra-Signature", "sha256=" + "a" * 64),
        ("Idempotency-Key", "different"),
        ("X-Correlation-ID", "different"),
        ("X-Codestra-Timestamp", "2026-09-07"),
    ],
)
def test_forged_headers_are_rejected(binding, header, bad):
    raw = json.dumps(event()).encode()
    h = headers(raw)
    h.replace_header(header, bad)
    with pytest.raises(ingress.IngressError):
        ingress.validate_body(raw, h, binding, now=NOW)


@pytest.mark.parametrize("field", ingress.GRANT_FIELDS)
def test_certificate_grants_bind_every_identity_dimension(binding, field):
    binding["grants"][0][field] = "different"
    raw = json.dumps(event()).encode()
    with pytest.raises(ingress.IngressError, match="ADAPTER_SCOPE_DENIED"):
        ingress.validate_body(raw, headers(raw), binding, now=NOW)


@pytest.mark.parametrize(
    "field,value",
    [
        ("sequence", True),
        ("sequence", -1),
        ("schema_version", True),
        ("agent_id", "agent.*"),
        ("event_id", "bad"),
        ("type", "telephony.call.originate.v1"),
        ("occurred_at", "no-date"),
    ],
)
def test_malformed_events_rejected(binding, field, value):
    value_event = event()
    value_event["payload"][field] = value
    raw = json.dumps(value_event).encode()
    with pytest.raises(ingress.IngressError):
        ingress.validate_body(raw, headers(raw, value_event), binding, now=NOW)


def test_duplicate_keys_and_raw_body_mutation_rejected(binding):
    raw = json.dumps(event()).encode()
    h = headers(raw)
    with pytest.raises(ingress.IngressError):
        ingress.validate_body(raw + b" ", h, binding, now=NOW)
    raw = raw.replace(
        b'"event_version": "1.0"', b'"event_version": "9.0", "event_version": "1.0"'
    )
    with pytest.raises(ingress.IngressError):
        ingress.validate_body(raw, headers(raw), binding, now=NOW)


def test_exact_concurrent_retries_have_one_receipt_and_three_intents(tmp_path):
    store = Store(str(tmp_path / "db"))
    raw = json.dumps(event()).encode()
    with ThreadPoolExecutor(max_workers=6) as pool:
        receipts = list(
            pool.map(
                lambda _: ingress.persist(store, event(), raw, "b" * 64), range(12)
            )
        )
    assert all(item == receipts[0] for item in receipts)
    assert receipts[0]["outcome"] == "DURABLY_ACCEPTED"
    with store.connect() as db:
        for table, count in [
            ("events", 1),
            ("calling_ingress_receipts", 1),
            ("event_deliveries", 3),
        ]:
            assert (
                db.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
                == count
            )


def test_changed_bytes_same_identity_conflict_without_mutation(tmp_path):
    store = Store(str(tmp_path / "db"))
    raw = json.dumps(event()).encode()
    original = ingress.persist(store, event(), raw, "b" * 64)
    with pytest.raises(ingress.IngressError, match="IDEMPOTENCY_CONFLICT"):
        ingress.persist(store, event(), raw + b" ", "b" * 64)
    assert ingress.persist(store, event(), raw, "b" * 64) == original


def test_failed_event_append_rolls_back_receipt(tmp_path):
    store = Store(str(tmp_path / "db"))
    raw = json.dumps(event()).encode()
    with store.connect() as db:
        db.execute(
            "CREATE TRIGGER deny_ingress BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT,'simulated failure'); END"
        )
    with pytest.raises(ingress.IngressError):
        ingress.persist(store, event(), raw, "b" * 64)
    with store.connect() as db:
        assert (
            db.execute("SELECT COUNT(*) AS n FROM calling_ingress_receipts").fetchone()[
                "n"
            ]
            == 0
        )
        assert (
            db.execute("SELECT COUNT(*) AS n FROM event_deliveries").fetchone()["n"]
            == 0
        )


class Request:
    path = ingress.PATH
    connection = object()

    def __init__(self, raw):
        self.rfile = BytesIO(raw)
        self.headers = headers(raw)
        self.result = None

    def send_json(self, status, value):
        self.result = (status, value)


def test_default_off_and_forged_proxy_certificate_headers_are_denied(
    monkeypatch, tmp_path
):
    current = Store(str(tmp_path / "db"))
    request = Request(json.dumps(event()).encode())
    monkeypatch.delenv("VICIDIAL_EVENT_INGRESS_ENABLED", raising=False)
    ingress.handle(request, current)
    assert request.result[0] == 503
    monkeypatch.setenv("VICIDIAL_EVENT_INGRESS_ENABLED", "true")
    request.headers["X-SSL-Client-Verify"] = "SUCCESS"
    request.headers["X-Client-Cert-SHA256"] = "b" * 64
    ingress.handle(request, current)
    assert request.result[0] == 401
    assert request.rfile.tell() == 0


def test_query_strings_rejected_before_acceptance(tmp_path):
    request = Request(json.dumps(event()).encode())
    request.path += "?bypass=1"
    ingress.handle(request, Store(str(tmp_path / "db")))
    assert request.result == (400, {"error": "INVALID_CANONICAL_PATH"})


def test_existing_server_exposes_only_canonical_authenticated_handler(
    monkeypatch, tmp_path
):
    from control_plane_service import server

    current = Store(str(tmp_path / "db"))
    monkeypatch.setattr(server, "STORE", current)
    request = Request(json.dumps(event()).encode())
    monkeypatch.setenv("VICIDIAL_EVENT_INGRESS_ENABLED", "true")
    server.Handler.do_POST(request)
    assert request.result == (401, {"error": "ADAPTER_MTLS_REQUIRED"})


def test_postgres_migration_has_attempt_backfill_and_restricted_receipts():
    from pathlib import Path

    text = (
        Path(__file__).parents[1]
        / "migrations/control_plane/007_corporate_delivery_receipts.sql"
    ).read_text()
    assert "FROM public.automation_executions" in text
    assert "GRANT SELECT, INSERT ON public.calling_ingress_receipts" in text
    assert "GRANT SELECT, INSERT, UPDATE ON public.calling_ingress_receipts" not in text
    assert "REVOKE DELETE, TRUNCATE" in text


@pytest.mark.parametrize(
    "stamp", ["2026-09-07 19:00:00Z", "2026-09-07T19:00:00", "2026-09-07T19:00:00+0400"]
)
def test_event_timestamp_requires_rfc3339(binding, stamp):
    value = event()
    value["occurred_at"] = stamp
    value["payload"]["occurred_at"] = stamp
    raw = json.dumps(value).encode()
    with pytest.raises(ingress.IngressError, match="INVALID_TIMESTAMP"):
        ingress.validate_body(raw, headers(raw, value), binding, now=NOW)


def test_live_loopback_mtls_certificate_binding_receipts_and_rejection(
    tmp_path, monkeypatch
):
    """Use an ephemeral local CA, actual SSL sockets and the real HTTP handler."""
    import ipaddress
    from datetime import timedelta, timezone
    from http.client import HTTPSConnection
    from threading import Thread

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    now = datetime.now(timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "isolated-test-ca")])

    def issue(name, key, usage=None, ca=False):
        builder = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(ca_name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(minutes=10))
            .add_extension(
                x509.BasicConstraints(ca=ca, path_length=None), critical=True
            )
            .add_extension(
                x509.SubjectKeyIdentifier.from_public_key(key.public_key()),
                critical=False,
            )
            .add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
                critical=False,
            )
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    content_commitment=False,
                    key_encipherment=not ca,
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=ca,
                    crl_sign=ca,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
        )
        if usage:
            builder = builder.add_extension(
                x509.ExtendedKeyUsage([usage]), critical=False
            )
        if usage == ExtendedKeyUsageOID.SERVER_AUTH:
            builder = builder.add_extension(
                x509.SubjectAlternativeName(
                    [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
                ),
                critical=False,
            )
        return builder.sign(ca_key, hashes.SHA256())

    ca_cert = issue(ca_name, ca_key, ca=True)
    ca_file = tmp_path / "ca.pem"
    ca_file.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    certs = {}
    for role, usage in [
        ("server", ExtendedKeyUsageOID.SERVER_AUTH),
        ("client", ExtendedKeyUsageOID.CLIENT_AUTH),
    ]:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cert = issue(
            x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, role)]), key, usage
        )
        cert_file = tmp_path / (role + ".pem")
        key_file = tmp_path / (role + ".key")
        cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_file.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        certs[role] = (cert, cert_file, key_file)
    secret = tmp_path / "hmac"
    secret.write_bytes(SECRET)
    fingerprint = hashlib.sha256(
        certs["client"][0].public_bytes(serialization.Encoding.DER)
    ).hexdigest()
    binding_file = tmp_path / "bindings.json"

    def save_binding(fingerprint_value):
        binding_file.write_text(
            json.dumps(
                {
                    "version": 1,
                    "bindings": [
                        {
                            "certificate_sha256": fingerprint_value,
                            "hmac_secret_file": str(secret),
                            "grants": [
                                {k: event()["payload"][k] for k in ingress.GRANT_FIELDS}
                            ],
                        }
                    ],
                }
            )
        )

    save_binding(fingerprint)
    monkeypatch.setenv("VICIDIAL_EVENT_BINDINGS_FILE", str(binding_file))
    monkeypatch.setenv("VICIDIAL_EVENT_INGRESS_ENABLED", "true")
    monkeypatch.setattr(ingress.time, "time", lambda: NOW)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.verify_mode = ssl.CERT_REQUIRED
    context.load_verify_locations(cafile=ca_file)
    context.load_cert_chain(certs["server"][1], certs["server"][2])
    client = ssl.create_default_context(cafile=str(ca_file))
    client.load_cert_chain(certs["client"][1], certs["client"][2])
    store = Store(str(tmp_path / "tls.db"))
    with ingress.make_server("127.0.0.1", 0, store, context) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def send(tls_context):
            connection = HTTPSConnection(
                "127.0.0.1", server.server_port, context=tls_context, timeout=3
            )
            raw = json.dumps(event()).encode()
            try:
                connection.request("POST", ingress.PATH, raw, dict(headers(raw)))
                response = connection.getresponse()
                return response.status, json.loads(response.read())
            finally:
                connection.close()

        try:
            first = send(client)
            assert first[0] == 202
            assert send(client) == first
            save_binding("a" * 64)
            assert send(client) == (403, {"error": "ADAPTER_IDENTITY_DENIED"})
            anonymous = ssl.create_default_context(cafile=str(ca_file))
            with pytest.raises((ssl.SSLError, ConnectionError, OSError)):
                send(anonymous)
            with store.connect() as db:
                assert (
                    db.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"] == 1
                )
                assert (
                    db.execute("SELECT COUNT(*) AS n FROM event_deliveries").fetchone()[
                        "n"
                    ]
                    == 3
                )
        finally:
            server.shutdown()
            thread.join(timeout=5)
    with pytest.raises(ValueError, match="certificate verification"):
        ingress.make_server(
            "127.0.0.1", 0, store, ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        )
