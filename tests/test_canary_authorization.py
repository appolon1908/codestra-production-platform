from __future__ import annotations

import datetime as dt
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "operations/canary/validate-authorization.py"
TEMPLATE = ROOT / "operations/canary/canary-authorization.env.example"


def fields() -> dict[str, str]:
    values = {}
    for line in TEMPLATE.read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    now = dt.datetime.now(dt.timezone.utc)
    for key in values:
        values[key] = values[key] or f"approved-reference-{key.lower()}"
    values.update(
        {
            "SIGNED_CANARY_APPROVAL": "VALIDATED",
            "CANARY_START": (now - dt.timedelta(minutes=1)).isoformat(),
            "CANARY_END": (now + dt.timedelta(minutes=10)).isoformat(),
            "CANARY_TIMEZONE": "America/Santo_Domingo",
            "MAX_CALLS": "1",
            "MAX_CONCURRENT_CALLS": "1",
            "MAX_CALL_DURATION_SECONDS": "120",
            "MAX_EVENTS": "20",
            "RETRY_CALLS_AUTHORIZED": "NO",
            "ZERO_MATCH_APPROVAL_EXPIRATION": (now + dt.timedelta(minutes=10)).isoformat(),
        }
    )
    return values


def run(values: dict[str, str]) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "authorization.env"
        path.write_text("".join(f"{key}={value}\n" for key, value in values.items()))
        return subprocess.run(
            ["python3", str(VALIDATOR), str(path)],
            text=True,
            capture_output=True,
            check=False,
        )


class CanaryAuthorizationTests(unittest.TestCase):
    def test_complete_active_one_call_scope_validates_without_echoing_values(self) -> None:
        values = fields()
        result = run(values)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("authorization_state=VALIDATED", result.stdout)
        self.assertNotIn(values["AUTHORIZED_CALLER_ID"], result.stdout)
        self.assertNotIn(values["PROTECTED_DESTINATION_REFERENCE"], result.stdout)

    def test_missing_approval_fails_closed(self) -> None:
        values = fields()
        values["CANARY_SIGNATURE_REFERENCE"] = ""
        result = run(values)
        self.assertEqual(result.returncode, 2)
        self.assertIn("authorization_state=NOT_PROVIDED", result.stderr)

    def test_second_call_or_retry_scope_is_rejected(self) -> None:
        for key, value in (("MAX_CALLS", "2"), ("RETRY_CALLS_AUTHORIZED", "YES")):
            with self.subTest(key=key):
                values = fields()
                values[key] = value
                result = run(values)
                self.assertEqual(result.returncode, 2)
                self.assertIn("authorization_state=SCOPE_MISMATCH", result.stderr)

    def test_expired_window_fails_closed(self) -> None:
        values = fields()
        now = dt.datetime.now(dt.timezone.utc)
        values["CANARY_START"] = (now - dt.timedelta(minutes=20)).isoformat()
        values["CANARY_END"] = (now - dt.timedelta(minutes=10)).isoformat()
        result = run(values)
        self.assertEqual(result.returncode, 2)
        self.assertIn("authorization_state=EXPIRED", result.stderr)


if __name__ == "__main__":
    unittest.main()
