from __future__ import annotations

import hashlib

import pytest

from tools.provision_release_trust_anchor import provision


PUBLIC_KEY = b"ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAISyntheticReleaseKey"


def test_provisions_verified_external_release_signer_idempotently(tmp_path) -> None:
    source = tmp_path / "external-release-key.pub"
    destination = tmp_path / "etc/codestra/release/allowed_signers"
    source.write_bytes(PUBLIC_KEY + b" operator-comment\n")
    fingerprint = hashlib.sha256(PUBLIC_KEY).hexdigest()
    assert provision(source, fingerprint, destination) == fingerprint
    assert destination.read_bytes() == b"codestra-release " + PUBLIC_KEY + b"\n"
    assert destination.stat().st_mode & 0o777 == 0o644
    assert provision(source, fingerprint, destination) == fingerprint


def test_rejects_unverified_or_conflicting_release_signer(tmp_path) -> None:
    source = tmp_path / "external-release-key.pub"
    destination = tmp_path / "allowed_signers"
    source.write_bytes(PUBLIC_KEY)
    with pytest.raises(ValueError, match="fingerprint mismatch"):
        provision(source, "0" * 64, destination)
    destination.write_text("codestra-release ssh-ed25519 different\n")
    with pytest.raises(ValueError, match="different release trust anchor"):
        provision(source, hashlib.sha256(PUBLIC_KEY).hexdigest(), destination)
