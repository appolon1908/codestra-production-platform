"""Exercise the actual shell guard before secrets, Python or an application run."""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FLAGS = (
    "ENABLE_VICIDIAL_WRITES",
    "ENABLE_PROVISIONING",
    "ENABLE_AGENT_SYNC",
    "ENABLE_LEAD_PUBLICATION",
    "ENABLE_IVR_CALLBACKS",
    "ENABLE_WARM_TRANSFER",
    "ENABLE_PSTN_DIALING",
    "ENABLE_SMS_DELIVERY",
    "ENABLE_EMAIL_DELIVERY",
    "ENABLE_EXTERNAL_DELIVERY",
    "ENABLE_PRODUCTION_DIALING",
    "ENABLE_LIVE_CALL_CONTROL",
    "ENABLE_IVR_ROUTING",
    "ENABLE_CAMPAIGN_SYNC",
    "ENABLE_APPT_PREP",
    "ENABLE_AI_ACTIONS",
)


@pytest.mark.parametrize("flag", FLAGS)
@pytest.mark.parametrize("value", ["true", "1", "TRUE", ""])
def test_every_effect_gate_requires_literal_false(flag, value, tmp_path):
    # A nonexistent secret proves no later startup gate was needed to reject it.
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("ENABLE_")
    }
    env.update({name: "false" for name in FLAGS})
    env.update({flag: value, "CODESTRA_ADAPTER_HMAC_FILE": str(tmp_path / "absent")})
    result = subprocess.run(
        ["/bin/sh", str(ROOT / "vicidial/docker/entrypoint.sh"), "false"],
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 78
    assert f"{flag} must remain false" in result.stderr
    assert "HMAC" not in result.stderr


def test_entrypoint_covers_every_declared_effect_switch():
    text = (ROOT / "vicidial/config/adapter.env.example").read_text()
    declared = {
        line.split("=", 1)[0]
        for line in text.splitlines()
        if line.startswith("ENABLE_")
    }
    assert declared <= set(FLAGS)
