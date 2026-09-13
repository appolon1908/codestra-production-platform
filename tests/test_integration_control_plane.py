import hashlib
import hmac
import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

from control_plane_service.core import ControlPlaneError, Store, canonical, credential_matches, validate_envelope, verify_signature
from control_plane_service import server as control_server
from control_plane_service.server import apply_provider_projection, requires_telnexa_projection
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

    def test_private_klyrow_compliance_statuses_reach_dispatch(self):
        for event_type in ("klyrow.email.complained", "klyrow.email.unsubscribed"):
            with self.subTest(event_type=event_type):
                item = validate_envelope(envelope(
                    event_type="klyrow.email.event",
                    idempotency_key=event_type,
                    payload={"event_type": event_type, "message_id": "message-1"},
                ), "klyrow", "event-" + event_type)
                self.assertEqual(item["event_type"], event_type)

    def test_external_odoo_message_callback_skips_missing_local_projection(self):
        item = validate_envelope(envelope(
            event_type="klyrow.email.event",
            payload={"event_type": "klyrow.email.delivered", "message_id": "odoo-mail-2"},
        ), "klyrow", "external-odoo-terminal")
        apply_provider_projection(self.store, "klyrow", item)

    def test_external_telnexa_event_does_not_require_local_projection(self):
        item = validate_envelope(envelope(
            event_type="telnexa.sms.submitted",
            payload={
                "message_id": "external-odoo-message",
                "provider_message_id": "external-carrier-message",
                "status": "submitted",
            },
        ), "telnexa", "external-telnexa-submitted")
        self.assertFalse(requires_telnexa_projection(item))
        self.assertFalse(self.store.ingest(item, reject_event_replay=True).duplicate)
        self.assertIsNone(apply_provider_projection(self.store, "telnexa", item))
        item["metadata"] = {"sms_postgres_authority": True}
        self.assertFalse(requires_telnexa_projection(item))

    def test_private_gateway_projection_marker_is_required_and_bounded(self):
        item = validate_envelope(envelope(
            event_type="telnexa.sms.submitted",
            metadata={"private_gateway_projection_required": True},
        ), "telnexa", "internal-telnexa-submitted")
        self.assertTrue(requires_telnexa_projection(item))
        item["event_type"] = "telnexa.sms.delivered"
        self.assertFalse(requires_telnexa_projection(item))
        item["metadata"] = "invalid"
        self.assertFalse(requires_telnexa_projection(item))

    def test_reconciliation_only_repairs_exact_replay_and_never_ingests_new_event(self):
        message,_ = self.store.create_message({
            "channel":"sms","tenant_id":"tenant-a","customer_id":"customer-a",
            "request_id":"request-reconciliation","correlation_id":"correlation-1",
            "idempotency_key":"message-reconciliation","sender":"CODESTRA",
            "recipient":"+18095550101","source_application":"n8n",
            "classification":"transactional","content_metadata":{},"content":"hello",
            "currency":"USD",
        })
        event_id = "event-reconciliation-only"
        item = validate_envelope({
            "event_type":"telnexa.sms.submitted","event_version":"1.0",
            "occurred_at":"2026-09-02T00:00:00Z","tenant_id":"tenant-a",
            "customer_id":"customer-a","correlation_id":"correlation-1",
            "idempotency_key":event_id,
            "payload":{
                "message_id":message["message_id"],
                "provider_message_id":"provider-reconciliation",
                "status":"submitted",
            },
        }, "telnexa", event_id)
        self.store.ingest(item, reject_event_replay=True)
        self.assertIsNone(self.store.provider_projection_receipt(event_id))

        old_store = control_server.STORE
        old_api_key = os.environ.get("TELNEXA_MIDDLEWARE_API_KEY")
        old_secret = os.environ.get("TELNEXA_WEBHOOK_SECRET")
        control_server.STORE = self.store
        os.environ["TELNEXA_MIDDLEWARE_API_KEY"] = "test-reconciliation-key"
        os.environ["TELNEXA_WEBHOOK_SECRET"] = "test-reconciliation-secret"
        server = control_server.ThreadingHTTPServer(
            ("127.0.0.1", 0), control_server.Handler
        )
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            producer = {
                key: value
                for key, value in item.items()
                if key not in {"event_id", "source"}
            }
            body = json.dumps(producer, separators=(",", ":"), sort_keys=True).encode()
            timestamp = str(int(time.time()))
            signature = hmac.new(
                b"test-reconciliation-secret",
                canonical(timestamp, event_id, "telnexa", body),
                hashlib.sha256,
            ).hexdigest()
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/v1/events",
                data=body,
                method="POST",
                headers={
                    "Authorization":"Bearer test-reconciliation-key",
                    "Content-Type":"application/json",
                    "X-Event-Source":"telnexa",
                    "X-Event-Id":event_id,
                    "X-Timestamp":timestamp,
                    "X-Signature":"sha256=" + signature,
                    "X-Reconciliation-Only":"true",
                },
            )
            with self.assertRaises(urllib.error.HTTPError) as raised:
                urllib.request.urlopen(request, timeout=5)
            self.assertEqual(raised.exception.code, 409)
            receipt = json.loads(raised.exception.read())
            self.assertEqual(receipt["event_id"], event_id)
            self.assertEqual(receipt["projection"]["status"], "accepted")

            missing_id = "event-reconciliation-missing"
            missing = dict(producer, idempotency_key=missing_id)
            missing_body = json.dumps(
                missing, separators=(",", ":"), sort_keys=True
            ).encode()
            missing_signature = hmac.new(
                b"test-reconciliation-secret",
                canonical(timestamp, missing_id, "telnexa", missing_body),
                hashlib.sha256,
            ).hexdigest()
            missing_request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/v1/events",
                data=missing_body,
                method="POST",
                headers={
                    "Authorization":"Bearer test-reconciliation-key",
                    "Content-Type":"application/json",
                    "X-Event-Source":"telnexa",
                    "X-Event-Id":missing_id,
                    "X-Timestamp":timestamp,
                    "X-Signature":"sha256=" + missing_signature,
                    "X-Reconciliation-Only":"true",
                },
            )
            with self.assertRaises(urllib.error.HTTPError) as missing_error:
                urllib.request.urlopen(missing_request, timeout=5)
            self.assertEqual(missing_error.exception.code, 404)
            self.assertFalse(self.store.event_exists(missing_id))
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)
            control_server.STORE = old_store
            if old_api_key is None:
                os.environ.pop("TELNEXA_MIDDLEWARE_API_KEY", None)
            else:
                os.environ["TELNEXA_MIDDLEWARE_API_KEY"] = old_api_key
            if old_secret is None:
                os.environ.pop("TELNEXA_WEBHOOK_SECRET", None)
            else:
                os.environ["TELNEXA_WEBHOOK_SECRET"] = old_secret

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
