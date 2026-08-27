from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged

from .test_call_followup import TestCodestraCrmCallFollowup


@tagged("post_install", "-at_install")
class TestCodestraCrmCallFollowupHardening(TestCodestraCrmCallFollowup):
    def test_missing_authoritative_end_timestamp_is_rejected(self):
        payload = self._payload("missing-ended-at")
        payload.pop("ended_at")
        with self.assertRaises(ValidationError):
            self._register("missing-ended-at", payload)

    def test_both_agent_selectors_are_rejected(self):
        payload = self._payload("ambiguous-agent")
        payload["agent_login"] = self.other_agent.login
        with self.assertRaises(ValidationError):
            self._register("ambiguous-agent", payload)

    def test_mismatched_lead_customer_is_rejected(self):
        unrelated = self.env["res.partner"].create(
            {
                "name": "Unrelated Synthetic Customer",
                "email": "unrelated@test.invalid",
            }
        )
        payload = self._payload("mismatched-customer")
        payload["partner_id"] = unrelated.id
        with self.assertRaises(ValidationError):
            self._register("mismatched-customer", payload)

    def test_conflicting_event_replay_is_rejected(self):
        payload = self._payload("conflicting-replay")
        first = self._register("conflicting-replay", payload)
        conflicting = dict(payload, call_id="different-authoritative-call")
        with self.assertRaisesRegex(ValidationError, "idempotency_conflict"):
            self._register("conflicting-replay", conflicting)
        followup = self.env["codestra.crm.call.followup"].sudo().browse(
            first["followup_id"]
        )
        self.assertEqual(followup.call_id, payload["call_id"])

    def test_fallback_customer_identity_is_part_of_replay_fingerprint(self):
        payload = self._payload("fallback-replay")
        payload.pop("lead_id")
        payload.pop("partner_id")
        payload["customer_name"] = "Fallback Customer A"
        payload["customer_email"] = "fallback-a@test.invalid"
        self._register("fallback-replay", payload)

        conflict = dict(
            payload,
            customer_name="Fallback Customer B",
            customer_email="fallback-b@test.invalid",
        )
        with self.assertRaisesRegex(ValidationError, "idempotency_conflict"):
            self._register("fallback-replay", conflict)

    def test_exact_lead_only_replay_survives_later_partner_change(self):
        lead = self.env["crm.lead"].create(
            {
                "name": "Initially Unlinked Lead",
                "type": "opportunity",
                "company_id": self.company.id,
                "user_id": self.agent.id,
            }
        )
        payload = self._payload("lead-only-replay")
        payload["lead_id"] = lead.id
        payload.pop("partner_id")
        first = self._register("lead-only-replay", payload)

        later_partner = self.env["res.partner"].create(
            {
                "name": "Later Linked Customer",
                "email": "later@test.invalid",
            }
        )
        lead.partner_id = later_partner
        second = self._register("lead-only-replay", dict(payload))
        self.assertEqual(first["followup_id"], second["followup_id"])
        self.assertTrue(second["replayed"])

    def test_legacy_resolved_hash_is_upgraded_on_verified_replay(self):
        payload = self._payload("legacy-hash-upgrade")
        first = self._register("legacy-hash-upgrade", payload)
        followup = self.env["codestra.crm.call.followup"].sudo().browse(
            first["followup_id"]
        )
        followup._write_from_workflow(
            {"payload_hash": "legacy-resolved-hash", "payload_hash_version": 0}
        )
        second = self._register("legacy-hash-upgrade", dict(payload))
        followup.invalidate_recordset()
        self.assertTrue(second["replayed"])
        self.assertEqual(followup.payload_hash_version, 2)
        self.assertNotEqual(followup.payload_hash, "legacy-resolved-hash")

    def test_cancel_rechecks_locked_database_state(self):
        registration = self._register("cancel-stale-cache")
        followup = self._followup(registration, self.agent)
        self.assertEqual(followup.state, "pending")
        self.env.cr.execute(
            "UPDATE codestra_crm_call_followup SET state = 'completed' WHERE id = %s",
            [followup.id],
        )
        with self.assertRaises(ValidationError):
            followup.action_cancel_followup()
        followup.invalidate_recordset(["state"])
        self.assertEqual(followup.state, "completed")

    def test_save_draft_preserves_disabled_email_preference(self):
        registration = self._register("save-draft")
        followup = self._followup(registration, self.agent)
        agent_env = self.env(user=self.agent)
        wizard = agent_env["codestra.crm.post.call.wizard"].create(
            {
                "followup_id": followup.id,
                "disposition": "contacted",
                "notes": "Synthetic saved draft note.",
                "schedule_kind": "none",
                "send_post_call_email": False,
            }
        )
        wizard.action_save_draft()
        followup.invalidate_recordset()
        self.assertEqual(followup.state, "pending")
        self.assertTrue(followup.draft_saved_at)
        self.assertFalse(followup.send_post_call_email)
        self.assertIn("Synthetic saved draft note", followup.notes)
        reopened = agent_env["codestra.crm.post.call.wizard"].with_context(
            default_followup_id=followup.id
        ).new({})
        self.assertFalse(reopened.send_post_call_email)

    def test_snoozed_followup_is_temporarily_excluded(self):
        registration = self._register("snooze-followup")
        followup = self._followup(registration, self.agent)
        wizard = self.env(user=self.agent)[
            "codestra.crm.post.call.wizard"
        ].create(
            {
                "followup_id": followup.id,
                "disposition": "contacted",
                "schedule_kind": "none",
                "send_post_call_email": False,
            }
        )
        wizard.action_snooze_10_minutes()
        followup.invalidate_recordset()
        self.assertGreater(followup.snoozed_until, fields.Datetime.now())
        pending = self.env(user=self.agent)[
            "codestra.crm.call.followup"
        ].get_pending_post_call_actions(limit=20)
        self.assertNotIn(
            followup.id,
            [item["followup_id"] for item in pending],
        )

    def test_archived_legacy_event_restores_null_schedule_kind(self):
        registration = self._register("calendar-reactivation")
        followup = self._followup(registration, self.agent)
        callback_at = fields.Datetime.now() + timedelta(hours=2)
        self._complete(
            followup,
            disposition="callback",
            schedule_kind="callback",
            callback_at=callback_at,
            duration_minutes=30,
            reminder_email_enabled=True,
        )
        event = followup.calendar_event_id
        event.with_context(skip_codestra_followup_sync=True).write(
            {"codestra_schedule_kind": False}
        )
        event.active = False
        followup.invalidate_recordset()
        event.invalidate_recordset()
        self.assertEqual(followup.schedule_kind, "none")
        self.assertEqual(event.codestra_schedule_kind, "callback")
        event.active = True
        followup.invalidate_recordset()
        self.assertEqual(followup.calendar_event_id, event)
        self.assertEqual(followup.schedule_kind, "callback")
        self.assertEqual(followup.callback_at, callback_at)

    def test_pending_cursor_reaches_more_than_220_records(self):
        ended_at = fields.Datetime.now() - timedelta(days=1)
        values = []
        for index in range(225):
            values.append(
                {
                    "name": f"Bulk pending {index}",
                    "event_id": f"bulk-pending-{index}",
                    "company_id": self.company.id,
                    "agent_id": self.agent.id,
                    "ended_at": ended_at,
                    "duration_seconds": 1,
                    "source": "cursor-test",
                    "popup_requested_at": fields.Datetime.now(),
                }
            )
        created = self.env["codestra.crm.call.followup"].sudo().create(values)
        agent_model = self.env(user=self.agent)["codestra.crm.call.followup"]
        collected = []
        after_ended_at = False
        after_id = False
        for _page in range(20):
            page = agent_model.get_pending_post_call_actions(
                limit=20,
                after_ended_at=after_ended_at,
                after_id=after_id,
            )
            if not page:
                break
            collected.extend(item["followup_id"] for item in page)
            after_ended_at = page[-1]["ended_at"]
            after_id = page[-1]["followup_id"]
        self.assertTrue(set(created.ids).issubset(set(collected)))
        self.assertEqual(len(collected), len(set(collected)))

    def test_delivery_intent_cannot_be_created_or_changed_directly(self):
        registration = self._register("intent-access")
        followup = self._followup(registration, self.agent)
        self._complete(
            followup,
            send_post_call_email=True,
            email_to=self.customer.email,
            email_subject="Intent access",
            email_body="<p>Intent access.</p>",
        )
        intent = followup.immediate_delivery_intent_id
        with self.assertRaises(AccessError):
            intent.with_user(self.service_user).write({"state": "delivered"})
        with self.assertRaises(AccessError):
            self.env["codestra.crm.call.delivery.intent"].sudo().create(
                {
                    "name": "Bypass",
                    "company_id": self.company.id,
                    "followup_id": followup.id,
                    "intent_type": "post_call_email",
                    "audience": "client",
                    "idempotency_key": "bypass",
                    "available_at": fields.Datetime.now(),
                    "recipient_to": self.customer.email,
                    "subject": "Bypass",
                }
            )
