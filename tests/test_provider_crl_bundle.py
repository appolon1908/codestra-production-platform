import importlib.util
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

SPEC = importlib.util.spec_from_file_location(
    "provider_crl_bundle", Path(__file__).resolve().parents[1] / "operations/tls/provider_crl_bundle.py"
)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def certificate(name, key, serial, issuer=None, signer=None, ca=False):
    now = datetime.now(timezone.utc)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    return (
        x509.CertificateBuilder().subject_name(subject)
        .issuer_name(issuer.subject if issuer else subject)
        .public_key(key.public_key()).serial_number(serial)
        .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), True)
        .sign(signer or key, hashes.SHA256())
    )


@pytest.fixture
def authority():
    root_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    root = certificate("Test root", root_key, 1, ca=True)
    issuer_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    issuer = certificate("Test provider", issuer_key, 2, root, root_key, ca=True)
    now = datetime.now(timezone.utc)
    revoked = x509.RevokedCertificateBuilder().serial_number(4).revocation_date(now).build()
    provider_crl = (
        x509.CertificateRevocationListBuilder().issuer_name(issuer.subject)
        .last_update(now - timedelta(minutes=1)).next_update(now + timedelta(days=10))
        .add_extension(x509.CRLNumber(1), False).add_revoked_certificate(revoked)
        .sign(issuer_key, hashes.SHA256())
    )
    return root_key, root, issuer_key, issuer, provider_crl


def test_complete_bundle_accepts_valid_leaf_and_rejects_revoked_leaf(authority, tmp_path):
    root_key, root, issuer_key, issuer, provider_crl = authority
    root_crl = module.issue_root_crl(root, root_key, initialize=True)
    for name, item in [("root", root), ("issuer", issuer)]:
        (tmp_path / name).write_bytes(item.public_bytes(serialization.Encoding.PEM))
    (tmp_path / "bundle").write_bytes(module.build_bundle(root, root_crl, issuer, provider_crl))
    for serial, expected in [(3, 0), (4, 2)]:
        leaf = certificate("Test client", issuer_key, serial, issuer, issuer_key)
        path = tmp_path / "leaf"
        path.write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
        result = subprocess.run(
            ["openssl", "verify", "-crl_check_all", "-CAfile", str(tmp_path / "root"),
             "-untrusted", str(tmp_path / "issuer"), "-CRLfile", str(tmp_path / "bundle"), str(path)],
            capture_output=True, text=True, check=False,
        )
        assert result.returncode == expected, result.stderr
        if expected:
            assert "certificate revoked" in result.stderr


def test_initialization_is_explicit_and_cannot_replace_existing_authority(authority):
    root_key, root, *_ = authority
    with pytest.raises(ValueError, match="explicit"):
        module.issue_root_crl(root, root_key)
    previous = module.issue_root_crl(root, root_key, initialize=True)
    with pytest.raises(ValueError, match="must not be initialized again"):
        module.issue_root_crl(root, root_key, previous, initialize=True)


def test_renewal_preserves_root_revocations_and_increments_number(authority):
    root_key, root, _, issuer, _ = authority
    now = datetime.now(timezone.utc)
    revoked = x509.RevokedCertificateBuilder().serial_number(issuer.serial_number).revocation_date(now).build()
    previous = (
        x509.CertificateRevocationListBuilder().issuer_name(root.subject)
        .last_update(now - timedelta(days=2)).next_update(now - timedelta(days=1))
        .add_extension(x509.CRLNumber(8), False).add_revoked_certificate(revoked)
        .sign(root_key, hashes.SHA256())
    )
    renewed = module.issue_root_crl(root, root_key, previous)
    assert [item.serial_number for item in renewed] == [issuer.serial_number]
    assert renewed.extensions.get_extension_for_class(x509.CRLNumber).value.crl_number == 9


def test_bundle_rejects_expired_crl_and_revoked_intermediate(authority):
    root_key, root, issuer_key, issuer, provider_crl = authority
    now = datetime.now(timezone.utc)
    root_crl = module.issue_root_crl(root, root_key, initialize=True)
    with pytest.raises(ValueError, match="not currently valid"):
        module.build_bundle(root, root_crl, issuer, provider_crl, now=now + timedelta(days=11))
    revoked = x509.RevokedCertificateBuilder().serial_number(issuer.serial_number).revocation_date(now).build()
    bad_root_crl = (
        x509.CertificateRevocationListBuilder().issuer_name(root.subject)
        .last_update(now - timedelta(minutes=1)).next_update(now + timedelta(days=10))
        .add_revoked_certificate(revoked).sign(root_key, hashes.SHA256())
    )
    with pytest.raises(ValueError, match="intermediate CA is revoked"):
        module.build_bundle(root, bad_root_crl, issuer, provider_crl)


def test_candidate_output_never_overwrites(tmp_path):
    path = tmp_path / "candidate"
    module.write_new(path, b"first")
    with pytest.raises(FileExistsError):
        module.write_new(path, b"second")
    assert path.read_bytes() == b"first"


def test_root_signer_must_match_selected_ca(authority):
    _, root, issuer_key, _, _ = authority
    with pytest.raises(ValueError, match="does not match"):
        module.issue_root_crl(root, issuer_key, initialize=True)


def test_renewal_preserves_revocations_from_unnumbered_crl(authority):
    root_key, root, _, issuer, _ = authority
    now = datetime.now(timezone.utc)
    revoked = x509.RevokedCertificateBuilder().serial_number(issuer.serial_number).revocation_date(now).build()
    previous = (
        x509.CertificateRevocationListBuilder().issuer_name(root.subject)
        .last_update(now - timedelta(minutes=1)).next_update(now + timedelta(days=1))
        .add_revoked_certificate(revoked).sign(root_key, hashes.SHA256())
    )
    renewed = module.issue_root_crl(root, root_key, previous)
    assert [item.serial_number for item in renewed] == [issuer.serial_number]
    assert renewed.extensions.get_extension_for_class(x509.CRLNumber).value.crl_number == 1
