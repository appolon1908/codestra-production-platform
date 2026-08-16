import hashlib
import hmac
import json
import os
import tempfile
import time
import unittest

from control_plane_service.core import ControlPlaneError, Store, canonical, credential_matches, validate_envelope, verify_signature
from control_plane_service.worker import once


def envelope(**overrides):
    value = {
        "event_type": "klyrow.email.delivered",
        "event_version": "1.0",
        "occurred_at": "2026-08-15T00:00:00Z",
        "tenant_id": "tenant-a",
        "customer_id": "customer-a",
        "idempotency_key": "delivery-1",
        "payload": {"message_id": "message-1"},
    }
    value.update(overrides)
    return value


class ControlPlaneTests(unittest.TestCase):
    def setUp(self):
        handle, path = tempfile.mkstemp(); os.close(handle); self.path = path; self.store = Store(path)

    def tearDown(self):
        for suffix in ("", "-wal", "-shm"):
            try: os.unlink(self.path + suffix)
            except FileNotFoundError: pass

    def test_hmac_valid_invalid_and_expired(self):
        body = b"{}"; ts = str(int(time.time())); event_id = "event-1"; secret = "unique-test-secret"
        signature = hmac.new(secret.encode(), canonical(ts, event_id, "klyrow", body), hashlib.sha256).hexdigest()
        verify_signature(secret, ts, event_id, "klyrow", body, signature)
        with self.assertRaisesRegex(ControlPlaneError, "invalid_signature"):
            verify_signature(secret, ts, event_id, "klyrow", body, "bad")
        with self.assertRaisesRegex(ControlPlaneError, "expired_timestamp"):
            verify_signature(secret, str(int(ts) - 600), event_id, "klyrow", body, signature)

    def test_plaintext_and_hashed_service_credentials(self):
        secret = "synthetic-service-key"
        digest = hashlib.sha256(secret.encode()).hexdigest()
        self.assertTrue(credential_matches(secret, "", digest))
        self.assertFalse(credential_matches("wrong", "", digest))
        self.assertTrue(credential_matches(secret, secret))

    def test_contract_and_version_rejection(self):
        value = validate_envelope(envelope(), "klyrow", "event-1")
        self.assertEqual(value["source"], "klyrow")
        with self.assertRaisesRegex(ControlPlaneError, "unsupported_event_version"):
            validate_envelope(envelope(event_version="2.0"), "klyrow", "event-2")
        with self.assertRaisesRegex(ControlPlaneError, "unsupported_event_type"):
            validate_envelope(envelope(event_type="telnexa.sms.received"), "klyrow", "event-3")

    def test_private_klyrow_gateway_status_is_normalized_for_dispatch(self):
        item = validate_envelope(envelope(
            event_type="klyrow.email.event",
            payload={"event_type": "klyrow.email.delivered", "message_id": "message-1"},
        ), "klyrow", "event-transport-1")
        self.assertEqual(item["event_type"], "klyrow.email.delivered")
        self.assertEqual(item["metadata"]["transport_event_type"], "klyrow.email.event")

    def test_private_klyrow_gateway_held_status_is_deferred(self):
        item = validate_envelope(envelope(
            event_type="klyrow.email.event",
            payload={"event_type": "klyrow.email.held", "status": "Held", "message_id": "message-2"},
        ), "klyrow", "event-transport-held")
        self.assertEqual(item["event_type"], "klyrow.email.deferred")
        self.assertEqual(item["payload"]["event_type"], "klyrow.email.deferred")
        self.assertEqual(item["payload"]["provider_event_type"], "klyrow.email.held")
        self.assertEqual(item["payload"]["status"], "deferred")

    def test_private_klyrow_gateway_rejects_unknown_inner_status(self):
        with self.assertRaisesRegex(ControlPlaneError, "unsupported_klyrow_email_status"):
            validate_envelope(envelope(
                event_type="klyrow.email.event", payload={"event_type": "klyrow.email.opened"},
            ), "klyrow", "event-transport-2")

    def test_idempotency_replay_and_conflict(self):
        item = validate_envelope(envelope(correlation_id="correlation-1"), "klyrow", "event-1")
        self.assertFalse(self.store.ingest(item).duplicate)
        self.assertTrue(self.store.ingest(item).duplicate)
        retry = validate_envelope(envelope(), "klyrow", "event-retry")
        self.assertTrue(self.store.ingest(retry).duplicate)
        conflicting = dict(item); conflicting["payload"] = {"message_id": "different"}
        with self.assertRaisesRegex(ControlPlaneError, "idempotency_conflict"):
            self.store.ingest(conflicting)
        with self.store.connect() as db:
            self.assertEqual({r["target"] for r in db.execute("SELECT target FROM event_deliveries WHERE event_id='event-1'")}, {"odoo", "n8n"})

    def test_event_exists_tracks_accepted_event_id(self):
        item = validate_envelope(envelope(), "klyrow", "event-1")
        self.assertFalse(self.store.event_exists(item["event_id"]))
        self.store.ingest(item)
        self.assertTrue(self.store.event_exists(item["event_id"]))

    def test_strict_event_replay_rejects_same_id_but_allows_idempotent_retry(self):
        item = validate_envelope(envelope(event_type="customer.updated"), "odoo", "event-1")
        self.store.ingest(item, reject_event_replay=True)
        with self.assertRaisesRegex(ControlPlaneError, "replayed_event_id"):
            self.store.ingest(item, reject_event_replay=True)
        retry = validate_envelope(envelope(event_type="customer.updated"), "odoo", "event-2")
        self.assertTrue(self.store.ingest(retry, reject_event_replay=True).duplicate)

    def test_tenant_isolation_and_correlation(self):
        first = validate_envelope(envelope(correlation_id="trace", tenant_id="tenant-a"), "klyrow", "event-a")
        second = validate_envelope(envelope(correlation_id="trace", tenant_id="tenant-b", idempotency_key="other"), "klyrow", "event-b")
        self.store.ingest(first); self.store.ingest(second)
        self.assertEqual([x["event_id"] for x in self.store.correlation("trace", "tenant-a")], ["event-a"])
        self.assertEqual([x["event_id"] for x in self.store.list_events("tenant-b")], ["event-b"])

    def test_consent_defaults_deny_and_opt_out(self):
        self.assertFalse(self.store.preference_allows("tenant-a", "contact-1", "sms"))
        self.store.set_preference("tenant-a", "contact-1", "sms", "subscribed", "odoo")
        self.assertTrue(self.store.preference_allows("tenant-a", "contact-1", "sms"))
        self.store.set_preference("tenant-a", "contact-1", "sms", "unsubscribed", "telnexa", "STOP")
        self.assertFalse(self.store.preference_allows("tenant-a", "contact-1", "sms"))
        self.assertFalse(self.store.preference_allows("tenant-b", "contact-1", "sms"))

    def test_dlq_replay_pause_and_audit(self):
        item = validate_envelope(envelope(), "klyrow", "event-1"); self.store.ingest(item)
        with self.store.connect() as db: db.execute("UPDATE events SET state='dead_letter' WHERE event_id='event-1'")
        self.assertTrue(self.store.retry("event-1")); self.assertTrue(self.store.pause("klyrow", True))
        self.store.audit("operator", "operations", "event.replayed", "event", "event-1", "tenant-a", item["correlation_id"])
        with self.store.connect() as db: self.assertEqual(db.execute("SELECT count(*) FROM audit").fetchone()[0], 1)

    def test_outbound_worker_safe_by_default(self):
        old = os.environ.get("CONTROL_PLANE_OUTBOUND_ENABLED")
        os.environ["CONTROL_PLANE_OUTBOUND_ENABLED"] = "false"
        try: self.assertEqual(once(), 0)
        finally:
            if old is None: os.environ.pop("CONTROL_PLANE_OUTBOUND_ENABLED", None)
            else: os.environ["CONTROL_PLANE_OUTBOUND_ENABLED"] = old


if __name__ == "__main__": unittest.main()
