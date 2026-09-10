#!/usr/bin/env python3
"""Prepare a complete provider CRL bundle without exporting signing keys."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def timestamp(value, name):
    current = getattr(value, name + "_utc", None)
    return current if current is not None else utc(getattr(value, name))


def validate_crl(crl, issuer, now):
    if crl.issuer != issuer.subject or not crl.is_signature_valid(issuer.public_key()):
        raise ValueError("CRL issuer or signature does not match")
    if timestamp(crl, "last_update") > now or timestamp(crl, "next_update") <= now:
        raise ValueError("CRL is not currently valid")


def issue_root_crl(root, signer, previous=None, *, initialize=False, now=None, days=30):
    now = now or datetime.now(timezone.utc)
    if not 1 <= days <= 30:
        raise ValueError("CRL validity must be between 1 and 30 days")
    if root.issuer != root.subject or not root.extensions.get_extension_for_class(x509.BasicConstraints).value.ca:
        raise ValueError("A self-issued root CA certificate is required")
    root.verify_directly_issued_by(root)
    if not timestamp(root, "not_valid_before") <= now < timestamp(root, "not_valid_after"):
        raise ValueError("Root CA is not currently valid")
    public_format = serialization.PublicFormat.SubjectPublicKeyInfo
    encoding = serialization.Encoding.DER
    if root.public_key().public_bytes(encoding, public_format) != signer.public_key().public_bytes(encoding, public_format):
        raise ValueError("Signing key does not match the root CA")
    if previous is None and not initialize:
        raise ValueError("Initial root CRL issuance requires an explicit initialization decision")
    if previous is not None and initialize:
        raise ValueError("An existing root revocation authority must not be initialized again")
    number = 1
    if previous is not None:
        if previous.issuer != root.subject or not previous.is_signature_valid(root.public_key()):
            raise ValueError("Previous root CRL has an invalid issuer or signature")
        number = previous.extensions.get_extension_for_class(x509.CRLNumber).value.crl_number + 1
    builder = (
        x509.CertificateRevocationListBuilder()
        .issuer_name(root.subject)
        .last_update(now - timedelta(minutes=1))
        .next_update(min(now + timedelta(days=days), timestamp(root, "not_valid_after")))
        .add_extension(x509.CRLNumber(number), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(root.public_key()), critical=False)
    )
    for revoked in previous or []:
        builder = builder.add_revoked_certificate(revoked)
    result = builder.sign(signer, hashes.SHA384())
    validate_crl(result, root, now)
    return result


def build_bundle(root, root_crl, intermediate, provider_crl, *, now=None):
    now = now or datetime.now(timezone.utc)
    validate_crl(root_crl, root, now)
    validate_crl(provider_crl, intermediate, now)
    intermediate.verify_directly_issued_by(root)
    if not timestamp(intermediate, "not_valid_before") <= now < timestamp(intermediate, "not_valid_after"):
        raise ValueError("Provider CA is not currently valid")
    if not intermediate.extensions.get_extension_for_class(x509.BasicConstraints).value.ca:
        raise ValueError("Provider issuer is not a CA")
    if intermediate.issuer != root.subject:
        raise ValueError("Provider CA is not issued by the selected root")
    if any(item.serial_number == intermediate.serial_number for item in root_crl):
        raise ValueError("Provider intermediate CA is revoked")
    return (
        provider_crl.public_bytes(serialization.Encoding.PEM)
        + root_crl.public_bytes(serialization.Encoding.PEM)
    )


def write_new(path, data):
    # Candidate files are never allowed to replace an existing authority or bundle.
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root-certificate", type=Path, required=True)
    parser.add_argument("--root-key-file", type=Path, required=True)
    parser.add_argument("--expected-root-sha256", required=True)
    parser.add_argument("--previous-root-crl", type=Path)
    parser.add_argument("--initialize-root-crl", action="store_true")
    parser.add_argument("--provider-certificate", type=Path, required=True)
    parser.add_argument("--provider-crl", type=Path, required=True)
    parser.add_argument("--output-root-crl", type=Path, required=True)
    parser.add_argument("--output-bundle", type=Path, required=True)
    args = parser.parse_args()
    if args.output_root_crl.exists() or args.output_bundle.exists():
        raise ValueError("Output candidate already exists")
    root_data = args.root_certificate.read_bytes()
    if hashlib.sha256(root_data).hexdigest() != args.expected_root_sha256:
        raise ValueError("Root certificate fingerprint differs from the selected authority")
    metadata = args.root_key_file.lstat()
    if args.root_key_file.is_symlink() or metadata.st_mode & 0o077 or metadata.st_uid not in (0, os.geteuid()):
        raise ValueError("Root signing key file has unsafe ownership or permissions")
    root = x509.load_pem_x509_certificate(root_data)
    signer = serialization.load_pem_private_key(args.root_key_file.read_bytes(), password=None)
    previous = x509.load_pem_x509_crl(args.previous_root_crl.read_bytes()) if args.previous_root_crl else None
    intermediate = x509.load_pem_x509_certificate(args.provider_certificate.read_bytes())
    provider_crl = x509.load_pem_x509_crl(args.provider_crl.read_bytes())
    root_crl = issue_root_crl(root, signer, previous, initialize=args.initialize_root_crl)
    bundle = build_bundle(root, root_crl, intermediate, provider_crl)
    write_new(args.output_root_crl, root_crl.public_bytes(serialization.Encoding.PEM))
    write_new(args.output_bundle, bundle)
    print(json.dumps({
        "bundle_sha256": hashlib.sha256(bundle).hexdigest(),
        "provider_revocations_preserved": len(provider_crl),
        "root_revocations_preserved": len(root_crl),
        "root_crl_next_update": timestamp(root_crl, "next_update").isoformat(),
        "provider_crl_next_update": timestamp(provider_crl, "next_update").isoformat(),
        "private_material_exported": False,
        "runtime_changed": False,
    }))


if __name__ == "__main__":
    main()
