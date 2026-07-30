import json
import uuid
from typing import Dict

import pytest

from harness import EVIDENCE, ami_exchange, login, record, secret, state, timestamp


DENIED_ACTIONS = [
    ("Originate", {"Channel": "Local/99999@test-denied", "Context": "test-denied", "Exten": "99999", "Priority": "1"}),
    ("Redirect", {"Channel": "Local/nonexistent-test", "Context": "test-denied", "Exten": "99999", "Priority": "1"}),
    ("Hangup", {"Channel": "Local/nonexistent-test"}),
    ("Command", {"Command": "core show version"}),
    ("UpdateConfig", {"SrcFilename": "manager.conf", "DstFilename": "manager.conf", "Action-000000": "Append", "Cat-000000": "synthetic", "Var-000000": "x", "Value-000000": "y"}),
    ("CreateConfig", {"Filename": "synthetic-test.conf"}),
    ("Reload", {"Module": "manager"}),
    ("ModuleLoad", {"Module": "res_manager_devicestate.so", "LoadType": "reload"}),
    ("CoreRestart", {}),
    ("CoreStop", {}),
    ("QueueAdd", {"Queue": "SYNTHETIC_QUEUE", "Interface": "Local/nonexistent"}),
    ("QueueRemove", {"Queue": "SYNTHETIC_QUEUE", "Interface": "Local/nonexistent"}),
    ("QueuePause", {"Interface": "Local/nonexistent", "Paused": "true"}),
    ("BlindTransfer", {"Channel": "Local/nonexistent-test", "Context": "test-denied", "Exten": "99999"}),
    ("Atxfer", {"Channel": "Local/nonexistent-test", "Context": "test-denied", "Exten": "99999"}),
]
UNEXPOSED_ASTERISK18_ACTIONS = {"CoreRestart", "CoreStop"}


def authenticated_action(action: str, params: Dict[str, str]) -> Dict[str, str]:
    import socket
    import ssl
    from harness import HOST, PORT_OFFSET, RUNTIME, TLS_HOSTNAME
    raw = socket.create_connection((HOST, 15039 + PORT_OFFSET), timeout=4)
    ctx = ssl.create_default_context(cafile=str(RUNTIME / "pki/test-ca.pem"))
    conn = ctx.wrap_socket(raw, server_hostname=TLS_HOSTNAME)
    conn.recv(4096)
    login_body = (
        f"Action: Login\r\nUsername: codestra_event_ro_test\r\nSecret: {secret()}"
        "\r\nEvents: off\r\n\r\n"
    )
    conn.sendall(login_body.encode())
    conn.recv(4096)
    action_id = str(uuid.uuid4())
    body = {"Action": action, "ActionID": action_id, **params}
    conn.sendall(("".join(f"{k}: {v}\r\n" for k, v in body.items()) + "\r\n").encode())
    data = b""
    while b"\r\n\r\n" not in data:
        data += conn.recv(4096)
    conn.close()
    result = {"ActionID": action_id}
    for line in data.decode(errors="replace").splitlines():
        if ": " in line:
            key, value = line.split(": ", 1)
            result[key] = value
    return result


def test_login_ping_and_auth_failures():
    assert login().get("Response") == "Success"
    assert authenticated_action("Ping", {}).get("Response") == "Success"
    assert login(password="definitely-wrong").get("Response") == "Error"
    unknown = ami_exchange(15039, {
        "Action": "Login", "Username": "unknown_synthetic_identity",
        "Secret": "synthetic-wrong", "Events": "off",
    })
    assert unknown.get("Response") == "Error"
    record("ami_read_baseline", result="PASS")


@pytest.mark.parametrize(("action", "params"), DENIED_ACTIONS)
def test_write_action_explicitly_denied_without_side_effect(action, params):
    before = state()
    started = timestamp()
    response = authenticated_action(action, params)
    after = state()
    sanitized = {k: v for k, v in response.items() if k.lower() not in {"secret", "key"}}
    message = response.get("Message", "").lower()
    denied = response.get("Response") == "Error" and "permission" in message
    unexposed = (
        action in UNEXPOSED_ASTERISK18_ACTIONS
        and response.get("Response") == "Error"
        and "invalid/unknown command" in message
    )
    unchanged = before == after
    row = {
        "ACTION": action,
        "ACTION_ID": response.get("ActionID", ""),
        "TEST_TIMESTAMP_UTC": started,
        "EXPECTED_RESULT": "UNEXPOSED" if action in UNEXPOSED_ASTERISK18_ACTIONS else "DENIED",
        "ACTUAL_RESULT": (
            "DENIED" if denied else "UNEXPOSED" if unexposed
            else response.get("Response", "NO_RESPONSE")
        ),
        "AMI_RESPONSE_SANITIZED": sanitized,
        "CHANNEL_COUNT_BEFORE": before["channels"],
        "CHANNEL_COUNT_AFTER": after["channels"],
        "CONFIG_CHECKSUM_BEFORE": before["config"],
        "CONFIG_CHECKSUM_AFTER": after["config"],
        "SERVICE_PID_BEFORE": before["pid"],
        "SERVICE_PID_AFTER": after["pid"],
        "SIDE_EFFECT_COUNT": 0 if unchanged else 1,
        "TEST_RESULT": "PASS" if (denied or unexposed) and unchanged else "FAIL",
    }
    EVIDENCE.mkdir(exist_ok=True)
    with (EVIDENCE / "ami-denial.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")
    assert denied or unexposed, sanitized
    assert unchanged, row
