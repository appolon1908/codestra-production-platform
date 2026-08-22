import os
import tempfile
import unittest
from unittest.mock import patch

from control_plane_service.core import Store
from control_plane_service.providers import ProviderResult
from control_plane_service.worker import dispatch_messages


class CodWebOutWorkerGateTests(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp()
        os.close(handle)
        self.store = Store(self.path)
        self.previous = dict(os.environ)
        os.environ.update({
            "CONTROL_PLANE_DB": self.path,
            "CONTROL_PLANE_OUTBOUND_ENABLED": "true",
            "CAMPAIGN_SCOPED_CHANNEL_GATES_ENABLED": "true",
            "COD_WEB_OUT_EMAIL_ENABLED": "true",
            "COD_WEB_OUT_EMAIL_MODE": "CANARY",
            "COD_WEB_OUT_EMAIL_ALLOWLIST_REQUIRED": "true",
            "COD_WEB_OUT_CANARY_RECIPIENT": "approved@example.invalid",
            "GLOBAL_EMAIL_PRODUCTION": "false",
            "SMS_PRODUCTION": "false",
        })

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.previous)
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(self.path + suffix)
            except FileNotFoundError:
                pass

    def queue(self, *, campaign_id="COD-WEB-OUT", recipient="approved@example.invalid", key="canary-1"):
        value = {
            "channel": "email",
            "tenant_id": "COD",
            "customer_id": "customer-1",
            "request_id": "request-1",
            "correlation_id": "correlation-1",
            "idempotency_key": key,
            "sender": "sender@example.invalid",
            "recipient": recipient,
            "source_application": "n8n",
            "campaign_id": campaign_id,
            "classification": "transactional",
            "content_metadata": {"template_id": "canary"},
            "content": "canary",
            "currency": "USD",
        }
        return self.store.create_message(value)[0]

    def test_worker_submits_only_exact_campaign_tenant_and_recipient(self):
        message = self.queue()
        captured = []

        def fake_submit(value):
            captured.append(value)
            return ProviderResult("provider-1", "accepted", "accepted")

        with patch("control_plane_service.worker.submit", side_effect=fake_submit):
            self.assertEqual(dispatch_messages(), 1)

        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]["campaign_id"], "COD-WEB-OUT")
        self.assertEqual(captured[0]["tenant_id"], "COD")
        self.assertEqual(captured[0]["recipient"], "approved@example.invalid")
        self.assertEqual(self.store.get_message(message["message_id"], "COD")["status"], "accepted")

    def test_worker_rejects_wrong_campaign_before_provider(self):
        message = self.queue(campaign_id="MONEYBEE", key="wrong-campaign")
        with patch("control_plane_service.worker.submit") as provider:
            self.assertEqual(dispatch_messages(), 1)
            provider.assert_not_called()
        result = self.store.get_message(message["message_id"], "COD")
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["provider_error_code"], "campaign_email_gate_denied")

    def test_worker_rejects_wrong_recipient_before_provider(self):
        message = self.queue(recipient="other@example.invalid", key="wrong-recipient")
        with patch("control_plane_service.worker.submit") as provider:
            self.assertEqual(dispatch_messages(), 1)
            provider.assert_not_called()
        result = self.store.get_message(message["message_id"], "COD")
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["provider_error_code"], "canary_recipient_denied")

    def test_disabled_campaign_gate_fails_closed_before_provider(self):
        message = self.queue(key="disabled-gate")
        os.environ["CAMPAIGN_SCOPED_CHANNEL_GATES_ENABLED"] = "false"
        with patch("control_plane_service.worker.submit") as provider:
            self.assertEqual(dispatch_messages(), 1)
            provider.assert_not_called()
        result = self.store.get_message(message["message_id"], "COD")
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["provider_error_code"], "campaign_channel_gates_disabled")
