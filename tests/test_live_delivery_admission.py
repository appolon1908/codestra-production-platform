from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).parents[1]


def run_admission(**overrides: str) -> subprocess.CompletedProcess[str]:
    environment = {
        "PATH": os.environ["PATH"],
        "PYTHONPATH": str(ROOT),
        "LIVE_SMS_DELIVERY": "false",
        "LIVE_EMAIL_DELIVERY": "false",
        "LIVE_PSTN_DIALING": "false",
        **overrides,
    }
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "control_plane_service.admission",
            sys.executable,
            "-c",
            "print('ADMISSION_EXEC=PASS')",
        ],
        env=environment,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def test_admission_executes_only_when_all_channels_are_disabled() -> None:
    result = run_admission()
    assert result.returncode == 0
    assert result.stdout.strip() == "ADMISSION_EXEC=PASS"


def test_admission_denies_each_enabled_or_missing_channel() -> None:
    for flag in ("LIVE_SMS_DELIVERY", "LIVE_EMAIL_DELIVERY", "LIVE_PSTN_DIALING"):
        result = run_admission(**{flag: "true"})
        assert result.returncode != 0
        assert f"admission denied: {flag}" in result.stdout


def test_compose_uses_baked_python_entrypoint_without_host_shell_script() -> None:
    compose = (ROOT / "deploy/control-plane/compose.live-delivery-safety.yaml").read_text()
    assert 'entrypoint: ["/opt/venv/bin/python", "-m", "control_plane_service.admission"]' in compose
    assert "/opt/codestra/safety/live-delivery-admission.sh" not in compose
