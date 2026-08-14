from __future__ import annotations

import hashlib
import subprocess
from concurrent.futures import ThreadPoolExecutor

import pytest

from tools.provision_release_trust_anchor import provision


def generate_key(tmp_path, name):
    private = tmp_path / name
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(private)],
        check=True,
    )
    public = private.with_suffix(".pub")
    normalized = b" ".join(public.read_bytes().strip().split()[:2])
    return public, normalized


def test_provisions_verified_external_release_signer_idempotently(tmp_path) -> None:
    source, public_key = generate_key(tmp_path, "release-key")
    destination = tmp_path / "etc/codestra/release/allowed_signers"
    fingerprint = hashlib.sha256(public_key).hexdigest()
    assert provision(source, fingerprint, destination) == fingerprint
    assert destination.read_bytes() == b"codestra-release " + public_key + b"\n"
    assert destination.stat().st_mode & 0o777 == 0o644
    assert provision(source, fingerprint, destination) == fingerprint


def test_rejects_unverified_or_conflicting_release_signer(tmp_path) -> None:
    source, public_key = generate_key(tmp_path, "release-key")
    destination = tmp_path / "allowed_signers"
    with pytest.raises(ValueError, match="fingerprint mismatch"):
        provision(source, "0" * 64, destination)
    destination.write_text("codestra-release ssh-ed25519 different\n")
    with pytest.raises(ValueError, match="different release trust anchor"):
        provision(source, hashlib.sha256(public_key).hexdigest(), destination)


def test_rejects_malformed_ssh_public_key(tmp_path) -> None:
    source = tmp_path / "malformed.pub"
    source.write_text("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAISyntheticReleaseKey\n")
    with pytest.raises(subprocess.CalledProcessError):
        provision(source, "0" * 64, tmp_path / "allowed_signers")


def test_concurrent_different_keys_cannot_overwrite_first_anchor(tmp_path) -> None:
    first, first_key = generate_key(tmp_path, "first")
    second, second_key = generate_key(tmp_path, "second")
    destination = tmp_path / "release/allowed_signers"
    inputs = [
        (first, hashlib.sha256(first_key).hexdigest()),
        (second, hashlib.sha256(second_key).hexdigest()),
    ]

    def install(item):
        try:
            return provision(item[0], item[1], destination)
        except ValueError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(install, inputs))
    assert sum(len(value) == 64 for value in outcomes) == 1
    assert outcomes.count("a different release trust anchor is already installed") == 1
    installed = destination.read_bytes()
    assert installed in {
        b"codestra-release " + first_key + b"\n",
        b"codestra-release " + second_key + b"\n",
    }
