#!/usr/bin/env python3
"""Exercise private gateway routes and prove the production mTLS edge."""

from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import os
import socket
import ssl
import stat
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

CONTAINER = os.getenv(
    "PRIVATE_GATEWAY_AUDIT_CONTAINER", "private-app-integration-gateway-1"
)
EDGE_URL = os.getenv(
    "PRIVATE_GATEWAY_AUDIT_EDGE_URL",
    "https://telnexa.internal.codestra.agency:8443/metrics",
)
EDGE_ADDRESS = os.getenv("PRIVATE_GATEWAY_AUDIT_EDGE_ADDRESS", "10.40.0.4")
EDGE_CREDENTIALS = {
    "ca": "PRIVATE_GATEWAY_AUDIT_CA_FILE",
    "certificate": "PRIVATE_GATEWAY_AUDIT_CLIENT_CERT_FILE",
    "key": "PRIVATE_GATEWAY_AUDIT_CLIENT_KEY_FILE",
    "token": "PRIVATE_GATEWAY_AUDIT_BEARER_TOKEN_FILE",
}
ROUTES = {
    "kyqra": [
        "/api/v1/kyqra/jobs",
        "/api/v1/kyqra/results",
        "/api/v1/kyqra/progress",
        "/api/v1/kyqra/failures",
    ],
    "telnexa": [
        "/api/v1/telnexa/inbound",
        "/api/v1/telnexa/dlr",
        "/api/v1/telnexa/failure",
        "/api/v1/telnexa/provider-status",
    ],
    "klyrow": [
        "/api/v1/klyrow/campaigns",
        "/api/v1/klyrow/contacts",
        "/api/v1/klyrow/events",
        "/api/v1/klyrow/bounces",
        "/api/v1/klyrow/complaints",
        "/api/v1/klyrow/unsubscribes",
    ],
}


class EdgeHTTPSConnection(http.client.HTTPSConnection):
    """Connect to the private edge address while preserving hostname/SNI checks."""

    def __init__(self, hostname: str, port: int, address: str, context: ssl.SSLContext):
        super().__init__(hostname, port, timeout=8, context=context)
        self.address = address

    def connect(self) -> None:
        raw_socket = socket.create_connection(
            (self.address, self.port), self.timeout, self.source_address
        )
        try:
            self.sock = self._context.wrap_socket(raw_socket, server_hostname=self.host)
        except Exception:
            raw_socket.close()
            raise


def call(method, path, body=None, headers=None):
    raw = b"" if body is None else json.dumps(body, separators=(",", ":")).encode()
    request_headers = dict(headers or {})
    if raw:
        request_headers.update(
            {"Content-Type": "application/json", "Content-Length": str(len(raw))}
        )
    connection = http.client.HTTPConnection("127.0.0.1", 8080, timeout=5)
    connection.request(method, path, raw or None, request_headers)
    response = connection.getresponse()
    data = response.read()
    connection.close()
    try:
        value = json.loads(data or b"{}")
    except json.JSONDecodeError:
        value = {"body_sha256": hashlib.sha256(data).hexdigest()}
    return response.status, value


def headers(system, event_id, body, stamp=None, bad=False):
    timestamp = str(stamp if stamp is not None else int(time.time()))
    raw = json.dumps(body, separators=(",", ":")).encode()
    prefix = {"kyqra": "X-Kyqra", "telnexa": "X-Telnexa", "klyrow": "X-Klyrow"}[system]
    canonical = (
        timestamp.encode()
        + b"\n"
        + event_id.encode()
        + b"\n"
        + system.encode()
        + b"\n"
        + raw
    )
    signature = hmac.new(
        os.environ[system.upper() + "_WEBHOOK_SECRET"].encode(),
        canonical,
        hashlib.sha256,
    ).hexdigest()
    if bad:
        signature = "0" * 64
    return {
        "Authorization": "Bearer " + os.environ[system.upper() + "_MIDDLEWARE_API_KEY"],
        prefix + "-Timestamp": timestamp,
        prefix + "-Event-Id": event_id,
        prefix + "-Signature": "sha256=" + signature,
        "X-Source-System": system,
    }


