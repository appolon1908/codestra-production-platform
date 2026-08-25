import importlib.machinery
import importlib.util
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "operations" / "vicidial-operator"
SOURCE = PACKAGE / "codestra-vicidial-operator"


def load_operator():
    loader = importlib.machinery.SourceFileLoader("vicidial_safety_operator", str(SOURCE))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_approved_action_and_schema_are_exact(monkeypatch):
    operator = load_operator()
    output = {
        "core show channels count": "0 active channels\n0 active calls\n",
        "bridge show all": "0 bridges listed.\n",
        "pjsip show contacts": "Objects found: 2\n",
        "pjsip show endpoints": "Objects found: 3\n",
        "pjsip show registrations": "Objects found: 1\n",
    }

    def fake_run(command, **kwargs):
        assert command[:2] == [operator.ASTERISK, "-rx"]
        assert command[2] in output
        assert kwargs["stdin"] is subprocess.DEVNULL
        return subprocess.CompletedProcess(command, 0, output[command[2]], "")

    monkeypatch.setattr(operator.subprocess, "run", fake_run)
    result = operator.safety_status()
    assert set(result) == operator.ALLOWED_FIELDS
    assert result["ACTIVE_CALLS"] == 0
    assert result["ACTIVE_CHANNELS"] == 0
    assert result["SIP_REGISTRATION_CLASSIFICATION"] == "IDLE_INFRASTRUCTURE"
    assert all(isinstance(result[name], int) for name in operator.ALLOWED_FIELDS if name != "SIP_REGISTRATION_CLASSIFICATION")


def test_nonzero_activity_is_not_classified_safe(monkeypatch):
    operator = load_operator()
    values = iter(
        [
            "2 active channels\n1 active calls\n",
            "Objects found: 1\n",
            "1 bridges listed.\n",
            "Objects found: 2\n",
            "Objects found: 3\n",
        ]
    )
    monkeypatch.setattr(operator, "run_asterisk", lambda command: next(values))
    result = operator.safety_status()
    assert result["ACTIVE_CALLS"] == 1
    assert result["ACTIVE_CHANNELS"] == 2
    assert result["SIP_REGISTRATION_CLASSIFICATION"] == "ACTIVE_CALL_DEPENDENT"


def test_output_cannot_contain_asterisk_or_sip_secrets(monkeypatch, capsys):
    operator = load_operator()
    monkeypatch.setattr(operator.os, "geteuid", lambda: 0)
    monkeypatch.setattr(operator.sys, "argv", [str(SOURCE), operator.SAFETY_ACTION])
    monkeypatch.setattr(
        operator,
        "safety_status",
        lambda: {
            "ACTIVE_CALLS": 0,
            "ACTIVE_CHANNELS": 0,
            "ACTIVE_BRIDGES": 0,
            "PJSIP_CONTACTS": 0,
            "PJSIP_ENDPOINTS": 0,
            "PJSIP_REGISTRATIONS": 0,
            "SIP_REGISTRATION_CLASSIFICATION": "NONE",
        },
    )
    assert operator.main() == 0
    value = capsys.readouterr().out
    assert set(json.loads(value)) == operator.ALLOWED_FIELDS
    for forbidden in ("password", "secret", "username", "caller", "dial"):
        assert forbidden not in value.lower()


def test_unsupported_actions_fail_closed(monkeypatch):
    operator = load_operator()
    monkeypatch.setattr(operator.os, "geteuid", lambda: 0)
    for arguments in ([str(SOURCE)], [str(SOURCE), "status", "extra"], [str(SOURCE), "sh"], [str(SOURCE), "../../bin/sh"]):
        monkeypatch.setattr(operator.sys, "argv", arguments)
        assert operator.main() == 64


def test_sudoers_grants_only_the_exact_operator_action():
    value = (PACKAGE / "codestra-vicidial-safety-status.sudoers").read_text()
    assert "/usr/local/sbin/codestra-vicidial-operator telephony-safety-status" in value
    assert "/usr/sbin/asterisk" not in value
    assert "*" not in value
    assert " ALL=(root) NOPASSWD: ALL" not in value


def test_installer_backs_up_and_validates_before_atomic_install():
    value = (PACKAGE / "install-vicidial-safety-status.sh").read_text()
    assert "BACKUP_CURRENT_OPERATOR=PASS" in value
    assert "BACKUP_CURRENT_SUDOERS=PASS" in value
    assert "visudo -cf" in value
    assert "mv -f" in value
    assert "asterisk" not in value
