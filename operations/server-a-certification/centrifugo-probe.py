#!/usr/bin/env python3
"""Deterministic Centrifugo process, routed HTTP, and WebSocket probe."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import secrets
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PACKAGE = Path(__file__).resolve().parents[1] / "database-certification"
sys.path.insert(0, str(DB_PACKAGE))
from runtime_contract import (  # noqa: E402
    ContractError,
    atomic_write_json,
    load_json,
    validate_protected_file,
    write_prometheus_textfile,
)

DEFAULT_CONFIG = Path("/etc/codestra/server-a-certification/centrifugo-probe.json")
DEFAULT_METRICS = Path("/var/lib/node_exporter/textfile_collector/codestra_centrifugo_probe.prom")
DEFAULT_EVIDENCE = Path("/opt/codestra/evidence/server-a-certification/centrifugo/LAST_RESULT.json")
FORBIDDEN_QUERY_KEYS = {"token", "access_token", "authorization", "password", "secret"}


def validate_url(value: str, *, field: str, schemes: set[str]) -> urllib.parse.SplitResult:
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in schemes or not parsed.hostname or parsed.username or parsed.password:
        raise ContractError(f"{field} is not an approved absolute URL")
    keys = {key.casefold() for key, _ in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)}
    if keys & FORBIDDEN_QUERY_KEYS:
        raise ContractError(f"{field} must not contain credentials in its query string")
    if parsed.fragment:
        raise ContractError(f"{field} must not contain a fragment")
    return parsed


def load_headers(path_value: str | None) -> dict[str, str]:
    if not path_value:
        return {}
    path = Path(path_value)
    validate_protected_file(path, owner_uid=0)
    headers: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise ContractError("protected WebSocket header file contains an invalid line")
        name, value = line.split(":", 1)
        name = name.strip()
        value = value.strip()
        if not re.fullmatch(r"[A-Za-z0-9-]{1,64}", name) or not value:
            raise ContractError("protected WebSocket header file contains an invalid header")
        if name.casefold() in {"host", "connection", "upgrade", "sec-websocket-key", "sec-websocket-version"}:
            raise ContractError(f"protected WebSocket header may not override {name}")
        headers[name] = value
    return headers


def http_probe(item: dict[str, Any]) -> dict[str, Any]:
    url = str(item.get("url", "")).strip()
    parsed = validate_url(url, field=item.get("id", "HTTP probe"), schemes={"http", "https"})
    expected_statuses = item.get("expected_statuses", [200])
    if not isinstance(expected_statuses, list) or not expected_statuses:
        raise ContractError("expected_statuses must be a non-empty list")
    expected = {int(value) for value in expected_statuses}
    timeout = float(item.get("timeout_seconds", 10))
    if timeout <= 0 or timeout > 30:
        raise ContractError("HTTP probe timeout must be between 0 and 30 seconds")
    request = urllib.request.Request(
        urllib.parse.urlunsplit(parsed),
        method="GET",
        headers={"User-Agent": "codestra-server-a-certification/1"},
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.status
            final_url = response.geturl()
            body = response.read(65537)
    except urllib.error.HTTPError as exc:
        status = exc.code
        final_url = exc.geturl()
        body = exc.read(65537)
    duration = time.monotonic() - started
    if len(body) > 65536:
        raise ContractError(f"HTTP probe response exceeds 64 KiB: {item.get('id')}")
    if status not in expected:
        raise ContractError(f"HTTP probe {item.get('id')} returned {status}; expected {sorted(expected)}")
    final_parsed = validate_url(final_url, field=f"{item.get('id')} final URL", schemes={"http", "https"})
    if item.get("require_https_final") is True and final_parsed.scheme != "https":
        raise ContractError(f"HTTP probe {item.get('id')} downgraded from HTTPS")
    pattern = item.get("body_regex")
    if pattern and re.search(str(pattern), body.decode("utf-8", "replace")) is None:
        raise ContractError(f"HTTP probe body contract failed: {item.get('id')}")
    return {
        "id": item.get("id"),
        "status": "PASS",
        "http_status": status,
        "duration_seconds": round(duration, 6),
        "scheme": parsed.scheme,
        "final_scheme": final_parsed.scheme,
        "host": parsed.hostname,
        "path": parsed.path or "/",
    }


def read_http_headers(sock: socket.socket, limit: int = 32768) -> bytes:
    chunks = bytearray()
    while b"\r\n\r\n" not in chunks:
        block = sock.recv(4096)
        if not block:
            break
        chunks.extend(block)
        if len(chunks) > limit:
            raise ContractError("WebSocket handshake headers exceed the size limit")
    return bytes(chunks)


def websocket_probe(config: dict[str, Any]) -> dict[str, Any]:
    value = str(config.get("url", "")).strip()
    parsed = validate_url(value, field="websocket", schemes={"ws", "wss"})
    origin = str(config.get("origin", "")).strip()
    origin_parsed = validate_url(origin, field="websocket origin", schemes={"http", "https"})
    if origin_parsed.path not in ("", "/") or origin_parsed.query:
        raise ContractError("websocket origin must contain only scheme and authority")
    timeout = float(config.get("timeout_seconds", 10))
    if timeout <= 0 or timeout > 30:
        raise ContractError("WebSocket timeout must be between 0 and 30 seconds")
    headers = load_headers(config.get("protected_headers_file"))
    port = parsed.port or (443 if parsed.scheme == "wss" else 80)
    key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
    path = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    display_host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    host_header = display_host if parsed.port is None else f"{display_host}:{parsed.port}"
    request_lines = [
        f"GET {path} HTTP/1.1",
        f"Host: {host_header}",
        "Upgrade: websocket",
        "Connection: Upgrade",
        f"Sec-WebSocket-Key: {key}",
        "Sec-WebSocket-Version: 13",
        f"Origin: {origin}",
        "User-Agent: codestra-server-a-certification/1",
    ]
    request_lines.extend(f"{name}: {header_value}" for name, header_value in headers.items())
    request = ("\r\n".join(request_lines) + "\r\n\r\n").encode("ascii")
    started = time.monotonic()
    raw = socket.create_connection((parsed.hostname, port), timeout=timeout)
    try:
        raw.settimeout(timeout)
        sock: socket.socket
        if parsed.scheme == "wss":
            context = ssl.create_default_context()
            sock = context.wrap_socket(raw, server_hostname=parsed.hostname)
        else:
            sock = raw
        try:
            sock.sendall(request)
            response = read_http_headers(sock)
        finally:
            if sock is not raw:
                sock.close()
    finally:
        try:
            raw.close()
        except OSError:
            pass
    duration = time.monotonic() - started
    header_text = response.decode("iso-8859-1", "replace")
    lines = header_text.split("\r\n")
    if not lines or not re.fullmatch(r"HTTP/1\.[01] 101(?: .*)?", lines[0]):
        raise ContractError(f"WebSocket handshake returned an unexpected status: {lines[0] if lines else 'empty'}")
    response_headers: dict[str, str] = {}
    for line in lines[1:]:
        if not line or ":" not in line:
            continue
        name, header_value = line.split(":", 1)
        response_headers[name.casefold()] = header_value.strip()
    expected_accept = base64.b64encode(
        hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
    ).decode("ascii")
    if response_headers.get("sec-websocket-accept") != expected_accept:
        raise ContractError("WebSocket handshake has an invalid Sec-WebSocket-Accept value")
    if response_headers.get("upgrade", "").casefold() != "websocket":
        raise ContractError("WebSocket handshake did not confirm the Upgrade header")
    connection_tokens = {
        token.strip().casefold()
        for token in response_headers.get("connection", "").split(",")
        if token.strip()
    }
    if "upgrade" not in connection_tokens:
        raise ContractError("WebSocket handshake did not confirm Connection: Upgrade")
    return {
        "id": "websocket",
        "status": "PASS",
        "http_status": 101,
        "duration_seconds": round(duration, 6),
        "scheme": parsed.scheme,
        "host": parsed.hostname,
        "path": parsed.path or "/",
    }


def publish_metrics(path: Path, results: list[dict[str, Any]], success: bool) -> None:
    by_id = {str(item["id"]): item for item in results}
    lines = [
        "# HELP codestra_centrifugo_probe_success Whether all configured Centrifugo probes passed.",
        "# TYPE codestra_centrifugo_probe_success gauge",
        f"codestra_centrifugo_probe_success {1 if success else 0}",
    ]
    for probe_id in ("internal", "external", "websocket"):
        item = by_id.get(probe_id)
        value = 1 if item and item.get("status") == "PASS" else 0
        duration = float(item.get("duration_seconds", 0)) if item else 0
        lines.extend(
            [
                f'codestra_centrifugo_probe_component_success{{probe="{probe_id}"}} {value}',
                f'codestra_centrifugo_probe_duration_seconds{{probe="{probe_id}"}} {duration:.6f}',
            ]
        )
    write_prometheus_textfile(path, lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--metrics", type=Path, default=DEFAULT_METRICS)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    results: list[dict[str, Any]] = []
    try:
        config = load_json(args.config)
        if config.get("schema") != "codestra.centrifugo-probe.v1":
            raise ContractError("unsupported Centrifugo probe schema")
        http_items = config.get("http_probes")
        if not isinstance(http_items, list) or {item.get("id") for item in http_items} != {"internal", "external"}:
            raise ContractError("Centrifugo probe must define exactly internal and external HTTP checks")
        for item in http_items:
            if item.get("id") == "external":
                parsed = validate_url(str(item.get("url", "")), field="external", schemes={"https"})
                if parsed.scheme != "https":
                    raise ContractError("external Centrifugo probe must use HTTPS")
                if item.get("require_https_final") is not True:
                    raise ContractError("external Centrifugo probe must prohibit HTTPS downgrade")
            results.append(http_probe(item))
        results.append(websocket_probe(config.get("websocket_probe") or {}))
        payload = {
            "schema": "codestra.centrifugo-probe-result.v1",
            "status": "PASS",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "results": results,
            "production_business_writes_executed": False,
        }
        atomic_write_json(args.evidence, payload)
        publish_metrics(args.metrics, results, True)
        print(json.dumps(payload, sort_keys=True))
        return 0
    except (ContractError, OSError, ValueError, json.JSONDecodeError) as exc:
        try:
            publish_metrics(args.metrics, results, False)
            atomic_write_json(
                args.evidence,
                {
                    "schema": "codestra.centrifugo-probe-result.v1",
                    "status": "FAIL",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "error": str(exc)[:1000],
                    "results": results,
                    "production_business_writes_executed": False,
                },
            )
        except Exception:
            pass
        print(f"CENTRIFUGO_PROBE=FAIL:{str(exc)[:1000]}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
