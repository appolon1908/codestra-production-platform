from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.fields import Command
from odoo.tests import TransactionCase, tagged

from odoo.addons.codestra_crm_call_followup_automation.models.outbox import (
    _NoRedirectHandler,
)


@tagged("post_install", "-at_install")
class TestCodestraCrmCallFollowupOutbox(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        base_user = cls.env.ref("base.group_user")
        manager_group = cls.env.ref(
            "codestra_crm_call_followup.group_call_followup_manager"
        )
        cls.manager = cls.env["res.users"].with_context(
            no_reset_password=True
        ).create(
            {
                "name": "Automation Test Manager",
                "login": "automation-manager@test.invalid",
                "email": "automation-manager@test.invalid",
                "company_id": cls.env.company.id,
                "company_ids": [Command.set([cls.env.company.id])],
                "group_ids": [
                    Command.set([base_user.id, manager_group.id])
                ],
            }
        )
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
        first = self.outbox.enqueue_followup_events(self.followup)
        second = self.outbox.enqueue_followup_events(self.followup)
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

    def test_calendar_mutation_key_is_payload_based(self):
        start = fields.Datetime.now() + timedelta(days=1)
        event = self.env["calendar.event"].with_context(
            skip_codestra_automation_outbox=True
        ).create(
            {
                "name": "Automation calendar test",
                "start": start,
                "stop": start + timedelta(minutes=30),
                "codestra_call_followup_id": self.followup.id,
            }
        )
        first = self.outbox.enqueue_calendar_event(
            event, "calendar.rescheduled"
        )
        second = self.outbox.enqueue_calendar_event(
            event, "calendar.rescheduled"
        )
        self.assertEqual(first, second)

        event.with_context(skip_codestra_automation_outbox=True).write(
            {"stop": start + timedelta(minutes=45)}
        )
        third = self.outbox.enqueue_calendar_event(
            event, "calendar.rescheduled"
        )
        self.assertNotEqual(first, third)

    def test_payload_excludes_notes_and_email_bodies(self):
        event = self.outbox.enqueue_followup_events(self.followup)[0]
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

    def test_unapproved_target_host_is_rejected_before_secret_read(self):
        parameters = self.env["ir.config_parameter"].sudo()
        parameters.set_param(
            "codestra.call_followup_automation.target_url",
            "https://middleware.example.test/events",
        )
        parameters.set_param(
            "codestra.call_followup_automation.tenant_id",
            "test-tenant",
        )
        parameters.set_param(
            "codestra.call_followup_automation.allowed_hosts",
            "different.example.test",
        )
        with self.assertRaises(ValidationError):
            self.outbox._delivery_config()

    def test_redirect_handler_is_fail_closed(self):
        handler = _NoRedirectHandler()
        self.assertIsNone(
            handler.redirect_request(
                None,
                None,
                302,
                "Found",
                {},
                "https://other.example.test/",
            )
        )

    def test_stale_processing_record_can_be_reclaimed(self):
        event = self.outbox.enqueue_followup_events(self.followup)[0]
        event._write_delivery(
            {
                "state": "processing",
                "locked_at": fields.Datetime.now() - timedelta(minutes=10),
                "lease_token": "stale-lease",
            }
        )
        claimed = self.outbox._claim_due(10)
        self.assertIn(event, claimed)
        self.assertEqual(event.state, "processing")
        self.assertNotEqual(event.lease_token, "stale-lease")

    def test_manual_retry_preserves_attempt_evidence_and_extends_budget(self):
        event = self.outbox.enqueue_followup_events(self.followup)[0]
        event._write_delivery(
            {
                "state": "dead",
                "attempt_count": 8,
                "max_attempts": 8,
                "last_error": "http_400",
            }
        )
        event.with_user(self.manager).action_retry_now()
        self.assertEqual(event.state, "pending")
        self.assertEqual(event.attempt_count, 8)
        self.assertEqual(event.max_attempts, 11)
        self.assertEqual(event.manual_retry_count, 1)
