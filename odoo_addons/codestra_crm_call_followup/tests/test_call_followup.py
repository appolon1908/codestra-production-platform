from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.fields import Command
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCodestraCrmCallFollowup(TransactionCase):
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
                "name": "CRM Follow-up Agent",
                "login": "crm-followup-agent@test.invalid",
                "email": "agent@test.invalid",
                "company_id": cls.company.id,
                "company_ids": [Command.set([cls.company.id])],
                "group_ids": [Command.set([base_user.id, agent_group.id])],
            }
        )
        cls.service_user = cls.env["res.users"].with_context(
            no_reset_password=True
        ).create(
            {
                "name": "Call Integration Service",
                "login": "call-integration@test.invalid",
                "email": "integration@test.invalid",
                "company_id": cls.company.id,
                "company_ids": [Command.set([cls.company.id])],
                "group_ids": [Command.set([base_user.id, service_group.id])],
            }
        )
        cls.other_agent = cls.env["res.users"].with_context(
            no_reset_password=True
        ).create(
            {
                "name": "Other CRM Agent",
                "login": "other-crm-agent@test.invalid",
                "email": "other-agent@test.invalid",
                "company_id": cls.company.id,
                "company_ids": [Command.set([cls.company.id])],
                "group_ids": [Command.set([base_user.id, agent_group.id])],
            }
        )
        cls.other_company = cls.env["res.company"].create(
            {"name": "Isolated Test Company"}
        )
        cls.customer = cls.env["res.partner"].create(
            {
                "name": "Test Customer",
                "email": "customer@test.invalid",
            }
        )
        cls.lead = cls.env["crm.lead"].create(
            {
                "name": "Test CRM Opportunity",
                "type": "opportunity",
                "company_id": cls.company.id,
                "user_id": cls.agent.id,
                "partner_id": cls.customer.id,
                "email_from": cls.customer.email,
            }
        )

    def _payload(self, event_id):
        ended_at = fields.Datetime.now()
        return {
            "event_id": event_id,
            "correlation_id": f"corr-{event_id}",
            "call_id": f"call-{event_id}",
            "source": "middleware-test",
            "company_id": self.company.id,
            "agent_user_id": self.agent.id,
            "lead_id": self.lead.id,
            "partner_id": self.customer.id,
            "started_at": fields.Datetime.to_string(ended_at - timedelta(minutes=4)),
            "ended_at": fields.Datetime.to_string(ended_at),
            "duration_seconds": 240,
        }

    def _register(self, event_id):
        service_env = self.env(user=self.service_user)
        return service_env[
            "codestra.crm.call.followup"
        ].register_completed_call(self._payload(event_id))

    def test_only_service_group_can_register_completed_calls(self):
        agent_env = self.env(user=self.agent)
        with self.assertRaises(AccessError):
            agent_env[
                "codestra.crm.call.followup"
            ].register_completed_call(self._payload("unauthorized-event"))

    def test_completed_call_registration_is_idempotent(self):
        payload = self._payload("idempotent-event")
        service = self.env(user=self.service_user)["codestra.crm.call.followup"]
        first = service.register_completed_call(payload)
        second = service.register_completed_call(dict(payload))

        self.assertEqual(first["followup_id"], second["followup_id"])
        self.assertFalse(first["replayed"])
        self.assertTrue(second["replayed"])
        self.assertEqual(
            self.env["codestra.crm.call.followup"].sudo().search_count(
                [
                    ("company_id", "=", self.company.id),
                    ("event_id", "=", "idempotent-event"),
                ]
            ),
            1,
        )

    def test_other_agent_cannot_read_or_update_assigned_followup(self):
        registration = self._register("assigned-agent-only")
        other_env = self.env(user=self.other_agent)
        followups = other_env["codestra.crm.call.followup"]

        self.assertFalse(followups.search([("id", "=", registration["followup_id"])]))
        with self.assertRaises(AccessError):
            followups.browse(registration["followup_id"]).write(
                {"disposition": "contacted"}
            )

    def test_service_cannot_register_for_unassigned_company(self):
        payload = self._payload("cross-company-event")
        payload["company_id"] = self.other_company.id
        service_env = self.env(user=self.service_user)

        with self.assertRaises(AccessError):
            service_env[
                "codestra.crm.call.followup"
            ].register_completed_call(payload)