def record(items, name, actual, expected, evidence=None):
    items.append(
        {
            "test": name,
            "status": "PASS" if actual == expected else "FAIL",
            "http_status": actual,
            "expected": [expected],
            "evidence": evidence or {},
        }
    )


def inside():
    run = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid.uuid4().hex[:8]
    )
    items = []
    for path in (
        "/health",
        "/api/v1/kyqra/health",
        "/api/v1/telnexa/health",
        "/api/v1/klyrow/health",
    ):
        status_code, value = call("GET", path)
        record(
            items,
            "private gateway " + path,
            status_code,
            200,
            {"response": value},
        )
    for system, paths in ROUTES.items():
        for index, path in enumerate(paths):
            event_id = f"gateway-audit-{system}-{index}-{run}"
            body = {
                "safe_test": True,
                "job_id": f"job-{index}-{run}",
                "message_id": f"message-{index}-{run}",
                "customer_id": "synthetic-customer",
            }
            if path.endswith("/results"):
                body.update(
                    {
                        "record_id": "record-" + run,
                        "source_url": "http://example.invalid/audit",
                        "business_name": "Synthetic Audit",
                        "crawl_timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )
            signed = headers(system, event_id, body)
            status_code, value = call("POST", path, body, signed)
            record(
                items,
                f"{system} route {path} valid signed event",
                status_code,
                202,
                {"event_id": event_id, "response": value},
            )
            status_code, value = call("POST", path, body, signed)
            record(
                items,
                f"{system} route {path} replay rejected",
                status_code,
                409,
                {"event_id": event_id, "response": value},
            )
        path = paths[0]
        event_id = f"gateway-negative-{system}-{run}"
        body = {
            "safe_test": True,
            "job_id": "negative-" + run,
            "message_id": "negative-" + run,
        }
        status_code, value = call(
            "POST", path, body, headers(system, event_id, body, bad=True)
        )
        record(
            items,
            f"{system} invalid HMAC rejected",
            status_code,
            401,
            {"response": value},
        )
        status_code, value = call(
            "POST",
            path,
            body,
            headers(system, event_id + "-stale", body, int(time.time()) - 900),
        )
        record(
            items,
            f"{system} stale timestamp rejected",
            status_code,
            401,
            {"response": value},
        )
        invalid = headers(system, event_id + "-key", body)
        invalid["Authorization"] = "Bearer invalid-audit-key"
        status_code, value = call("POST", path, body, invalid)
        record(
            items,
            f"{system} invalid API key rejected",
            status_code,
            401,
            {"response": value},
        )
    return {
        "schema_version": "private-gateway-audit.v1",
        "run_id": run,
        "safe_mode": True,
        "summary": {
            "pass": sum(item["status"] == "PASS" for item in items),
            "fail": sum(item["status"] == "FAIL" for item in items),
        },
        "tests": items,
    }


def credential_path(variable: str, private: bool) -> Path:
    configured = os.getenv(variable, "").strip()
    if not configured:
        raise ValueError(f"{variable} is required")
    path = Path(configured)
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        metadata = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"{variable} must name a regular non-symlink file")
    if metadata.st_uid != os.geteuid():
        raise ValueError(f"{variable} must be owned by the audit identity")
    if metadata.st_size <= 0 or metadata.st_size > 1_048_576:
        raise ValueError(f"{variable} has an invalid size")
    if metadata.st_mode & stat.S_IWGRP or metadata.st_mode & stat.S_IWOTH:
        raise ValueError(f"{variable} must not be group/world writable")
    if private and metadata.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise ValueError(f"{variable} must be private to the audit identity")
    return path


def read_token(path: Path) -> str:
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        raw = os.read(descriptor, 65_537)
    finally:
        os.close(descriptor)
    if len(raw) > 65_536:
        raise ValueError("PRIVATE_GATEWAY_AUDIT_BEARER_TOKEN_FILE is too large")
    token = raw.decode("utf-8").strip()
    if not token or "\n" in token or "\r" in token:
        raise ValueError("PRIVATE_GATEWAY_AUDIT_BEARER_TOKEN_FILE is invalid")
    return token


def edge_configuration():
    parsed = urlsplit(EDGE_URL)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "telnexa.internal.codestra.agency"
        or parsed.path != "/metrics"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "PRIVATE_GATEWAY_AUDIT_EDGE_URL must be the canonical HTTPS metrics URL"
        )
    if parsed.port != 8443:
        raise ValueError(
            "PRIVATE_GATEWAY_AUDIT_EDGE_URL must use the private mTLS port"
        )
    if EDGE_ADDRESS != "10.40.0.4":
        raise ValueError(
            "PRIVATE_GATEWAY_AUDIT_EDGE_ADDRESS must identify the canonical private edge"
        )
    paths = {
        name: credential_path(variable, name in {"key", "token"})
        for name, variable in EDGE_CREDENTIALS.items()
    }
    return parsed, paths


