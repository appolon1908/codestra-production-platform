import hashlib
import hmac
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import urllib.error
from unittest.mock import patch

from odoo.exceptions import ValidationError

from ..models import hardening as hardening_module
from .test_outbox import TestCodestraCrmCallFollowupOutbox


class _Response:
    def __init__(self, status, body):
        self.status = status
        self._body = body

    def read(self, _limit=-1):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _Opener:
    def __init__(self, *, response=None, error=None):
        self.response = response
        self.error = error
        self.request = None
        self.timeout = None

    def open(self, request, timeout):
        self.request = request
        self.timeout = timeout
        if self.error:
            raise self.error
        return self.response


class TestCodestraCrmCallFollowupAutomationHardening(
    TestCodestraCrmCallFollowupOutbox
):
    def _config(self):
        return {
            "target_url": "https://middleware.example.test/api/v1/events/odoo",
            "target_host": "middleware.example.test",
            "tenant_id": "test-tenant",
            "timeout": 5.0,
            "api_key": "a" * 32,
            "webhook_secret": "s" * 32,
        }

    def _event(self):
        return self.outbox.enqueue_followup_events(self.followup)[0]

    def _receipt(
        self,
        event,
        *,
        status,
        event_id,
        duplicate,
        state="queued",
    ):
        value = {
            "event_id": event_id,
            "correlation_id": event._stable_correlation_id(),
            "duplicate": duplicate,
            "state": state,
            "projection": None,
        }
        return status, json.dumps(
            value,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

    def test_secret_reader_rejects_symbolic_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.write_text("x" * 32, encoding="utf-8")
            target.chmod(0o600)
            link = root / "secret"
            os.symlink(target, link)
            self.env["ir.config_parameter"].sudo().set_param(
                "codestra.test.secret_file",
                str(link),
            )

            with self.assertRaisesRegex(
                ValidationError,
                "cannot be opened safely",
            ):
                self.outbox._read_secret_file(
                    "codestra.test.secret_file",
                    minimum_length=16,
                )

    def test_secret_reader_rejects_writable_secret_files(self):
        with tempfile.TemporaryDirectory() as directory:
            secret = Path(directory) / "secret"
            secret.write_text("x" * 32, encoding="utf-8")
            secret.chmod(0o622)
            self.env["ir.config_parameter"].sudo().set_param(
                "codestra.test.secret_file",
                str(secret),
            )

            with self.assertRaisesRegex(
                ValidationError,
                "group- or world-writable",
            ):
                self.outbox._read_secret_file(
                    "codestra.test.secret_file",
                    minimum_length=16,
                )

    def test_target_url_rejects_query_credentials_before_secret_read(self):
        parameters = self.env["ir.config_parameter"].sudo()
        parameters.set_param(
            "codestra.call_followup_automation.target_url",
            "https://middleware.example.test/events?token=forbidden",
        )
        parameters.set_param(
            "codestra.call_followup_automation.tenant_id",
            "test-tenant",
        )
        parameters.set_param(
            "codestra.call_followup_automation.allowed_hosts",
            "middleware.example.test",
        )

        with self.assertRaisesRegex(
            ValidationError,
            "query string",
        ):
            self.outbox._delivery_config()

    def test_sequential_enqueue_reuses_existing_event_without_insert_error(self):
        first = self.outbox.enqueue_followup_events(self.followup)
        second = self.outbox.enqueue_followup_events(self.followup)

        self.assertEqual(
            [record.id for record in first],
            [record.id for record in second],
        )

    def test_manager_can_dead_letter_through_internal_write_boundary(self):
        event = self._event()

        event.with_user(self.manager).action_mark_dead()

        self.assertEqual(event.state, "dead")
        self.assertEqual(event.last_error, "manually_dead_lettered")

    def test_wire_envelope_uses_one_accepted_namespace_and_stable_metadata(self):
        event = self._event()
        config = self._config()
        first = event._envelope(config, event._transport_event_id(1))
        second = event._envelope(config, event._transport_event_id(2))

        self.assertEqual(first["event_type"], "call_followup.completed")
        self.assertTrue(first["occurred_at"].endswith("Z"))
        self.assertEqual(first["metadata"]["source"], "odoo")
        self.assertEqual(
            first["metadata"]["logical_event_id"],
            event.event_id,
        )
        self.assertNotIn("delivery_attempt", first["metadata"])
        first_without_transport = dict(first)
        second_without_transport = dict(second)
        first_without_transport.pop("event_id")
        second_without_transport.pop("event_id")
        self.assertEqual(first_without_transport, second_without_transport)
        self.assertNotEqual(first["event_id"], second["event_id"])

    def test_hmac_uses_odoo_source_and_transport_event_nonce(self):
        event = self._event()
        config = self._config()
        transport_event_id = event._transport_event_id(1)
        status, body = self._receipt(
            event,
            status=202,
            event_id=transport_event_id,
            duplicate=False,
        )
        opener = _Opener(response=_Response(status, body))

        with patch.object(
            hardening_module.urllib.request,
            "build_opener",
            return_value=opener,
        ):
            result = event._post_event(config)

        self.assertEqual(result["receipt"], "accepted")
        headers = {
            key.lower(): value
            for key, value in opener.request.header_items()
        }
        self.assertEqual(headers["x-event-id"], transport_event_id)
        self.assertEqual(headers["x-event-source"], "odoo")
        self.assertEqual(
            headers["x-correlation-id"],
            event._stable_correlation_id(),
        )
        canonical = b"\n".join(
            (
                headers["x-timestamp"].encode("ascii"),
                transport_event_id.encode("utf-8"),
                b"odoo",
                opener.request.data,
            )
        )
        expected = hmac.new(
            config["webhook_secret"].encode("utf-8"),
            canonical,
            hashlib.sha256,
        ).hexdigest()
        self.assertEqual(
            headers["x-signature"],
            f"sha256={expected}",
        )

    def test_exact_transport_replay_receipt_is_reconciled(self):
        event = self._event()
        config = self._config()
        transport_event_id = event._transport_event_id(1)
        replay = {
            "error": "replayed_event_id",
            "event_id": transport_event_id,
            "projection": None,
        }
        body = json.dumps(
            replay,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        error = urllib.error.HTTPError(
            config["target_url"],
            409,
            "Conflict",
            {},
            BytesIO(body),
        )
        opener = _Opener(error=error)

        with patch.object(
            hardening_module.urllib.request,
            "build_opener",
            return_value=opener,
        ):
            result = event._post_event(config)

        self.assertEqual(result["status"], 409)
        self.assertEqual(result["receipt"], "reconciled_replay")

    def test_invalid_replay_receipt_is_dead_letter_safe(self):
        event = self._event()
        config = self._config()
        replay = {
            "error": "replayed_event_id",
            "event_id": "wrong-event",
            "projection": None,
        }
        body = json.dumps(replay).encode("utf-8")
        error = urllib.error.HTTPError(
            config["target_url"],
            409,
            "Conflict",
            {},
            BytesIO(body),
        )
        opener = _Opener(error=error)

        with patch.object(
            hardening_module.urllib.request,
            "build_opener",
            return_value=opener,
        ):
            with self.assertRaisesRegex(
                ValidationError,
                "replay receipt is invalid",
            ):
                event._post_event(config)

    def test_fresh_transport_retry_accepts_duplicate_receipt(self):
        event = self._event()
        event._write_delivery({"attempt_count": 1})
        config = self._config()
        first_transport_event_id = event._transport_event_id(1)
        status, body = self._receipt(
            event,
            status=200,
            event_id=first_transport_event_id,
            duplicate=True,
        )
        opener = _Opener(response=_Response(status, body))

        with patch.object(
            hardening_module.urllib.request,
            "build_opener",
            return_value=opener,
        ):
            result = event._post_event(config)

        headers = {
            key.lower(): value
            for key, value in opener.request.header_items()
        }
        self.assertEqual(
            headers["x-event-id"],
            event._transport_event_id(2),
        )
        self.assertEqual(result["receipt"], "duplicate")
