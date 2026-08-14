#!/usr/bin/env python3
"""Validate protected Alertmanager URL files without exposing their contents."""

from __future__ import annotations

import sys
import hashlib
import socket
import ssl
import urllib.parse
from pathlib import Path

import yaml


ALLOWED_MODES = {0o400, 0o440, 0o600, 0o640}


def reachable(parsed: urllib.parse.ParseResult) -> None:
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    with socket.create_connection((parsed.hostname, port), timeout=10) as connection:
        if parsed.scheme == "https":
            context = ssl.create_default_context()
            with context.wrap_socket(connection, server_hostname=parsed.hostname):
                pass


def validate(
    config_path: Path,
    secret_dir: Path,
    *,
    check_network: bool = False,
    expected_uid: int = 0,
    expected_gid: int = 0,
) -> int:
    config = yaml.safe_load(config_path.read_text())
    validated = 0
    for receiver in config.get("receivers", []):
        for webhook in receiver.get("webhook_configs", []):
            if "url" in webhook:
                print("inline receiver URL is forbidden", file=sys.stderr)
                return 2
            reference = webhook.get("url_file")
            if not reference:
                continue
            filename = Path(reference).name.removeprefix("alertmanager_")
            actual = secret_dir / filename
            if not actual.is_file() or not actual.read_text().strip():
                print(f"empty receiver file: {actual}", file=sys.stderr)
                return 2
            metadata = actual.stat()
            mode = metadata.st_mode & 0o777
            if metadata.st_uid != expected_uid or metadata.st_gid != expected_gid:
                print(f"unsafe receiver file owner: {actual}", file=sys.stderr)
                return 2
            if mode not in ALLOWED_MODES:
                print(f"unsafe receiver file mode: {actual} ({mode:o})", file=sys.stderr)
                return 2
            value = actual.read_text().strip()
            parsed = urllib.parse.urlparse(value)
            if parsed.scheme not in {"https", "http"} or not parsed.hostname:
                print(f"invalid receiver URL reference: {actual}", file=sys.stderr)
                return 2
            if (
                parsed.hostname.endswith(".invalid")
                or parsed.hostname in {"example.com", "localhost"}
                or any(word in value.upper() for word in ("PLACEHOLDER", "REPLACE_WITH_APPROVED", "TODO", "TBD"))
            ):
                print(f"placeholder receiver URL rejected: {actual}", file=sys.stderr)
                return 2
            if check_network:
                try:
                    reachable(parsed)
                except (OSError, ssl.SSLError, ValueError) as exc:
                    print(f"receiver network validation failed: {actual} ({type(exc).__name__})", file=sys.stderr)
                    return 2
            fingerprint = hashlib.sha256(value.encode()).hexdigest()
            receiver_type = receiver.get("name", "unknown").replace("approved-", "")
            print(
                f"receiver_type={receiver_type} path={actual} owner={metadata.st_uid}:{metadata.st_gid} "
                f"mode={mode:o} fingerprint={fingerprint} network={'PASS' if check_network else 'NOT_CHECKED'}"
            )
            validated += 1
    if validated != 4:
        print(f"receiver reference count invalid: {validated}", file=sys.stderr)
        return 2
    print(f"receiver_files=validated count={validated}")
    return 0


def main() -> int:
    args = sys.argv[1:]
    check_network = False
    if "--check-network" in args:
        args.remove("--check-network")
        check_network = True
    if len(args) != 2:
        print("usage: validate-receiver-files.py [--check-network] ALERTMANAGER_CONFIG HOST_SECRET_DIR", file=sys.stderr)
        return 2
    return validate(*map(Path, args), check_network=check_network)


if __name__ == "__main__":
    raise SystemExit(main())