def edge_request(parsed, context, authorization=None):
    connection = EdgeHTTPSConnection(
        parsed.hostname, parsed.port, EDGE_ADDRESS, context
    )
    request_headers = {
        "Host": parsed.hostname,
        "X-Request-ID": "private-gateway-audit-" + uuid.uuid4().hex,
    }
    if authorization:
        request_headers["Authorization"] = "Bearer " + authorization
    connection.request("GET", parsed.path, headers=request_headers)
    response = connection.getresponse()
    tls_version = connection.sock.version() if connection.sock else "unavailable"
    body = response.read(1_048_577)
    status_code = response.status
    content_type = response.getheader("Content-Type", "")
    connection.close()
    if len(body) > 1_048_576:
        raise ValueError("private gateway metrics response exceeds the audit limit")
    return status_code, content_type, tls_version, body


def edge_tests():
    items = []
    try:
        parsed, paths = edge_configuration()
        rejection_context = ssl.create_default_context(cafile=str(paths["ca"]))
        rejection_context.minimum_version = ssl.TLSVersion.TLSv1_2
        try:
            status_code, _, _, _ = edge_request(parsed, rejection_context)
            rejected = status_code in {400, 401, 403, 496}
            evidence = {"http_status": status_code}
        except (
            ssl.SSLError,
            ConnectionError,
            http.client.HTTPException,
            OSError,
        ) as error:
            rejected = True
            evidence = {"failure_class": type(error).__name__}
        record(
            items,
            "private gateway edge rejects a client without mTLS identity",
            1 if rejected else 0,
            1,
            evidence,
        )

        context = ssl.create_default_context(cafile=str(paths["ca"]))
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(str(paths["certificate"]), str(paths["key"]))
        status_code, content_type, tls_version, body = edge_request(
            parsed, context, read_token(paths["token"])
        )
        metric_present = b"private_gateway_events" in body
        record(
            items,
            "private gateway authenticated /metrics through production mTLS edge",
            status_code if metric_present else 0,
            200,
            {
                "target": EDGE_URL,
                "tls_version": tls_version,
                "content_type": content_type,
                "body_sha256": hashlib.sha256(body).hexdigest(),
                "required_metric_present": metric_present,
            },
        )
    except (ValueError, http.client.HTTPException, OSError) as error:
        record(
            items,
            "private gateway authenticated /metrics through production mTLS edge",
            0,
            200,
            {"failure_class": type(error).__name__},
        )
    return items


def outside():
    result = subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "python", "-", "--inside"],
        input=Path(__file__).read_bytes(),
        capture_output=True,
        timeout=90,
        check=False,
    )
    if result.returncode:
        sys.stderr.buffer.write(result.stderr)
        raise SystemExit(result.returncode)
    value = json.loads(result.stdout)
    value["tests"].extend(edge_tests())
    value["summary"] = {
        "pass": sum(item["status"] == "PASS" for item in value["tests"]),
        "fail": sum(item["status"] == "FAIL" for item in value["tests"]),
    }
    print(json.dumps(value, indent=2, sort_keys=True))
    raise SystemExit(1 if value["summary"]["fail"] else 0)


if __name__ == "__main__":
    if "--inside" in sys.argv:
        print(json.dumps(inside(), indent=2, sort_keys=True))
    else:
        outside()
