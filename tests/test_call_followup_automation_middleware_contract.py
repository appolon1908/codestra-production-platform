import sys
import tempfile
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from control_plane_service.core import (  # noqa: E402
    ControlPlaneError,
    EVENT_PREFIXES,
    Store,
    validate_envelope,
)


def _envelope(event_type="call_followup.completed"):
    return {
        "event_type": event_type,
        "event_version": "1.0",
        "occurred_at": "2026-09-02T00:00:00Z",
        "tenant_id": "tenant-a",
        "correlation_id": "correlation-a",
        "idempotency_key": "call-followup-idempotency-a",
        "payload": {
            "followup_id": 1,
            "company_id": 1,
        },
        "metadata": {
            "source": "odoo",
            "logical_event_id": "11111111-1111-4111-8111-111111111111",
        },
    }


class CallFollowupAutomationMiddlewareContractTests(unittest.TestCase):
    def test_odoo_call_followup_namespace_is_explicitly_registered(self):
        self.assertIn("call_followup.", EVENT_PREFIXES["odoo"])
        accepted = validate_envelope(
            _envelope(),
            "odoo",
            "transport-event-a",
        )
        self.assertEqual(
            accepted["event_type"],
            "call_followup.completed",
        )

        with self.assertRaisesRegex(
            ControlPlaneError,
            "unsupported_event_type",
        ):
            validate_envelope(
                _envelope(event_type="post_call.completed"),
                "odoo",
                "transport-event-b",
            )

    def test_fresh_transport_nonce_reuses_stable_idempotency_content(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(str(Path(directory) / "control-plane.db"))
            first = validate_envelope(
                _envelope(),
                "odoo",
                "transport-event-a",
            )
            accepted = store.ingest(
                first,
                reject_event_replay=True,
            )
            self.assertFalse(accepted.duplicate)

            second = validate_envelope(
                _envelope(),
                "odoo",
                "transport-event-b",
            )
            duplicate = store.ingest(
                second,
                reject_event_replay=True,
            )
            self.assertTrue(duplicate.duplicate)
            self.assertEqual(
                duplicate.event_id,
                "transport-event-a",
            )
            self.assertEqual(
                duplicate.correlation_id,
                "correlation-a",
            )

    def test_same_transport_nonce_has_exact_replay_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(str(Path(directory) / "control-plane.db"))
            value = validate_envelope(
                _envelope(),
                "odoo",
                "transport-event-a",
            )
            store.ingest(value, reject_event_replay=True)

            with self.assertRaisesRegex(
                ControlPlaneError,
                "replayed_event_id",
            ):
                store.ingest(value, reject_event_replay=True)

            replay = store.exact_event_replay(value)
            self.assertIsNotNone(replay)
            self.assertEqual(
                replay.event_id,
                "transport-event-a",
            )
            self.assertEqual(
                replay.correlation_id,
                "correlation-a",
            )
            self.assertTrue(replay.duplicate)


if __name__ == "__main__":
    unittest.main()
