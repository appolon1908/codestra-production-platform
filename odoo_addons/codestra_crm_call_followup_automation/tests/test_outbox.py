from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCodestraCrmCallFollowupOutbox(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.followup = (
            cls.env["codestra.crm.call.followup"]
            .sudo()
            .create(
                {
                    "name": "Automation test follow-up",
                    "event_id": "automation-event-1",
                    "source": "test",
                    "company_id": cls.env.company.id,
                    "agent_id": cls.env.user.id,
                    "ended_at": fields.Datetime.now(),
                    "duration_seconds": 30,
                    "state": "completed",
                    "disposition": "contacted",
                    "popup_completed_at": fields.Datetime.now(),
                }
            )
        )
        cls.outbox = cls.env[
            "codestra.crm.call.followup.outbox"
        ]

    def test_followup_events_are_idempotent(self):
        first = self.outbox.enqueue_followup_events(
            self.followup
        )
        second = self.outbox.enqueue_followup_events(
            self.followup
        )
        self.assertEqual(
            {record.id for record in first},
            {record.id for record in second},
        )
        self.assertEqual(
            self.outbox.search_count(
                [("followup_id", "=", self.followup.id)]
            ),
            1,
        )

    def test_payload_excludes_notes_and_email_bodies(self):
        event = self.outbox.enqueue_followup_events(
            self.followup
        )[0]
        self.assertNotIn("notes", event.payload_json)
        self.assertNotIn("email_body", event.payload_json)
        self.assertNotIn("email_to", event.payload_json)

    def test_delivery_is_fail_closed_by_default(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "codestra.call_followup_automation.enabled",
            "False",
        )
        self.outbox.enqueue_followup_events(self.followup)
        processed = self.outbox._cron_process_outbox()
        self.assertEqual(processed, 0)
        event = self.outbox.search(
            [("followup_id", "=", self.followup.id)],
            limit=1,
        )
        self.assertEqual(event.state, "pending")
