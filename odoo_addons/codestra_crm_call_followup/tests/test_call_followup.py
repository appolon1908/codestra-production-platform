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
        manager_group = cls.env.ref(
            "codestra_crm_call_followup.group_call_followup_manager"
        )
        service_group = cls.env.ref(
            "codestra_crm_call_followup.group_call_followup_service"
        )

        def user_values(name, login, email, groups):
            return {
                "name": name,
                "login": login,
                "email": email,
                "company_id": cls.company.id,
                "company_ids": [Command.set([cls.company.id])],
                "group_ids": [Command.set([base_user.id, *groups])],
            }

        cls.agent = cls.env["res.users"].with_context(
            no_reset_password=True
        ).create(
            user_values(
                "CRM Follow-up Agent",
                "crm-followup-agent@test.invalid",
                "agent@test.invalid",
                [agent_group.id],
            )
        )
        cls.other_agent = cls.env["res.users"].with_context(
            no_reset_password=True
        ).create(
            user_values(
                "Other CRM Agent",
                "other-crm-agent@test.invalid",
                "other-agent@test.invalid",
                [agent_group.id],
            )
        )
        cls.non_followup_user = cls.env["res.users"].with_context(
            no_reset_password=True
        ).create(
            user_values(
                "Ordinary Internal User",
                "ordinary-user@test.invalid",
                "ordinary@test.invalid",
                [],
            )
        )
        cls.manager = cls.env["res.users"].with_context(
            no_reset_password=True
        ).create(
            user_values(
                "CRM Follow-up Manager",
                "crm-followup-manager@test.invalid",
                "manager@test.invalid",
                [manager_group.id],
            )
        )
        cls.service_user = cls.env["res.users"].with_context(
            no_reset_password=True
        ).create(
            user_values(
                "Codestra Middleware Service",
                "call-integration@test.invalid",
                "integration@test.invalid",
                [service_group.id],
            )
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
            "started_at": fields.Datetime.to_string(
                ended_at - timedelta(minutes=4)
            ),
            "ended_at": fields.Datetime.to_string(ended_at),
            "duration_seconds": 240,
        }

    def _register(self, event_id, payload=None):
        service_env = self.env(user=self.service_user)
        return service_env[
            "codestra.crm.call.followup"
        ].register_completed_call(payload or self._payload(event_id))

    def _followup(self, registration, user=None):
        env = self.env(user=user) if user else self.env
        return env["codestra.crm.call.followup"].browse(
            registration["followup_id"]
        )

    def _complete(self, followup, **overrides):
        values = {
            "followup_id": followup.id,
            "disposition": "contacted",
            "schedule_kind": "none",
            "send_post_call_email": False,
        }
        values.update(overrides)
        wizard = self.env(user=self.agent)[
            "codestra.crm.post.call.wizard"
        ].create(values)
        wizard.action_complete()
        followup.invalidate_recordset()
        return wizard

    def test_only_service_group_can_register_completed_calls(self):
        agent_env = self.env(user=self.agent)
        with self.assertRaises(AccessError):
            agent_env[
                "codestra.crm.call.followup"
            ].register_completed_call(self._payload("unauthorized-event"))

    def test_company_is_required_and_never_defaults_from_service_session(self):
        payload = self._payload("missing-company")
        payload.pop("company_id")
        with self.assertRaisesRegex(ValidationError, "company_id is required"):
            self._register("missing-company", payload)

    def test_selected_agent_must_have_call_followup_privilege(self):
        payload = self._payload("unprivileged-agent")
        payload["agent_user_id"] = self.non_followup_user.id
        with self.assertRaisesRegex(ValidationError, "Call Follow-up Agent"):
            self._register("unprivileged-agent", payload)

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
        self.assertFalse(
            followups.search([("id", "=", registration["followup_id"])])
        )
        with self.assertRaises(AccessError):
            followups.browse(registration["followup_id"]).write(
                {"disposition": "contacted"}
            )

    def test_service_cannot_register_for_unassigned_company(self):
        payload = self._payload("cross-company-event")
        payload["company_id"] = self.other_company.id
        with self.assertRaises(AccessError):
            self._register("cross-company-event", payload)

    def test_manager_cannot_bypass_workflow_with_direct_state_write(self):
        registration = self._register("manager-direct-write")
        followup = self._followup(registration, self.manager)
        with self.assertRaises(AccessError):
            followup.write(
                {
                    "state": "completed",
                    "disposition": "sale",
                    "notes": "Bypassed workflow",
                }
            )

    def test_callback_creates_internal_calendar_and_middleware_reminders(self):
        registration = self._register("callback-event")
        followup = self._followup(registration, self.agent)
        callback_at = fields.Datetime.now() + timedelta(hours=2)
        mail_count = self.env["mail.mail"].sudo().search_count([])

        self._complete(
            followup,
            disposition="callback",
            notes="Client asked to review the proposal before the callback.",
            schedule_kind="callback",
            callback_at=callback_at,
            duration_minutes=45,
            reminder_email_enabled=True,
        )

        event = followup.calendar_event_id
        self.assertTrue(event)
        self.assertEqual(event.partner_ids, self.agent.partner_id)
        self.assertNotIn(self.customer, event.partner_ids)
        self.assertEqual(
            event.alarm_ids,
            self.env.ref(
                "codestra_crm_call_followup.calendar_alarm_prepare_30_minutes"
            ),
        )
        self.assertEqual(self.env["mail.mail"].sudo().search_count([]), mail_count)

        reminders = followup.delivery_intent_ids.filtered(
            lambda intent: intent.intent_type == "callback_reminder"
        )
        self.assertEqual(len(reminders), 2)
        self.assertEqual(set(reminders.mapped("audience")), {"client", "agent"})
        self.assertEqual(set(reminders.mapped("state")), {"pending"})
        self.assertTrue(all(reminders.mapped("requires_consent_check")))

    def test_immediate_email_records_intent_without_creating_mail(self):
        registration = self._register("immediate-intent")
        followup = self._followup(registration, self.agent)
        before = self.env["mail.mail"].sudo().search_count([])
        self._complete(
            followup,
            send_post_call_email=True,
            email_to=self.customer.email,
            email_cc=self.agent.email,
            email_subject="Your requested follow-up",
            email_body="<p>Thank you for your time.</p>",
        )

        self.assertEqual(self.env["mail.mail"].sudo().search_count([]), before)
        intent = followup.immediate_delivery_intent_id
        self.assertTrue(intent)
        self.assertEqual(intent.intent_type, "post_call_email")
        self.assertEqual(intent.audience, "client")
        self.assertEqual(intent.state, "pending")
        self.assertEqual(intent.recipient_to, self.customer.email)
        self.assertTrue(intent.requires_consent_check)
        self.assertFalse(followup.mail_id)

    def test_middleware_service_claims_and_acknowledges_intent(self):
        registration = self._register("delivery-lease")
        followup = self._followup(registration, self.agent)
        self._complete(
            followup,
            send_post_call_email=True,
            email_to=self.customer.email,
            email_cc=self.agent.email,
            email_subject="Lease test",
            email_body="<p>Lease test.</p>",
        )
        service_model = self.env(user=self.service_user)[
            "codestra.crm.call.delivery.intent"
        ]
        claimed = service_model.claim_due_delivery_intents(limit=10)
        selected = next(
            item
            for item in claimed
            if item["intent_id"] == followup.immediate_delivery_intent_id.id
        )
        result = service_model.acknowledge_delivery_intent(
            selected["intent_id"],
            selected["lease_token"],
            provider_message_id="provider-message-1",
        )
        followup.immediate_delivery_intent_id.invalidate_recordset()
        self.assertEqual(result["state"], "delivered")
        self.assertEqual(followup.immediate_delivery_intent_id.state, "delivered")
        replay = service_model.acknowledge_delivery_intent(
            selected["intent_id"],
            selected["lease_token"],
            provider_message_id="provider-message-1",
        )
        self.assertTrue(replay["replayed"])

    def test_calendar_reschedule_replaces_only_undelivered_reminders(self):
        registration = self._register("reschedule-event")
        followup = self._followup(registration, self.agent)
        original_start = fields.Datetime.now() + timedelta(hours=2)
        self._complete(
            followup,
            disposition="appointment",
            schedule_kind="appointment",
            callback_at=original_start,
            duration_minutes=30,
            reminder_email_enabled=True,
        )
        original = followup.delivery_intent_ids.filtered(
            lambda item: item.intent_type == "callback_reminder"
        )
        self.assertEqual(len(original), 2)

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
        original.invalidate_recordset()
        self.assertEqual(set(original.mapped("state")), {"cancelled"})
        replacement = followup.delivery_intent_ids.filtered(
            lambda item: (
                item.intent_type == "callback_reminder"
                and item.state == "pending"
            )
        )
        self.assertEqual(len(replacement), 2)
        self.assertFalse(set(original.ids).intersection(replacement.ids))

    def test_calendar_cancellation_clears_schedule_but_preserves_followup(self):
        registration = self._register("cancel-calendar-event")
        followup = self._followup(registration, self.agent)
        self._complete(
            followup,
            disposition="callback",
            schedule_kind="callback",
            callback_at=fields.Datetime.now() + timedelta(hours=2),
            duration_minutes=30,
            reminder_email_enabled=True,
        )
        event = followup.calendar_event_id
        event.unlink()
        followup.invalidate_recordset()
        self.assertTrue(followup.exists())
        self.assertEqual(followup.state, "completed")
        self.assertEqual(followup.schedule_kind, "none")
        self.assertFalse(followup.callback_at)
        self.assertFalse(followup.calendar_event_id)
        active_reminders = followup.delivery_intent_ids.filtered(
            lambda item: (
                item.intent_type == "callback_reminder"
                and item.state in {"pending", "claimed"}
            )
        )
        self.assertFalse(active_reminders)

    def test_pending_action_is_recovered_only_for_assigned_agent(self):
        registration = self._register("pending-recovery-event")
        pending = self.env(user=self.agent)[
            "codestra.crm.call.followup"
        ].get_pending_post_call_actions(limit=10)
        other_pending = self.env(user=self.other_agent)[
            "codestra.crm.call.followup"
        ].get_pending_post_call_actions(limit=10)
        self.assertIn(
            registration["followup_id"],
            [item["followup_id"] for item in pending],
        )
        self.assertNotIn(
            registration["followup_id"],
            [item["followup_id"] for item in other_pending],
        )

    def test_replayed_wizard_does_not_duplicate_completion_side_effects(self):
        registration = self._register("replayed-wizard-event")
        followup = self._followup(registration, self.agent)
        values = {
            "followup_id": followup.id,
            "disposition": "contacted",
            "schedule_kind": "none",
            "send_post_call_email": True,
            "email_to": self.customer.email,
            "email_cc": self.agent.email,
            "email_subject": "Synthetic replay-safe follow-up",
            "email_body": "<p>Replay safety test.</p>",
        }
        agent_env = self.env(user=self.agent)
        first = agent_env["codestra.crm.post.call.wizard"].create(values)
        stale = agent_env["codestra.crm.post.call.wizard"].create(values)
        first.action_complete()
        followup.invalidate_recordset()
        first_intent = followup.immediate_delivery_intent_id
        first_messages = self.lead.message_ids.filtered(
            lambda item: "Post-call follow-up completed" in (item.body or "")
        )
        stale.action_complete()
        followup.invalidate_recordset()
        replay_messages = self.lead.message_ids.filtered(
            lambda item: "Post-call follow-up completed" in (item.body or "")
        )
        self.assertEqual(followup.immediate_delivery_intent_id, first_intent)
        self.assertEqual(len(replay_messages), len(first_messages))
        self.assertEqual(
            followup.delivery_intent_ids.filtered(
                lambda item: item.intent_type == "post_call_email"
            ),
            first_intent,
        )

    def test_completed_followup_cannot_be_cancelled(self):
        registration = self._register("completed-cancel-event")
        followup = self._followup(registration, self.agent)
        self._complete(followup)
        with self.assertRaises(ValidationError):
            followup.action_cancel_followup()

    def test_agent_notes_are_copied_to_crm_chatter(self):
        registration = self._register("chatter-notes-event")
        followup = self._followup(registration, self.agent)
        note = "Synthetic customer requested a proposal review."
        self._complete(followup, notes=note)
        message = self.lead.message_ids.filtered(
            lambda item: "Post-call follow-up completed" in (item.body or "")
        )[:1]
        self.assertTrue(message)
        self.assertIn(note, message.body)
