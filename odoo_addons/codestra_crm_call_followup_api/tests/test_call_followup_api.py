from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.fields import Command
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCodestraCrmCallFollowupApi(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        base_user = cls.env.ref("base.group_user")
        agent_group = cls.env.ref(
            "codestra_crm_call_followup.group_call_followup_user"
        )
        service_group = cls.env.ref(
            "codestra_crm_call_followup.group_call_followup_service"
        )
        cls.agent = cls.env["res.users"].with_context(
            no_reset_password=True
        ).create(
            {
                "name": "API Test Agent",
                "login": "api-agent@test.invalid",
                "email": "api-agent@test.invalid",
                "company_id": cls.company.id,
                "company_ids": [Command.set([cls.company.id])],
                "group_ids": [Command.set([base_user.id, agent_group.id])],
            }
        )
        cls.service_user = cls.env["res.users"].with_context(
            no_reset_password=True
        ).create(
            {
                "name": "API Integration Service",
                "login": "api-service@test.invalid",
                "email": "api-service@test.invalid",
                "company_id": cls.company.id,
                "company_ids": [Command.set([cls.company.id])],
                "group_ids": [Command.set([base_user.id, service_group.id])],
            }
        )
        cls.customer = cls.env["res.partner"].create(
            {
                "name": "API Test Customer",
                "email": "customer@test.invalid",
            }
        )
        cls.lead = cls.env["crm.lead"].create(
            {
                "name": "API Contract Opportunity",
                "type": "opportunity",
                "company_id": cls.company.id,
                "user_id": cls.agent.id,
                "partner_id": cls.customer.id,
            }
        )

    def _api(self):
        return self.env(user=self.service_user)["codestra.crm.call.followup"]

    def _payload(self, event_id="api-event"):
        ended_at = fields.Datetime.now()
        return {
            "api_version": "1.0",
            "event_id": event_id,
            "correlation_id": f"corr-{event_id}",
            "call_id": f"call-{event_id}",
            "source": "middleware",
            "producer": "vicidial-adapter",
            "company_id": self.company.id,
            "agent_user_id": self.agent.id,
            "agent_login": self.agent.login,
            "lead_id": self.lead.id,
            "partner_id": self.customer.id,
            "started_at": fields.Datetime.to_string(
                ended_at - timedelta(minutes=3)
            ),
            "ended_at": fields.Datetime.to_string(ended_at),
            "duration_seconds": 180,
        }

    def test_v1_returns_versioned_reconciliation_fields(self):
        result = self._api().register_completed_call_v1(
            self._payload("versioned-event")
        )
        self.assertEqual(result["api_version"], "1.0")
        self.assertTrue(result["accepted"])
        self.assertFalse(result["replayed"])
        self.assertTrue(result["request_fingerprint"])

        status = self._api().get_completed_call_status_v1(
            self.company.id,
            "versioned-event",
        )
        self.assertTrue(status["found"])
        self.assertEqual(status["followup_id"], result["followup_id"])

    def test_same_event_with_changed_immutable_payload_is_rejected(self):
        payload = self._payload("conflicting-event")
        self._api().register_completed_call_v1(payload)
        payload["duration_seconds"] = 999

        with self.assertRaises(ValidationError):
            self._api().register_completed_call_v1(payload)

    def test_correlation_change_does_not_create_idempotency_conflict(self):
        payload = self._payload("retry-correlation-event")
        first = self._api().register_completed_call_v1(payload)
        payload["correlation_id"] = "retry-correlation-id"
        second = self._api().register_completed_call_v1(payload)

        self.assertEqual(first["followup_id"], second["followup_id"])
        self.assertTrue(second["replayed"])

    def test_strict_api_rejects_unknown_fields(self):
        payload = self._payload("unknown-field-event")
        payload["unexpected"] = "not-allowed"

        with self.assertRaises(ValidationError):
            self._api().register_completed_call_v1(payload)

    def test_started_at_cannot_be_after_ended_at(self):
        payload = self._payload("invalid-time-order")
        payload["started_at"] = fields.Datetime.to_string(
            fields.Datetime.now() + timedelta(hours=1)
        )

        with self.assertRaises(ValidationError):
            self._api().validate_completed_call_v1(payload)

    def test_capabilities_are_machine_readable(self):
        capabilities = self._api().get_integration_capabilities()
        self.assertEqual(capabilities["api_version"], "1.0")
        self.assertEqual(
            capabilities["methods"]["register"],
            "register_completed_call_v1",
        )
        self.assertIn("event_id", capabilities["allowed_fields"])
