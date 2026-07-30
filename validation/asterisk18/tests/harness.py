import hashlib
import json
import os
import socket
import ssl
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
EVIDENCE = ROOT / "evidence"
HOST = os.environ.get("HARNESS_HOST", "127.0.0.1")
PORT_OFFSET = int(os.environ.get("HARNESS_PORT_OFFSET", "0"))
TLS_HOSTNAME = "asterisk-ami.test.invalid"


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def record(name: str, **values: object) -> None:
    EVIDENCE.mkdir(exist_ok=True)
    payload = {"test": name, "timestamp_utc": timestamp(), **values}
    with (EVIDENCE / "results.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def secret() -> str:
    return (RUNTIME / "ami.secret").read_text(encoding="utf-8").strip()


def ami_exchange(port: int, fields: Dict[str, str], tls: bool = True) -> Dict[str, str]:
    raw = socket.create_connection((HOST, port + PORT_OFFSET), timeout=4)
    if tls:
        ctx = ssl.create_default_context(cafile=str(RUNTIME / "pki/test-ca.pem"))
        raw = ctx.wrap_socket(raw, server_hostname=TLS_HOSTNAME)
    with raw:
        raw.settimeout(4)
        raw.recv(4096)
        body = "".join(f"{key}: {value}\r\n" for key, value in fields.items()) + "\r\n"
        raw.sendall(body.encode())
        response = b""
        while b"\r\n\r\n" not in response:
            response += raw.recv(4096)
    parsed = {}  # type: Dict[str, str]
    for line in response.decode(errors="replace").splitlines():
        if ": " in line:
            key, value = line.split(": ", 1)
            parsed[key] = value
    return parsed


def login(port: int = 15039, password: Optional[str] = None) -> Dict[str, str]:
    return ami_exchange(port, {
        "Action": "Login",
        "ActionID": str(uuid.uuid4()),
        "Username": "codestra_event_ro_test",
        "Secret": secret() if password is None else password,
        "Events": "on",
    })


def docker_exec(command: str) -> str:
    result = subprocess.run(
        ["docker", "compose", "-f", str(ROOT / "compose.yaml"), "exec", "-T",
         "--user", "10001:10001", "asterisk",
         "sh", "-ec", command],
        check=True, text=True, capture_output=True,
    )
    return result.stdout.strip()


def state() -> Dict[str, str]:
    return {
        "channels": docker_exec("asterisk -rx 'core show channels count' | tr '\\n' ' '"),
        "config": docker_exec("sha256sum /etc/asterisk/*.conf | sha256sum | cut -d' ' -f1"),
        "pid": docker_exec("cat /var/run/asterisk/asterisk.pid"),
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()
