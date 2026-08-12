#!/usr/bin/env python3
"""Authenticated loopback readiness probe for the private adapter."""

from __future__ import annotations

import hashlib
import hmac
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path


def main() -> int:
    key = Path(sys.argv[1]).read_bytes().strip()
    timestamp = int(time.time())
    nonce = uuid.uuid4().hex
    digest = hashlib.sha256(b"").hexdigest()
    signature = hmac.new(
        key,
        f"{timestamp}\n{nonce}\n{digest}".encode(),
        hashlib.sha256,
    ).hexdigest()
    request = urllib.request.Request(
        "http://127.0.0.1:8097/ready",
        headers={
            "X-Forwarded-For": "10.40.0.1",
            "X-Service-Identity": "codestra-middleware",
            "X-Service-Scopes": "telephony:adapter-status-read",
            "X-Request-Timestamp": str(timestamp),
            "X-Request-Nonce": nonce,
            "X-Request-Signature": signature,
        },
    )
    for attempt in range(5):
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                document = json.load(response)
            break
        except urllib.error.URLError:
            if attempt == 4:
                raise
            time.sleep(1)
    if (
        response.status != 200
        or document.get("status") != "ready"
        or document.get("backend") != "read_only"
        or document.get("writes_enabled") is not False
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
