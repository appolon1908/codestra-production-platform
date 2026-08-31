#!/usr/bin/python3
"""No-secret helpers for immutable production-validation probes."""

from __future__ import annotations

import json
import os
import re
import stat
import urllib.error
import urllib.request
from pathlib import Path
from typing import Mapping


GATEWAY = "http://127.0.0.1:18000"
SECRET_KEY_RE = re.compile(
    r"(?i)(authorization|cookie|password|passwd|token|api[_-]?key|client[_-]?secret|"
    r"smtp[_-]?(password|credential)|private[_-]?key|database[_-]?(url|dsn))"
)


def contains_secret_key(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            SECRET_KEY_RE.search(str(key)) is not None or contains_secret_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(contains_secret_key(item) for item in value)
    return False


def request_status(
    method: str,
    path: str,
    *,
    headers: Mapping[str, str] | None = None,
    body: bytes | None = None,
) -> dict[str, object]:
    if method not in {"GET", "POST"} or not path.startswith("/v1/"):
        raise ValueError("fixed request rejected")
    request = urllib.request.Request(
        GATEWAY + path,
        method=method,
        headers=dict(headers or {}),
        data=body,
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = response.read(8193)
            return {
                "status": response.status,
                "response_bytes": min(len(payload), 8192),
                "response_truncated": len(payload) > 8192,
            }
    except urllib.error.HTTPError as exc:
        payload = exc.read(8193)
        return {
            "status": exc.code,
            "response_bytes": min(len(payload), 8192),
            "response_truncated": len(payload) > 8192,
        }
    except (OSError, urllib.error.URLError) as exc:
        return {"status": 0, "error": type(exc).__name__}


def emit(value: object) -> None:
    print(json.dumps(value, sort_keys=True, separators=(",", ":")))


def safe_json_file(path: Path, allowed_keys: set[str]) -> dict[str, object]:
    metadata = path.lstat()
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_mode & 0o022
        or metadata.st_size > 65536
    ):
        raise ValueError("readback rejected")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        raw = os.read(descriptor, 65537)
    finally:
        os.close(descriptor)
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict) or set(value) != allowed_keys:
        raise ValueError("readback schema rejected")
    if contains_secret_key(value):
        raise ValueError("secret field rejected")
    return value
