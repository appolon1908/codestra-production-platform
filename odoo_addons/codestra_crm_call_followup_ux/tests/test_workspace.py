from datetime import timedelta

from odoo import fields
from odoo.fields import Command
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCodestraCallFollowupWorkspace(TransactionCase):
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
        cls.agent = cls.env["res.users"].with_context(no_reset_password=True).create(
            {
                "name": "Workspace Agent",
                "login": "workspace-agent@test.invalid",
                "email": "workspace-agent@test.invalid",
                "company_id": cls.company.id,
                "company_ids": [Command.set([cls.company.id])],
                "group_ids": [Command.set([base_user.id, agent_group.id])],
            }
        )
        cls.service = cls.env["res.users"].with_context(no_reset_password=True).create(
            {
                "name": "Workspace Integration",
                "login": "workspace-integration@test.invalid",
                "email": "workspace-integration@test.invalid",
                "company_id": cls.company.id,
                "company_ids": [Command.set([cls.company.id])],
                "group_ids": [Command.set([base_user.id, service_group.id])],
            }
        )
        cls.customer = cls.env["res.partner"].create(
            {
                "name": "Workspace Customer",
                "email": "workspace-customer@test.invalid",
            }
        )
        cls.lead = cls.env["crm.lead"].create(
            {
                "name": "Workspace Opportunity",
                "type": "opportunity",
                "partner_id": cls.customer.id,
                "email_from": cls.customer.email,
                "user_id": cls.agent.id,
                "company_id": cls.company.id,
            }
        )

    def _register(self, event_id, with_customer=True):
        ended_at = fields.Datetime.now()
        payload = {
            "event_id": event_id,
            "company_id": self.company.id,
            "agent_user_id": self.agent.id,
            "source": "workspace-test",
            "started_at": fields.Datetime.to_string(
                ended_at - timedelta(seconds=125)
            ),
            "ended_at": fields.Datetime.to_string(ended_at),
            "duration_seconds": 125,
        }
        if with_customer:
            payload.update(
                {
                    "partner_id": self.customer.id,
                    "lead_id": self.lead.id,
                    "customer_email": self.customer.email,
                }
            )
        response = self.env(user=self.service)[
            "codestra.crm.call.followup"
        ].register_completed_call(payload)
        return self.env(user=self.agent)[
            "codestra.crm.call.followup"
        ].browse(response["followup_id"])

    def test_workspace_labels_and_related_record_actions(self):
        followup = self._register("workspace-labels")
        self.assertEqual(followup.ux_contact_label, self.customer.display_name)
        self.assertEqual(followup.ux_call_duration_label, "2 min 5 sec")
        self.assertTrue(followup.ux_can_complete)

        customer_action = followup.action_ux_open_customer()
        lead_action = followup.action_ux_open_opportunity()
        primary_action = followup.action_ux_primary()

        self.assertEqual(customer_action["res_model"], "res.partner")
        self.assertEqual(customer_action["res_id"], self.customer.id)
        self.assertEqual(lead_action["res_model"], "crm.lead")
        self.assertEqual(lead_action["res_id"], self.lead.id)
        self.assertEqual(
            primary_action["res_model"],
            "codestra.crm.post.call.wizard",
        )
        self.assertEqual(primary_action["target"], "new")

    def test_unmatched_completed_call_has_safe_primary_fallback(self):
        followup = self._register("workspace-unmatched", with_customer=False)
        followup.sudo()._write_from_workflow(
            {
                "state": "completed",
                "disposition": "contacted",
                "popup_completed_at": fields.Datetime.now(),
            }
        )
        followup.invalidate_recordset()
        action = followup.action_ux_primary()
        self.assertEqual(action["res_model"], "codestra.crm.call.followup")
        self.assertEqual(action["res_id"], followup.id)

    def test_readiness_guides_required_outcome(self):
        followup = self._register("workspace-readiness")
        wizard = self.env(user=self.agent)[
            "codestra.crm.post.call.wizard"
        ].create(
            {
                "followup_id": followup.id,
                "schedule_kind": "none",
                "send_post_call_email": False,
            }
        )
        self.assertFalse(wizard.ux_ready)
        wizard.disposition = "contacted"
        self.assertTrue(wizard.ux_schedule_ready)
        self.assertTrue(wizard.ux_email_ready)
        self.assertTrue(wizard.ux_ready)

    def test_complete_and_open_calendar_creates_linked_event(self):
        followup = self._register("workspace-calendar")
        callback_at = fields.Datetime.now() + timedelta(hours=4)
        wizard = self.env(user=self.agent)[
            "codestra.crm.post.call.wizard"
        ].create(
            {
                "followup_id": followup.id,
                "disposition": "callback",
                "schedule_kind": "callback",
                "callback_at": callback_at,
                "duration_minutes": 30,
                "send_post_call_email": False,
                "reminder_email_enabled": True,
            }
        )
        action = wizard.action_ux_complete_and_open_calendar()
        followup.invalidate_recordset()

        self.assertEqual(action["res_model"], "calendar.event")
        self.assertEqual(action["res_id"], followup.calendar_event_id.id)
        self.assertEqual(followup.state, "completed")
        self.assertEqual(followup.schedule_kind, "callback")

    def test_complete_without_email_keeps_mail_queue_empty(self):
        followup = self._register("workspace-no-email")
        wizard = self.env(user=self.agent)[
            "codestra.crm.post.call.wizard"
        ].create(
            {
                "followup_id": followup.id,
                "disposition": "contacted",
                "schedule_kind": "none",
                "send_post_call_email": True,
                "email_to": self.customer.email,
                "email_subject": "Follow-up",
                "email_body": "<p>Thank you.</p>",
            }
        )
        wizard.action_ux_complete_without_email()
        followup.invalidate_recordset()
        self.assertEqual(followup.state, "completed")
        self.assertFalse(followup.send_post_call_email)
        self.assertFalse(followup.mail_id)
