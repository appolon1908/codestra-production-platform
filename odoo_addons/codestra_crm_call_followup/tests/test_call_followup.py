from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError
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
                "name": "Other CRM Follow-up Agent",
                "login": "other-crm-followup-agent@test.invalid",
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
        first = self._register("idempotent-event")
        second = self._register("idempotent-event")

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

    def test_completed_call_identity_is_immutable_for_agent(self):
        registration = self._register("immutable-event")
        agent_env = self.env(user=self.agent)
        followup = agent_env["codestra.crm.call.followup"].browse(
            registration["followup_id"]
        )

        with self.assertRaises(AccessError):
            followup.write({"event_id": "rewritten-event"})

    def test_callback_creates_calendar_and_both_reminders(self):
        registration = self._register("callback-event")
        agent_env = self.env(user=self.agent)
        followup = agent_env["codestra.crm.call.followup"].browse(
            registration["followup_id"]
        )
        callback_at = fields.Datetime.now() + timedelta(hours=2)
        wizard = agent_env["codestra.crm.post.call.wizard"].create(
            {
                "followup_id": followup.id,
                "disposition": "callback",
                "notes": "Client asked to review the proposal before the callback.",
                "schedule_kind": "callback",
                "callback_at": callback_at,
                "duration_minutes": 45,
                "reminder_email_enabled": True,
                "send_post_call_email": False,
            }
        )
        wizard.action_complete()

        followup.invalidate_recordset()
        self.assertEqual(followup.state, "completed")
        self.assertEqual(followup.schedule_kind, "callback")
        self.assertTrue(followup.calendar_event_id)
        event = followup.calendar_event_id

        expected_partners = {self.customer.id, self.agent.partner_id.id}
        self.assertTrue(expected_partners.issubset(set(event.partner_ids.ids)))
        expected_alarms = {
            self.env.ref(
                "codestra_crm_call_followup.calendar_alarm_prepare_30_minutes"
            ).id,
            self.env.ref(
                "codestra_crm_call_followup.calendar_alarm_email_15_minutes"
            ).id,
        }
        self.assertTrue(expected_alarms.issubset(set(event.alarm_ids.ids)))

    def test_calendar_reschedule_updates_followup(self):
        registration = self._register("reschedule-event")
        agent_env = self.env(user=self.agent)
        followup = agent_env["codestra.crm.call.followup"].browse(
            registration["followup_id"]
        )
        original_start = fields.Datetime.now() + timedelta(hours=2)
        agent_env["codestra.crm.post.call.wizard"].create(
            {
                "followup_id": followup.id,
                "disposition": "appointment",
                "schedule_kind": "appointment",
                "callback_at": original_start,
                "duration_minutes": 30,
                "reminder_email_enabled": True,
                "send_post_call_email": False,
            }
        ).action_complete()

        followup.invalidate_recordset()
        new_start = original_start + timedelta(days=1)
        followup.calendar_event_id.write(
            {
                "start": new_start,
                "stop": new_start + timedelta(minutes=60),
            }
        )
        followup.invalidate_recordset()
        self.assertEqual(followup.callback_at, new_start)
        self.assertEqual(followup.duration_minutes, 60)

        followup.calendar_event_id.unlink()
        followup.invalidate_recordset()
        self.assertFalse(followup.calendar_event_id)
        self.assertFalse(followup.callback_at)
        self.assertEqual(followup.schedule_kind, "none")

    def test_immediate_email_is_queued_not_force_sent(self):
        registration = self._register("email-event")
        agent_env = self.env(user=self.agent)
        followup = agent_env["codestra.crm.call.followup"].browse(
            registration["followup_id"]
        )
        agent_env["codestra.crm.post.call.wizard"].create(
            {
                "followup_id": followup.id,
                "disposition": "contacted",
                "schedule_kind": "none",
                "send_post_call_email": True,
                "email_to": self.customer.email,
                "email_cc": self.agent.email,
                "email_subject": "Your requested follow-up",
                "email_body": "<p>Thank you for your time.</p>",
            }
        ).action_complete()

        followup.invalidate_recordset()
        self.assertTrue(followup.mail_id)
        self.assertEqual(followup.mail_id.state, "outgoing")
