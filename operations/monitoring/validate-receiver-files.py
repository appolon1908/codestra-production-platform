#!/usr/bin/env python3
"""Validate protected Alertmanager URL files without exposing their contents."""

from __future__ import annotations

import sys
import urllib.parse
from pathlib import Path

import yaml


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: validate-receiver-files.py ALERTMANAGER_CONFIG HOST_SECRET_DIR", file=sys.stderr)
        return 2
    config_path, secret_dir = map(Path, sys.argv[1:])
    config = yaml.safe_load(config_path.read_text())
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
    print("receiver_files=validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
