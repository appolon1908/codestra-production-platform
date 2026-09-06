from pathlib import Path


MANIFEST = Path("operations/tls/certificates.tsv")
PRODUCTION_NAME = "provisioning-production-server"
RUNTIME_SECRET_ROOT = "/etc/codestra/secrets/provisioning-service-production/"
CA_AUTHORITY_ROOT = "/etc/codestra/pki/provisioning-production-ca/"
RUNTIME_CONTAINER = "codestra-provisioning-production-provisioning-service-1"


def _record() -> list[str]:
    for raw_line in MANIFEST.read_text().splitlines():
        if raw_line.startswith(f"{PRODUCTION_NAME}|"):
            fields = raw_line.split("|")
            assert len(fields) == 11
            return fields
    raise AssertionError(f"missing certificate lifecycle record: {PRODUCTION_NAME}")


def test_provisioning_ca_signing_key_is_not_in_runtime_secret_bundle() -> None:
    _, kind, certificate, key, ca_certificate, ca_key, days, _, sans, reload, _ = _record()

    assert kind == "server"
    assert certificate.startswith(RUNTIME_SECRET_ROOT)
    assert key.startswith(RUNTIME_SECRET_ROOT)
    assert ca_certificate.startswith(CA_AUTHORITY_ROOT)
    assert ca_key.startswith(CA_AUTHORITY_ROOT)
    assert not ca_key.startswith(RUNTIME_SECRET_ROOT)
    assert days == "90"
    assert sans == "DNS:provisioning-service-production"
    assert reload == f"docker:{RUNTIME_CONTAINER}"


def test_provisioning_certificate_renewal_has_a_verified_runtime_reload_target() -> None:
    reload = _record()[9]

    assert reload not in {"", "none"}
    assert reload.startswith(("docker:", "systemd:"))
    assert reload == f"docker:{RUNTIME_CONTAINER}"
