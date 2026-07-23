from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
import yaml


ROOT = Path(__file__).resolve().parents[1]
BACKUP = ROOT / "operations" / "backup"
MONITORING = ROOT / "operations" / "monitoring"


def run(script: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(BACKUP / script)],
        cwd=ROOT,
        env={**os.environ, **env},
        text=True,
        capture_output=True,
        check=False,
    )


class BackupOperationsTests(unittest.TestCase):
    def test_backup_fails_closed_without_protected_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = run(
                "codestra-backup.sh",
                {
                    "CODESTRA_BACKUP_ROOT": directory,
                    "CODESTRA_BACKUP_GPG_RECIPIENT": "",
                    "CODESTRA_BACKUP_REMOTE_HOST": "",
                },
            )
        self.assertEqual(result.returncode, 2)
        self.assertIn("required protected configuration missing", result.stderr)

    def test_freshness_check_passes_for_current_success_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "LAST_SUCCESS"
            marker.write_text(datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "\n")
            result = run(
                "check-backup-state.sh",
                {
                    "CODESTRA_BACKUP_ROOT": directory,
                    "CODESTRA_BACKUP_MAX_AGE_SECONDS": "120",
                    "CODESTRA_BACKUP_MIN_FREE_BYTES": "1",
                },
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("backup_age_seconds", result.stdout)

    def test_cleanup_never_deletes_and_preserves_minimum(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for stamp in ("20260101T000000Z", "20260201T000000Z"):
                backup = root / stamp
                backup.mkdir()
                artifact = backup / "bundle.gpg"
                artifact.write_bytes(stamp.encode())
                digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
                (backup / "SHA256SUMS").write_text(f"{digest}  bundle.gpg\n")
            result = run(
                "cleanup-backups.sh",
                {
                    "CODESTRA_BACKUP_ROOT": directory,
                    "CODESTRA_BACKUP_RETENTION_DAYS": "0",
                    "CODESTRA_BACKUP_MIN_VALID": "2",
                },
            )
            remaining = sorted(path.name for path in root.iterdir())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(remaining, ["20260101T000000Z", "20260201T000000Z"])
        self.assertIn("cleanup_mode=report_only", result.stdout)

    def test_cleanup_refuses_when_verified_minimum_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = run(
                "cleanup-backups.sh",
                {
                    "CODESTRA_BACKUP_ROOT": directory,
                    "CODESTRA_BACKUP_MIN_VALID": "2",
                },
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("refusing cleanup", result.stderr)


class MonitoringGovernanceTests(unittest.TestCase):
    def test_empty_governance_template_fails_closed(self) -> None:
        result = subprocess.run(
            [
                "python3",
                str(MONITORING / "validate-governance.py"),
                str(MONITORING / "governance.env.example"),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("PRODUCTION_ALERT_RECEIVER", result.stderr)
        self.assertIn("FINAL_CHANGE_ID", result.stderr)

    def test_complete_governance_references_validate(self) -> None:
        keys = (
            "PRODUCTION_ALERT_RECEIVER",
            "PRIMARY_ESCALATION_OWNER",
            "SECONDARY_ESCALATION_OWNER",
            "RECOVERY_NOTIFICATION_RECEIVER",
            "ALERT_ESCALATION_POLICY_REFERENCE",
            "API_PERMISSION_APPROVER",
            "DNC_POLICY_REFERENCE",
            "DNC_TEST_APPROVER",
            "RECORDING_POLICY_REFERENCE",
            "RECORDING_RETENTION_POLICY",
            "SECURITY_APPROVER",
            "MAINTENANCE_APPROVER",
            "RISK_ACCEPTANCE_OWNER",
            "PRODUCTION_ACTIVATION_APPROVER",
            "FINAL_CHANGE_ID",
            "FINAL_PRODUCTION_WINDOW",
            "ROLLBACK_DECISION_OWNER",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "governance.env"
            path.write_text("".join(f"{key}=approved-reference-{index}\n" for index, key in enumerate(keys)))
            result = subprocess.run(
                ["python3", str(MONITORING / "validate-governance.py"), str(path)],
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("count=17", result.stdout)

    def test_every_critical_alert_has_an_existing_runbook(self) -> None:
        document = yaml.safe_load(
            (MONITORING / "rules" / "platform.rules.yml").read_text()
        )
        critical = [
            rule
            for group in document["groups"]
            for rule in group["rules"]
            if rule.get("labels", {}).get("severity") == "critical"
        ]
        self.assertTrue(critical)
        for rule in critical:
            reference = rule.get("annotations", {}).get("runbook")
            self.assertIsNotNone(reference, rule["alert"])
            self.assertTrue((ROOT / reference).is_file(), f"{rule['alert']}: {reference}")

    def test_alertmanager_uses_only_protected_receiver_files(self) -> None:
        document = yaml.safe_load(
            (MONITORING / "alertmanager.example.yml").read_text()
        )
        self.assertEqual(len(document["receivers"]), 3)
        for receiver in document["receivers"]:
            for webhook in receiver["webhook_configs"]:
                self.assertNotIn("url", webhook)
                self.assertTrue(webhook["url_file"].startswith("/run/secrets/"))
                self.assertTrue(webhook["send_resolved"])


if __name__ == "__main__":
    unittest.main()
