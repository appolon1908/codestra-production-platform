import importlib
import hashlib
import hmac
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import uuid


ROOT = Path(__file__).parents[1]


class EmailResellerAdmissionTest(unittest.TestCase):
    def run_admission(self, **overrides):
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
                "email_reseller_service.admission",
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

    def test_admission_executes_only_when_all_delivery_flags_are_disabled(self):
        result = self.run_admission()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "ADMISSION_EXEC=PASS")

    def test_admission_rejects_enabled_or_missing_delivery_flags(self):
        for flag in ("LIVE_SMS_DELIVERY", "LIVE_EMAIL_DELIVERY", "LIVE_PSTN_DIALING"):
            with self.subTest(flag=flag, state="enabled"):
                result = self.run_admission(**{flag: "true"})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f"admission denied: {flag}", result.stdout)

            with self.subTest(flag=flag, state="missing"):
                environment = {
                    "PATH": os.environ["PATH"],
                    "PYTHONPATH": str(ROOT),
                    "LIVE_SMS_DELIVERY": "false",
                    "LIVE_EMAIL_DELIVERY": "false",
                    "LIVE_PSTN_DIALING": "false",
                }
                environment.pop(flag)
                result = subprocess.run(
                    [sys.executable, "-m", "email_reseller_service.admission", sys.executable, "-c", "print('unexpected')"],
                    env=environment,
                    check=False,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f"admission denied: {flag}", result.stdout)

    def test_deployment_uses_baked_admission_and_matching_private_origin(self):
        base = (ROOT / "deploy/email-reseller/compose.yaml").read_text()
        safety = (ROOT / "deploy/email-reseller/compose.live-delivery-safety.yaml").read_text()
        caddy = (ROOT / "operations/caddy/klyrow-events.caddy").read_text()

        self.assertIn('entrypoint: ["/opt/venv/bin/python", "-m", "email_reseller_service.admission"]', safety)
        self.assertIn('command: ["/opt/venv/bin/python", "-m", "email_reseller_service.server"]', safety)
        self.assertNotIn("/opt/codestra/safety/live-delivery-admission.sh", safety)
        self.assertIn('"127.0.0.1:18181:8080"', base)
        self.assertIn("reverse_proxy 127.0.0.1:18181", caddy)


class EmailResellerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        os.environ["EMAIL_DATABASE_PATH"] = self.temp.name + "/email.db"
        os.environ["EMAIL_RATE_PER_MINUTE"] = "3"
        os.environ["KLYROW_WEBHOOK_SECRET"] = "test-klyrow-webhook-secret"
        os.environ["KLYROW_MIDDLEWARE_API_KEY"] = "test-klyrow-api-key"
        import email_reseller_service.server as server
        self.s = importlib.reload(server)
        self.s.initialize()
        self.seed(enabled=1, email_enabled=1, domain_state="active", sender=True)

    def tearDown(self):
        self.temp.cleanup()

    def seed(self, enabled=1, email_enabled=1, domain_state="active", sender=True):
        stamp = self.s.now()
        with self.s.connect() as db:
            db.execute("DELETE FROM sender_identities")
            db.execute("DELETE FROM email_domains")
            db.execute("DELETE FROM customer_limits")
            db.execute("DELETE FROM email_accounts")
            db.execute("INSERT INTO email_accounts VALUES(?,?,?,?,?,?,?,?,?)",
                       ("account-a", "consumer-a", "customer-a", enabled, email_enabled, "USD", 100000, stamp, stamp))
            db.execute("INSERT INTO email_domains VALUES(?,?,?,?,?,?)",
                       ("domain-a", "account-a", "example.test", domain_state, stamp, stamp))
            if sender:
                db.execute("INSERT INTO sender_identities VALUES(?,?,?,?,?,?,?)",
                           ("sender-a", "account-a", "domain-a", "sender@example.test", 1, stamp, stamp))
            db.execute("INSERT INTO customer_limits VALUES(?,?,?,?,?,?)", ("account-a", 2, 3, 100, 1, stamp))

    def payload(self, **changes):
        value = {"from": "sender@example.test", "to": ["one@example.test"], "subject": "Synthetic", "text": "Never delivered"}
        value.update(changes)
        return value

    def rejected(self, code, fn):
        with self.assertRaises(self.s.ApiError) as raised:
            fn()
        self.assertEqual(raised.exception.code, code)

    def create(self, key="key-1", consumer="consumer-a", **changes):
        return self.s.create_message(consumer, key, "correlation-a", self.payload(**changes))

    def klyrow_event(self, value):
        event_id = value.setdefault("event_id", str(uuid.uuid4()))
        value.setdefault("source_system", "klyrow")
        raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        timestamp = str(int(time.time()))
        signature = hmac.new(
            os.environ["KLYROW_WEBHOOK_SECRET"].encode(),
            timestamp.encode() + b"\n" + event_id.encode() + b"\nklyrow\n" + raw,
            hashlib.sha256,
        ).hexdigest()
        headers = {
            "Authorization": "Bearer " + os.environ["KLYROW_MIDDLEWARE_API_KEY"],
            "X-Klyrow-Timestamp": timestamp,
            "X-Klyrow-Event-Id": event_id,
            "X-Klyrow-Signature": "sha256=" + signature,
        }
        return self.s.receive_klyrow_event(raw, headers)

    def test_disabled_account_denied(self):
        self.seed(enabled=0)
        self.rejected("account_disabled", lambda: self.create())

    def test_service_disabled_denied(self):
        self.seed(email_enabled=0)
        self.rejected("email_service_disabled", lambda: self.create())

    def test_unverified_domain_denied(self):
        self.seed(domain_state="pending")
        self.rejected("sender_domain_not_active", lambda: self.create())

    def test_unauthorized_sender_denied(self):
        self.seed(sender=False)
        self.rejected("sender_identity_unauthorized", lambda: self.create())

    def test_too_many_recipients_denied(self):
        self.rejected("too_many_recipients", lambda: self.create(to=["a@example.test", "b@example.test", "c@example.test"]))

    def test_suppression_denied(self):
        stamp = self.s.now()
        with self.s.connect() as db:
            db.execute("INSERT INTO suppressions VALUES(?,?,?,?,?,?,?,?)", ("sup", "account-a", "one@example.test", "hard_bounce", 1, "test", stamp, stamp))
        self.rejected("recipient_suppressed", lambda: self.create())

    def test_headers_and_attachments_rejected(self):
        self.rejected("unsupported_fields:attachments", lambda: self.create(attachments=[]))
        self.rejected("invalid_subject", lambda: self.create(subject="ok\r\nBcc: victim@example.test"))

    def test_body_limits(self):
        self.rejected("text_too_large", lambda: self.create(text="x" * 100001))

    def test_idempotency_returns_same_message(self):
        first, duplicate1 = self.create()
        second, duplicate2 = self.create()
        self.assertFalse(duplicate1)
        self.assertTrue(duplicate2)
        self.assertEqual(first["message_id"], second["message_id"])
        self.assertEqual(first["status"], "accepted")

    def test_idempotency_conflict(self):
        self.create()
        self.rejected("idempotency_conflict", lambda: self.create(subject="different"))

    def test_tenant_isolation(self):
        message, _ = self.create()
        stamp = self.s.now()
        with self.s.connect() as db:
            db.execute("INSERT INTO email_accounts VALUES(?,?,?,?,?,?,?,?,?)", ("account-b", "consumer-b", "customer-b", 1, 1, "USD", 1000, stamp, stamp))
        self.rejected("message_not_found", lambda: self.s.get_message("consumer-b", message["message_id"]))

    def test_ledger_event_and_audit_are_persistent(self):
        message, _ = self.create()
        with self.s.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) n FROM billing_ledger WHERE message_id=?", (message["message_id"],)).fetchone()["n"], 1)
            event = db.execute("SELECT * FROM delivery_events WHERE message_id=?", (message["message_id"],)).fetchone()
            self.assertEqual((event["event_type"], event["canonical_status"], event["correlation_id"]), ("email.accepted", "accepted", "correlation-a"))
            self.assertEqual(db.execute("SELECT COUNT(*) n FROM audit_records WHERE object_id=?", (message["message_id"],)).fetchone()["n"], 1)

    def test_rate_limit(self):
        self.create("one")
        self.create("two")
        self.create("three")
        self.rejected("rate_limit_exceeded", lambda: self.create("four"))

    def test_provider_event_correlation_dedupe_and_suppression(self):
        message, _ = self.create()
        self.assertTrue(self.s.record_provider_event("account-a", message["message_id"], "provider-1", "hard_bounce", "HardBounce", "one@example.test"))
        self.assertFalse(self.s.record_provider_event("account-a", message["message_id"], "provider-1", "hard_bounce", "HardBounce", "one@example.test"))
        current = self.s.get_message("consumer-a", message["message_id"])
        self.assertEqual((current["status"], current["raw_provider_status"], current["correlation_id"]), ("hard_bounce", "HardBounce", "correlation-a"))
        with self.s.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) n FROM suppressions WHERE account_id='account-a' AND kind='hard_bounce' AND active=1").fetchone()["n"], 1)

    def test_klyrow_receiver_accepts_canonical_event_type_and_deduplicates(self):
        message, _ = self.create()
        event = {
            "event_type": "klyrow.email.delivered",
            "message_id": message["message_id"],
            "status": "delivered",
        }
        first, changed = self.klyrow_event(event)
        duplicate, changed_again = self.klyrow_event(event)

        self.assertTrue(changed)
        self.assertEqual(first["status"], "delivered")
        self.assertFalse(changed_again)
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(self.s.get_message("consumer-a", message["message_id"])["status"], "delivered")

    def test_klyrow_receiver_preserves_legacy_event_compatibility(self):
        message, _ = self.create()
        value, changed = self.klyrow_event({
            "event": "email.deferred",
            "message_id": message["message_id"],
            "status": "deferred",
        })

        self.assertTrue(changed)
        self.assertEqual(value["status"], "soft_bounce")

    def test_klyrow_receiver_rejects_conflicting_event_names(self):
        message, _ = self.create()
        self.rejected("conflicting_klyrow_event", lambda: self.klyrow_event({
            "event_type": "klyrow.email.delivered",
            "event": "email.bounced",
            "message_id": message["message_id"],
        }))

    def test_late_provider_event_cannot_regress_terminal_state(self):
        message, _ = self.create()
        self.assertTrue(self.s.record_provider_event("account-a", message["message_id"], "provider-delivered", "delivered", "Delivered"))
        self.assertTrue(self.s.record_provider_event("account-a", message["message_id"], "provider-sent-late", "sent", "Sent"))
        current = self.s.get_message("consumer-a", message["message_id"])
        self.assertEqual((current["status"], current["raw_provider_status"]), ("delivered", "Delivered"))

    def test_balance_reservation_never_goes_negative(self):
        with self.s.connect() as db:
            db.execute("UPDATE email_accounts SET balance_minor=1 WHERE id='account-a'")
        self.create("one")
        self.rejected("insufficient_balance", lambda: self.create("two"))
        with self.s.connect() as db:
            self.assertEqual(db.execute("SELECT balance_minor FROM email_accounts WHERE id='account-a'").fetchone()["balance_minor"], 0)

    def test_unknown_consumer_denied(self):
        self.rejected("customer_account_not_found", lambda: self.create(consumer="missing"))

    def test_version_state_is_safe_and_attributable(self):
        value = self.s.version_state("correlation-a")
        self.assertEqual(value["service"], "email-reseller")
        self.assertEqual(value["api_version"], "v1")
        self.assertEqual(value["correlation_id"], "correlation-a")
        self.assertNotIn("database_url", value)

    def test_capabilities_derive_from_fail_closed_runtime_state(self):
        os.environ["LIVE_EMAIL_DELIVERY"] = "false"
        os.environ["LIVE_SMS_DELIVERY"] = "false"
        os.environ["LIVE_PSTN_DIALING"] = "false"
        value = self.s.capability_state("correlation-a")
        self.assertFalse(value["business_writes_enabled"])
        self.assertFalse(value["external_delivery_enabled"])
        self.assertFalse(value["live_email_enabled"])
        self.assertFalse(value["live_sms_enabled"])
        self.assertFalse(value["live_pstn_enabled"])
        self.assertTrue(value["simulation_enabled"])


if __name__ == "__main__":
    unittest.main()
