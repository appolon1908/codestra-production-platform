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
        cls.unenabled_agent = cls.env["res.users"].with_context(
            no_reset_password=True
        ).create(
            {
                "name": "Unenabled CRM User",
                "login": "unenabled-crm-user@test.invalid",
                "email": "unenabled@test.invalid",
                "company_id": cls.company.id,
                "company_ids": [Command.set([cls.company.id])],
                "group_ids": [Command.set([base_user.id])],
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
        cls.other_customer = cls.env["res.partner"].create(
            {
                "name": "Different Customer",
                "email": "different@test.invalid",
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
            "api_version": "1.0",
            "event_id": event_id,
            "correlation_id": f"corr-{event_id}",
            "call_id": f"call-{event_id}",
            "source": "middleware-test",
            "company_id": self.company.id,
            "agent_user_id": self.agent.id,
            "lead_id": self.lead.id,
            "partner_id": self.customer.id,
            "started_at": fields.Datetime.to_string(
                ended_at - timedelta(minutes=4)
            ),
            "ended_at": fields.Datetime.to_string(ended_at),
            "duration_seconds": 240,
            "call_direction": "outbound",
        }

    def _register_payload(self, payload):
        return self.env(user=self.service_user)[
            "codestra.crm.call.followup.api"
        ].register_completed_call(payload)

    def _register(self, event_id):
        return self._register_payload(self._payload(event_id))

    def _followup_for(self, registration, user=None):
        env = self.env(user=user) if user else self.env
        return env["codestra.crm.call.followup"].browse(
            registration["followup_id"]
        )

    def test_only_service_group_can_use_api(self):
        agent_api = self.env(user=self.agent)[
            "codestra.crm.call.followup.api"
        ]
        with self.assertRaises(AccessError):
            agent_api.health()
        with self.assertRaises(AccessError):
            agent_api.get_contract()
        with self.assertRaises(AccessError):
            agent_api.register_completed_call(
                self._payload("unauthorized-event")
            )

    def test_api_health_and_contract_are_versioned(self):
        service_api = self.env(user=self.service_user)[
            "codestra.crm.call.followup.api"
        ]
        health = service_api.health()
        contract = service_api.get_contract()

        self.assertEqual(health["status"], "ok")
        self.assertEqual(health["api_version"], "1.0")
        self.assertFalse(health["public_controller"])
        self.assertEqual(contract["api_version"], "1.0")
        self.assertIn("register_completed_call", contract["methods"])
        self.assertIn("request", contract["schemas"])
        self.assertEqual(
            contract["security"]["authentication"],
            "odoo_api_key",
        )

    def test_compatibility_api_delegates_to_versioned_model(self):
        service_model = self.env(user=self.service_user)[
            "codestra.crm.call.followup"
        ]
        health = service_model.get_api_health()
        contract = service_model.get_api_contract()
        registration = service_model.register_completed_call(
            self._payload("compatibility-delegate")
        )

        self.assertEqual(health["api_version"], "1.0")
        self.assertEqual(contract["api_version"], "1.0")
        self.assertTrue(registration["created"])

    def test_completed_call_registration_is_idempotent(self):
        first = self._register("idempotent-event")
        second = self._register("idempotent-event")

        self.assertEqual(first["followup_id"], second["followup_id"])
        self.assertTrue(first["created"])
        self.assertFalse(first["replayed"])
        self.assertFalse(second["created"])
        self.assertTrue(second["replayed"])
        self.assertEqual(first["api_version"], "1.0")
        self.assertEqual(
            self.env["codestra.crm.call.followup"].sudo().search_count(
                [
                    ("company_id", "=", self.company.id),
                    ("event_id", "=", "idempotent-event"),
                ]
            ),
            1,
        )

    def test_conflicting_replay_fails_closed(self):
        self._register("conflict-event")
        conflicting = self._payload("conflict-event")
        conflicting["duration_seconds"] = 999
        conflicting["started_at"] = fields.Datetime.to_string(
            fields.Datetime.to_datetime(conflicting["ended_at"])
            - timedelta(seconds=999)
        )

        with self.assertRaisesRegex(
            ValidationError,
            "IDEMPOTENCY_CONFLICT",
        ):
            self._register_payload(conflicting)

    def test_unknown_fields_and_unsupported_version_fail_closed(self):
        unknown = self._payload("unknown-field")
        unknown["provider_secret"] = "must-not-be-accepted"
        with self.assertRaisesRegex(
            ValidationError,
            "UNKNOWN_PAYLOAD_FIELDS",
        ):
            self._register_payload(unknown)

        unsupported = self._payload("unsupported-version")
        unsupported["api_version"] = "2.0"
        with self.assertRaisesRegex(
            ValidationError,
            "UNSUPPORTED_API_VERSION",
        ):
            self._register_payload(unsupported)

    def test_timeline_and_required_end_time_are_validated(self):
        missing_end = self._payload("missing-end")
        missing_end.pop("ended_at")
        with self.assertRaises(ValidationError):
            self._register_payload(missing_end)

        reversed_timeline = self._payload("reversed-timeline")
        ended_at = fields.Datetime.to_datetime(
            reversed_timeline["ended_at"]
        )
        reversed_timeline["started_at"] = fields.Datetime.to_string(
            ended_at + timedelta(minutes=2)
        )
        with self.assertRaises(ValidationError):
            self._register_payload(reversed_timeline)

    def test_start_time_is_derived_from_duration(self):
        payload = self._payload("derived-start")
        payload.pop("started_at")
        registration = self._register_payload(payload)
        followup = self._followup_for(registration).sudo()

        self.assertEqual(
            int((followup.ended_at - followup.started_at).total_seconds()),
            240,
        )

    def test_agent_must_be_enabled_for_feature(self):
        payload = self._payload("agent-not-enabled")
        payload["agent_user_id"] = self.unenabled_agent.id

        with self.assertRaises(AccessError):
            self._register_payload(payload)

    def test_service_cannot_register_for_unassigned_company(self):
        payload = self._payload("cross-company-event")
        payload["company_id"] = self.other_company.id

        with self.assertRaises(AccessError):
            self._register_payload(payload)

    def test_lead_customer_mismatch_is_rejected(self):
        payload = self._payload("partner-mismatch")
        payload["partner_id"] = self.other_customer.id

        with self.assertRaises(ValidationError):
            self._register_payload(payload)

    def test_other_agent_cannot_read_or_update_assigned_followup(self):
        registration = self._register("assigned-agent-only")
        other_env = self.env(user=self.other_agent)
        followups = other_env["codestra.crm.call.followup"]

        self.assertFalse(
            followups.search(
                [("id", "=", registration["followup_id"])]
            )
        )
        with self.assertRaises(AccessError):
            followups.browse(registration["followup_id"]).write(
                {"disposition": "contacted"}
            )

    def test_human_cannot_create_or_delete_audit_record(self):
        with self.assertRaises(AccessError):
            self.env(user=self.agent)[
                "codestra.crm.call.followup"
            ].create(
                {
                    "name": "Fabricated call",
                    "event_id": "fabricated-event",
                    "source": "human",
                    "company_id": self.company.id,
                    "agent_id": self.agent.id,
                    "ended_at": fields.Datetime.now(),
                }
            )

        registration = self._register("undeletable-event")
        followup = self._followup_for(registration).sudo()
        with self.assertRaises(AccessError):
            followup.unlink()

    def test_completed_call_identity_is_immutable_for_agent(self):
        registration = self._register("immutable-event")
        followup = self._followup_for(
            registration,
            user=self.agent,
        )

        with self.assertRaises(AccessError):
            followup.write({"event_id": "rewritten-event"})

    def test_pending_action_is_recovered_only_for_assigned_agent(self):
        registration = self._register("pending-recovery-event")
        pending = self.env(user=self.agent)[
            "codestra.crm.call.followup"
        ].get_pending_post_call_actions(limit=10)
        other_pending = self.env(user=self.other_agent)[
            "codestra.crm.call.followup"
        ].get_pending_post_call_actions(limit=10)

        self.assertEqual(
            [item["followup_id"] for item in pending].count(
                registration["followup_id"]
            ),
            1,
        )
        self.assertNotIn(
            registration["followup_id"],
            [item["followup_id"] for item in other_pending],
        )

    def test_snooze_saves_draft_and_hides_pending_popup(self):
        registration = self._register("snooze-event")
        agent_env = self.env(user=self.agent)
        followup = self._followup_for(
            registration,
            user=self.agent,
        )
        wizard = agent_env[
            "codestra.crm.post.call.wizard"
        ].create(
            {
                "followup_id": followup.id,
                "disposition": "contacted",
                "notes": "<p>Call back after internal review.</p>",
                "priority": "high",
                "customer_sentiment": "neutral",
                "schedule_kind": "none",
                "send_post_call_email": False,
            }
        )
        wizard.action_snooze_10_minutes()

        followup.invalidate_recordset()
        self.assertEqual(followup.state, "pending")
        self.assertEqual(followup.priority, "high")
        self.assertTrue(followup.snoozed_until)
        pending_ids = [
            item["followup_id"]
            for item in agent_env[
                "codestra.crm.call.followup"
            ].get_pending_post_call_actions(limit=20)
        ]
        self.assertNotIn(followup.id, pending_ids)

    def test_callback_creates_private_calendar_and_both_reminders(self):
        registration = self._register("callback-event")
        agent_env = self.env(user=self.agent)
        followup = self._followup_for(
            registration,
            user=self.agent,
        )
        callback_at = fields.Datetime.now() + timedelta(hours=2)
        wizard = agent_env[
            "codestra.crm.post.call.wizard"
        ].create(
            {
                "followup_id": followup.id,
                "disposition": "appointment",
                "notes": "<p>Customer requested a video proposal review.</p>",
                "priority": "urgent",
                "customer_sentiment": "positive",
                "schedule_kind": "appointment",
                "callback_at": callback_at,
                "duration_minutes": 45,
                "contact_channel": "video",
                "meeting_location": "https://meet.test.invalid/proposal",
                "reminder_email_enabled": True,
                "send_post_call_email": False,
            }
        )
        wizard.action_complete()

        followup.invalidate_recordset()
        self.assertEqual(followup.state, "completed")
        self.assertEqual(followup.priority, "urgent")
        self.assertEqual(followup.priority_rank, 2)
        self.assertEqual(followup.schedule_kind, "appointment")
        self.assertEqual(followup.completed_by_id, self.agent)
        self.assertTrue(followup.completed_at)
        event = followup.calendar_event_id
        self.assertTrue(event)
        self.assertEqual(event.privacy, "private")
        self.assertEqual(
            event.location,
            "https://meet.test.invalid/proposal",
        )

        expected_partners = {
            self.customer.id,
            self.agent.partner_id.id,
        }
        self.assertTrue(
            expected_partners.issubset(set(event.partner_ids.ids))
        )
        expected_alarms = {
            self.env.ref(
                "codestra_crm_call_followup."
                "calendar_alarm_prepare_30_minutes"
            ).id,
            self.env.ref(
                "codestra_crm_call_followup."
                "calendar_alarm_email_15_minutes"
            ).id,
        }
        self.assertTrue(
            expected_alarms.issubset(set(event.alarm_ids.ids))
        )

    def test_calendar_reschedule_and_location_update_followup(self):
        registration = self._register("reschedule-event")
        agent_env = self.env(user=self.agent)
        followup = self._followup_for(
            registration,
            user=self.agent,
        )
        original_start = fields.Datetime.now() + timedelta(hours=2)
        agent_env["codestra.crm.post.call.wizard"].create(
            {
                "followup_id": followup.id,
                "disposition": "appointment",
                "notes": "<p>In-person review.</p>",
                "schedule_kind": "appointment",
                "callback_at": original_start,
                "duration_minutes": 30,
                "contact_channel": "in_person",
                "meeting_location": "Office A",
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
                "location": "Office B",
            }
        )
        followup.invalidate_recordset()
        self.assertEqual(followup.callback_at, new_start)
        self.assertEqual(followup.duration_minutes, 60)
        self.assertEqual(followup.meeting_location, "Office B")

    def test_calendar_cancellation_clears_schedule_but_preserves_audit(self):
        registration = self._register("cancel-calendar-event")
        agent_env = self.env(user=self.agent)
        followup = self._followup_for(
            registration,
            user=self.agent,
        )
        agent_env["codestra.crm.post.call.wizard"].create(
            {
                "followup_id": followup.id,
                "disposition": "callback",
                "schedule_kind": "callback",
                "callback_at": fields.Datetime.now() + timedelta(hours=2),
                "duration_minutes": 30,
                "contact_channel": "phone",
                "reminder_email_enabled": True,
                "send_post_call_email": False,
            }
        ).action_complete()

        followup.invalidate_recordset()
        followup.calendar_event_id.unlink()
        self.assertTrue(followup.exists())
        self.assertEqual(followup.state, "completed")
        self.assertEqual(followup.schedule_kind, "none")
        self.assertFalse(followup.callback_at)
        self.assertFalse(followup.calendar_event_id)
        self.assertFalse(followup.meeting_location)

    def test_immediate_email_is_queued_not_force_sent(self):
        registration = self._register("email-event")
        agent_env = self.env(user=self.agent)
        followup = self._followup_for(
            registration,
            user=self.agent,
        )
        agent_env["codestra.crm.post.call.wizard"].create(
            {
                "followup_id": followup.id,
                "disposition": "contacted",
                "notes": "<p>Customer requested written details.</p>",
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

    def test_double_completion_does_not_duplicate_side_effects(self):
        registration = self._register("double-submit-event")
        agent_env = self.env(user=self.agent)
        followup = self._followup_for(
            registration,
            user=self.agent,
        )
        wizard = agent_env[
            "codestra.crm.post.call.wizard"
        ].create(
            {
                "followup_id": followup.id,
                "disposition": "contacted",
                "notes": "<p>One completion only.</p>",
                "schedule_kind": "none",
                "send_post_call_email": True,
                "email_to": self.customer.email,
                "email_subject": "Single queued message",
                "email_body": "<p>One message.</p>",
            }
        )

        wizard.action_complete()
        first_mail_count = self.env["mail.mail"].sudo().search_count(
            [
                ("model", "=", "codestra.crm.call.followup"),
                ("res_id", "=", followup.id),
            ]
        )
        first_summary_count = len(
            self.lead.message_ids.filtered(
                lambda message: "Post-call follow-up completed"
                in (message.body or "")
            )
        )

        wizard.action_complete()
        second_mail_count = self.env["mail.mail"].sudo().search_count(
            [
                ("model", "=", "codestra.crm.call.followup"),
                ("res_id", "=", followup.id),
            ]
        )
        second_summary_count = len(
            self.lead.message_ids.filtered(
                lambda message: "Post-call follow-up completed"
                in (message.body or "")
            )
        )

        self.assertEqual(first_mail_count, 1)
        self.assertEqual(second_mail_count, first_mail_count)
        self.assertEqual(second_summary_count, first_summary_count)

    def test_compliance_outcomes_require_notes_and_disable_email(self):
        registration = self._register("compliance-event")
        agent_env = self.env(user=self.agent)
        followup = self._followup_for(
            registration,
            user=self.agent,
        )

        without_notes = agent_env[
            "codestra.crm.post.call.wizard"
        ].create(
            {
                "followup_id": followup.id,
                "disposition": "do_not_call",
                "schedule_kind": "none",
                "send_post_call_email": False,
            }
        )
        with self.assertRaises(ValidationError):
            without_notes.action_complete()

        with_email = agent_env[
            "codestra.crm.post.call.wizard"
        ].create(
            {
                "followup_id": followup.id,
                "disposition": "do_not_call",
                "notes": "<p>Customer explicitly requested no more calls.</p>",
                "schedule_kind": "none",
                "send_post_call_email": True,
                "email_to": self.customer.email,
                "email_subject": "Should not send",
                "email_body": "<p>Blocked.</p>",
            }
        )
        with self.assertRaises(ValidationError):
            with_email.action_complete()

        agent_env["codestra.crm.post.call.wizard"].create(
            {
                "followup_id": followup.id,
                "disposition": "do_not_call",
                "notes": "<p>Customer explicitly requested no more calls.</p>",
                "schedule_kind": "none",
                "send_post_call_email": False,
            }
        ).action_complete()

        followup.invalidate_recordset()
        self.assertTrue(followup.compliance_review_required)
        self.assertFalse(followup.send_post_call_email)
        self.assertEqual(followup.state, "completed")

    def test_agent_notes_are_copied_to_crm_chatter(self):
        registration = self._register("chatter-notes-event")
        agent_env = self.env(user=self.agent)
        followup = self._followup_for(
            registration,
            user=self.agent,
        )
        note = "Synthetic customer requested a proposal review."
        agent_env["codestra.crm.post.call.wizard"].create(
            {
                "followup_id": followup.id,
                "disposition": "contacted",
                "notes": note,
                "priority": "high",
                "customer_sentiment": "neutral",
                "schedule_kind": "none",
                "send_post_call_email": False,
            }
        ).action_complete()

        message = self.lead.message_ids.filtered(
            lambda item: "Post-call follow-up completed"
            in (item.body or "")
        )[:1]
        self.assertTrue(message)
        self.assertIn(note, message.body)
        self.assertIn("High", message.body)

    def test_agent_cannot_bypass_workflow_with_direct_write(self):
        registration = self._register("direct-write-event")
        followup = self._followup_for(
            registration,
            user=self.agent,
        )

        with self.assertRaises(AccessError):
            followup.write(
                {
                    "state": "completed",
                    "disposition": "sale",
                }
            )

    def test_completed_followup_cannot_be_cancelled(self):
        registration = self._register("completed-cancel-event")
        agent_env = self.env(user=self.agent)
        followup = self._followup_for(
            registration,
            user=self.agent,
        )
        agent_env["codestra.crm.post.call.wizard"].create(
            {
                "followup_id": followup.id,
                "disposition": "contacted",
                "schedule_kind": "none",
                "send_post_call_email": False,
            }
        ).action_complete()

        with self.assertRaises(ValidationError):
            followup.action_cancel_followup()

    def test_related_record_action_opens_crm_lead(self):
        registration = self._register("related-record-event")
        followup = self._followup_for(
            registration,
            user=self.agent,
        )
        action = followup.action_open_related_record()

        self.assertEqual(action["res_model"], "crm.lead")
        self.assertEqual(action["res_id"], self.lead.id)
