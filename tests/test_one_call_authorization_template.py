"""Source-only checks: this template must never imply live authorization."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = "VICIDIAL_ONE_CALL_PRODUCTION_AUTHORIZATION_PACKAGE.example.md"
PRIVATE = "VICIDIAL_ONE_CALL_PRODUCTION_AUTHORIZATION_PACKAGE.md"


class OneCallAuthorizationTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (ROOT / TEMPLATE).read_text(encoding="utf-8")
        cls.pairs = re.findall(r"^([A-Z][A-Z0-9_]*)=(.*)$", cls.text, re.MULTILINE)
        cls.values = dict(cls.pairs)

    def test_no_duplicate_keys_or_preapproved_results(self):
        self.assertEqual(len(self.pairs), len(self.values))
        for key, value in self.pairs:
            with self.subTest(key=key):
                self.assertNotIn(value, {"YES", "PASS", "APPROVED", "VALIDATED",
                                        "APPROVED_FOR_EXACTLY_ONE_MANUAL_CALL"})

    def test_default_decision_blocks_call_and_limited_production(self):
        expected = {
            "PACKAGE_STATE": "DRAFT_BLOCKED", "PACKAGE_SIGNED": "NO",
            "RUNTIME_STATE_VERIFIED_THIS_SESSION": "NO",
            "CHANGE_STATUS": "PENDING", "AUTHORIZATION_DECISION": "BLOCKED",
            "ALL_MANDATORY_FIELDS_COMPLETE": "NO",
            "ALL_REQUIRED_APPROVALS_VALID": "NO",
            "LIMITED_PRODUCTION_DECISION": "NO_GO",
            "REQUIRED_BASELINE_ENABLE_VICIDIAL_WRITES": "false",
            "REQUIRED_BASELINE_SEND_EVENTS": "false",
        }
        for key, value in expected.items():
            with self.subTest(key=key):
                self.assertEqual(self.values[key], value)

    def test_one_manual_attempt_and_exclusions_are_fixed(self):
        for key, value in {
            "DIAL_METHOD": "MANUAL", "MAX_HOPPER": "1", "MAX_CALLS": "1",
            "MAX_CONCURRENT_CALLS": "1", "RETRY_CALLS_AUTHORIZED": "NO",
            "PREDICTIVE_DIALING": "DENIED", "AUTOMATED_DIALING": "DENIED",
            "ROUTE_FALLBACK": "DENIED", "HISTORICAL_REPLAY_AUTHORIZED": "NO",
        }.items():
            with self.subTest(key=key):
                self.assertEqual(self.values[key], value)
        for key in ("CUSTOMER_LISTS_PERMISSION", "UNRELATED_CAMPAIGNS_PERMISSION",
                    "CALLBACK_PERMISSION", "APPOINTMENT_PERMISSION", "TRANSFER_PERMISSION",
                    "SMS_PERMISSION", "EMAIL_PERMISSION", "VOICEMAIL_DROP_PERMISSION",
                    "CUSTOMER_WEBHOOK_PERMISSION", "N8N_CUSTOMER_COMMUNICATION",
                    "RECORDING_CONTENT_ACCESS_PERMISSION"):
            with self.subTest(key=key):
                self.assertEqual(self.values[key], "DENIED")

    def test_unverified_targets_and_policies_are_not_invented(self):
        for key in ("PILOT_CAMPAIGN_ID", "PILOT_LIST_ID", "APPROVED_OPERATOR_ID",
                    "APPROVED_EXTENSION", "DESTINATION_ALLOWLIST_E164",
                    "DESTINATION_FINGERPRINT_SHA256", "APPROVED_CALLER_ID_DID",
                    "APPROVED_SIP_TRUNK_ID", "ACTIVATION_START_UTC", "ACTIVATION_END_UTC",
                    "CONSENT_EVIDENCE_REFERENCE_FOR_DESTINATION",
                    "PERMANENT_DNC_CHECK_REFERENCE", "RECORDING_POLICY_ID_VERSION",
                    "RECORDING_ENABLED_FOR_CANARY", "APPROVAL_MANIFEST_SHA256",
                    "SERVER_A_EXISTING_APPROVED_TARGET", "SERVER_B_EXISTING_APPROVED_TARGET"):
            with self.subTest(key=key):
                self.assertEqual(self.values[key], "")
        self.assertIsNone(re.search(r"\+[1-9][0-9]{7,14}\b", self.text))

    def test_all_named_approval_roles_are_unassigned(self):
        for role in ("BUSINESS", "COMPLIANCE_PRIVACY", "SECURITY", "OPERATIONS",
                     "TELEPHONY", "ODOO", "N8N", "RELEASE", "ROLLBACK"):
            for suffix in ("APPROVER_NAME", "APPROVAL_REFERENCE", "APPROVAL_TIMESTAMP_UTC"):
                with self.subTest(role=role, suffix=suffix):
                    self.assertEqual(self.values[f"{role}_{suffix}"], "")

    def test_fresh_preflight_and_reconciliation_are_unclaimed(self):
        for key in ("SERVER_A_READY_FOR_CALL", "SERVER_B_READY_FOR_CALL",
                    "SERVER_A_SERVER_B_MANIFEST_HASH_MATCH", "PROVENANCE_ALL_COMPONENTS",
                    "OFFSERVER_BACKUP_AND_RESTORE_BOTH_SERVERS",
                    "MONITORING_AND_ALERT_RECOVERY_BOTH_SERVERS",
                    "ODOO_MAPPING_DISABLED_DRY_RUN", "N8N_INACTIVE_NO_MESSAGE_CANARY",
                    "HISTORICAL_EVENTS_LOCKED_NO_REPLAY", "CONSENT_AND_DNC_RECHECK",
                    "CURRENT_TIME_INSIDE_APPROVED_WINDOW", "ROLLBACK_AUTHORITIES_AVAILABLE",
                    "CALL_RECONCILIATION_RESULT"):
            with self.subTest(key=key):
                self.assertEqual(self.values[key], "NOT_TESTED")
        for key in ("ASTERISK_UNIQUEID", "VICIDIAL_CALL_ID", "MIDDLEWARE_CORRELATION_ID",
                    "MIDDLEWARE_EVENT_IDS", "ODOO_CALL_RECORD_ID", "CALL_ATTEMPTS_CONSUMED",
                    "FAIL_CLOSED_RESTORED_AT_UTC", "FINAL_EVIDENCE_SHA256"):
            with self.subTest(key=key):
                self.assertEqual(self.values[key], "")

    @unittest.skipUnless(shutil.which("git"), "git required to test ignore behavior")
    def test_private_package_and_backup_copies_are_ignored_not_example(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "--quiet", str(root)], check=True)
            (root / ".gitignore").write_text((ROOT / ".gitignore").read_text())
            for name in (PRIVATE, PRIVATE + ".bak", "nested/" + PRIVATE):
                with self.subTest(path=name):
                    result = subprocess.run(["git", "-C", str(root), "check-ignore", "--quiet", name])
                    self.assertEqual(result.returncode, 0)
            result = subprocess.run(["git", "-C", str(root), "check-ignore", "--quiet", TEMPLATE])
            self.assertEqual(result.returncode, 1)


if __name__ == "__main__":
    unittest.main()
