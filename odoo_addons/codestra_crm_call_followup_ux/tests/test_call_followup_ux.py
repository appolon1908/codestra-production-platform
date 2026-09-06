from datetime import timedelta

from odoo import fields
from odoo.fields import Command
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCodestraCrmCallFollowupUx(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        base_user = cls.env.ref("base.group_user")
        agent_group = cls.env.ref(
            "codestra_crm_call_followup.group_call_followup_user"
        )
        cls.agent = cls.env["res.users"].with_context(
            no_reset_password=True
        ).create(
            {
                "name": "UX Test Agent",
                "login": "ux-agent@test.invalid",
                "email": "ux-agent@test.invalid",
                "company_id": cls.env.company.id,
                "company_ids": [Command.set([cls.env.company.id])],
                "group_ids": [Command.set([base_user.id, agent_group.id])],
            }
        )
        cls.followup = cls.env[
            "codestra.crm.call.followup"
        ].sudo().create(
            {
                "name": "Post-call UX test",
                "event_id": "ux-event-1",
                "source": "test",
                "company_id": cls.env.company.id,
                "agent_id": cls.agent.id,
                "ended_at": fields.Datetime.now(),
                "duration_seconds": 60,
                "popup_requested_at": fields.Datetime.now(),
            }
        )

    def test_form_snooze_keeps_the_persistent_record_open(self):
        action = self.followup.with_user(
            self.agent
        ).action_snooze_15()
        self.assertEqual(
            action,
            {"type": "ir.actions.client", "tag": "reload"},
        )
        self.assertEqual(self.followup.snooze_count, 1)
        self.assertTrue(self.followup.snoozed_until)
        self.assertGreater(
            self.followup.snoozed_until,
            fields.Datetime.now(),
        )

    def test_wizard_snooze_closes_only_the_dialog(self):
        wizard = self.env[
            "codestra.crm.post.call.wizard"
        ].with_user(self.agent).create(
            {"followup_id": self.followup.id}
        )
        action = wizard.action_snooze_5()
        self.assertEqual(
            action,
            {"type": "ir.actions.act_window_close"},
        )
        self.assertEqual(self.followup.snooze_count, 1)

    def test_snoozed_followup_is_not_returned_until_due(self):
        self.followup._write_from_workflow(
            {
                "snoozed_until": (
                    fields.Datetime.now() + timedelta(minutes=30)
                ),
            }
        )
        pending = self.env(user=self.agent)[
            "codestra.crm.call.followup"
        ].get_pending_post_call_actions()
        self.assertNotIn(
            self.followup.id,
            [item["followup_id"] for item in pending],
        )

        self.followup._write_from_workflow(
            {
                "snoozed_until": (
                    fields.Datetime.now() - timedelta(minutes=1)
                ),
            }
        )
        pending = self.env(user=self.agent)[
            "codestra.crm.call.followup"
        ].get_pending_post_call_actions()
        self.assertIn(
            self.followup.id,
            [item["followup_id"] for item in pending],
        )

    def test_cron_releases_due_snooze(self):
        self.followup._write_from_workflow(
            {
                "snoozed_until": (
                    fields.Datetime.now() - timedelta(minutes=1)
                ),
                "snooze_count": 1,
            }
        )
        released = self.env[
            "codestra.crm.call.followup"
        ]._cron_release_snoozed_followups()
        self.assertGreaterEqual(released, 1)
        self.assertFalse(self.followup.snoozed_until)
        self.assertTrue(self.followup.last_popup_released_at)

    def test_popup_state_reports_pending_and_due(self):
        state = self.env(user=self.agent)[
            "codestra.crm.call.followup"
        ].get_post_call_popup_state(self.followup.id)
        self.assertTrue(state["found"])
        self.assertTrue(state["pending"])
        self.assertTrue(state["due"])
