from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .test_call_followup import TestCodestraCrmCallFollowup


@tagged("post_install", "-at_install")
class TestCodestraCrmCallFollowupHardening(TestCodestraCrmCallFollowup):
    def test_missing_authoritative_end_timestamp_is_rejected(self):
        payload = self._payload("missing-ended-at")
        payload.pop("ended_at")
        service_env = self.env(user=self.service_user)

        with self.assertRaises(ValidationError):
            service_env[
                "codestra.crm.call.followup"
            ].register_completed_call(payload)

    def test_both_agent_selectors_are_rejected(self):
        payload = self._payload("ambiguous-agent")
        payload["agent_login"] = self.other_agent.login
        service_env = self.env(user=self.service_user)

        with self.assertRaises(ValidationError):
            service_env[
                "codestra.crm.call.followup"
            ].register_completed_call(payload)

    def test_mismatched_lead_customer_is_rejected(self):
        unrelated = self.env["res.partner"].create(
            {
                "name": "Unrelated Synthetic Customer",
                "email": "unrelated@test.invalid",
            }
        )
        payload = self._payload("mismatched-customer")
        payload["partner_id"] = unrelated.id
        service_env = self.env(user=self.service_user)

        with self.assertRaises(ValidationError):
            service_env[
                "codestra.crm.call.followup"
            ].register_completed_call(payload)

    def test_conflicting_event_replay_is_rejected(self):
        payload = self._payload("conflicting-replay")
        service_env = self.env(user=self.service_user)
        model = service_env["codestra.crm.call.followup"]
        first = model.register_completed_call(payload)

        conflicting = dict(payload, call_id="different-authoritative-call")
        with self.assertRaisesRegex(ValidationError, "idempotency_conflict"):
            model.register_completed_call(conflicting)

        followup = self.env["codestra.crm.call.followup"].sudo().browse(
            first["followup_id"]
        )
        self.assertEqual(followup.call_id, payload["call_id"])

    def test_exact_event_replay_uses_same_fingerprint(self):
        payload = self._payload("exact-replay")
        service_env = self.env(user=self.service_user)
        model = service_env["codestra.crm.call.followup"]

        first = model.register_completed_call(payload)
        second = model.register_completed_call(dict(payload))

        self.assertEqual(first["followup_id"], second["followup_id"])
        self.assertTrue(second["replayed"])

    def test_cancel_rechecks_locked_database_state(self):
        registration = self._register("cancel-stale-cache")
        followup = self.env(user=self.agent)[
            "codestra.crm.call.followup"
        ].browse(registration["followup_id"])
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
        agent_env = self.env(user=self.agent)
        followup = agent_env["codestra.crm.call.followup"].browse(
            registration["followup_id"]
        )
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
        agent_env = self.env(user=self.agent)
        followup = agent_env["codestra.crm.call.followup"].browse(
            registration["followup_id"]
        )
        wizard = agent_env["codestra.crm.post.call.wizard"].create(
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
        pending = agent_env[
            "codestra.crm.call.followup"
        ].get_pending_post_call_actions(limit=20)
        self.assertNotIn(
            followup.id,
            [item["followup_id"] for item in pending],
        )

    def test_archived_calendar_event_relinks_when_reactivated(self):
        registration = self._register("calendar-reactivation")
        agent_env = self.env(user=self.agent)
        followup = agent_env["codestra.crm.call.followup"].browse(
            registration["followup_id"]
        )
        callback_at = fields.Datetime.now() + timedelta(hours=2)
        agent_env["codestra.crm.post.call.wizard"].create(
            {
                "followup_id": followup.id,
                "disposition": "callback",
                "schedule_kind": "callback",
                "callback_at": callback_at,
                "duration_minutes": 30,
                "reminder_email_enabled": True,
                "send_post_call_email": False,
            }
        ).action_complete()

        followup.invalidate_recordset()
        event = followup.calendar_event_id
        event.active = False
        followup.invalidate_recordset()
        self.assertEqual(followup.schedule_kind, "none")
        self.assertEqual(followup.calendar_event_id, event)

        event.active = True
        followup.invalidate_recordset()
        self.assertEqual(followup.calendar_event_id, event)
        self.assertEqual(followup.schedule_kind, "callback")
        self.assertEqual(followup.callback_at, callback_at)

    def test_pending_recovery_supports_multiple_pages(self):
        agent_env = self.env(user=self.agent)
        followup_ids = []
        for index in range(21):
            registration = self._register(f"pending-page-{index}")
            followup_ids.append(registration["followup_id"])

        first_page = agent_env[
            "codestra.crm.call.followup"
        ].get_pending_post_call_actions(limit=20)
        first_ids = [item["followup_id"] for item in first_page]
        second_page = agent_env[
            "codestra.crm.call.followup"
        ].get_pending_post_call_actions(limit=20, exclude_ids=first_ids)
        second_ids = [item["followup_id"] for item in second_page]

        self.assertEqual(len(first_ids), 20)
        self.assertTrue(set(followup_ids).issubset(set(first_ids + second_ids)))
        self.assertFalse(set(first_ids).intersection(second_ids))
