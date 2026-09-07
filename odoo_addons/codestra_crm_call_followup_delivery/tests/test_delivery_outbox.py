from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError
from odoo.fields import Command
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCodestraCrmCallDeliveryOutbox(TransactionCase):
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

        cls.agent = cls.env["res.users"].with_context(no_reset_password=True).create(
            {
                "name": "Delivery Agent",
                "login": "delivery-agent@test.invalid",
                "email": "delivery-agent@test.invalid",
                "company_id": cls.company.id,
                "company_ids": [Command.set([cls.company.id])],
                "group_ids": [Command.set([base_user.id, agent_group.id])],
            }
        )
        cls.other_agent = cls.env["res.users"].with_context(no_reset_password=True).create(
            {
                "name": "Other Delivery Agent",
                "login": "other-delivery-agent@test.invalid",
                "email": "other-delivery-agent@test.invalid",
                "company_id": cls.company.id,
                "company_ids": [Command.set([cls.company.id])],
                "group_ids": [Command.set([base_user.id, agent_group.id])],
            }
        )
        cls.manager = cls.env["res.users"].with_context(no_reset_password=True).create(
            {
                "name": "Delivery Manager",
                "login": "delivery-manager@test.invalid",
                "email": "delivery-manager@test.invalid",
                "company_id": cls.company.id,
                "company_ids": [Command.set([cls.company.id])],
                "group_ids": [Command.set([base_user.id, manager_group.id])],
            }
        )
        cls.service_user = cls.env["res.users"].with_context(no_reset_password=True).create(
            {
                "name": "Delivery Integration Service",
                "login": "delivery-service@test.invalid",
                "email": "delivery-service@test.invalid",
                "company_id": cls.company.id,
                "company_ids": [Command.set([cls.company.id])],
                "group_ids": [Command.set([base_user.id, service_group.id])],
            }
        )
        cls.customer = cls.env["res.partner"].create(
            {
                "name": "Delivery Customer",
                "email": "delivery-customer@test.invalid",
            }
        )
        cls.lead = cls.env["crm.lead"].create(
            {
                "name": "Delivery Opportunity",
                "type": "opportunity",
                "company_id": cls.company.id,
                "user_id": cls.agent.id,
                "partner_id": cls.customer.id,
            }
        )

    def _complete_with_email(self, event_id):
        ended_at = fields.Datetime.now()
        registration = self.env(user=self.service_user)[
            "codestra.crm.call.followup"
        ].register_completed_call(
            {
                "api_version": "1.0",
                "event_id": event_id,
                "company_id": self.company.id,
                "agent_user_id": self.agent.id,
                "lead_id": self.lead.id,
                "partner_id": self.customer.id,
                "started_at": fields.Datetime.to_string(
                    ended_at - timedelta(minutes=3)
                ),
                "ended_at": fields.Datetime.to_string(ended_at),
                "duration_seconds": 180,
                "call_direction": "outbound",
            }
        )
        agent_env = self.env(user=self.agent)
        followup = agent_env["codestra.crm.call.followup"].browse(
            registration["followup_id"]
        )
        agent_env["codestra.crm.post.call.wizard"].create(
            {
                "followup_id": followup.id,
                "disposition": "contacted",
                "notes": "<p>Send the requested summary.</p>",
                "schedule_kind": "none",
                "send_post_call_email": True,
                "email_to": self.customer.email,
                "email_cc": self.agent.email,
                "email_subject": "Requested summary",
                "email_body": "<p>Thank you for your time.</p>",
            }
        ).action_complete()
        delivery = self.env["codestra.crm.call.delivery"].sudo().search(
            [("followup_id", "=", followup.id)], limit=1
        )
        return followup.sudo(), delivery

    def test_completion_creates_one_auditable_delivery(self):
        followup, delivery = self._complete_with_email("delivery-created")

        self.assertTrue(delivery)
        self.assertEqual(delivery.state, "queued")
        self.assertEqual(delivery.followup_id, followup)
        self.assertEqual(delivery.mail_id, followup.mail_id)
        self.assertFalse(delivery.mail_id.auto_delete)
        self.assertTrue(delivery.idempotency_key)
        self.assertTrue(delivery.recipient_hash)

    def test_enqueue_is_idempotent(self):
        followup, delivery = self._complete_with_email("delivery-idempotent")
        second = self.env["codestra.crm.call.delivery"].enqueue_post_call_email(
            followup,
            delivery.mail_id,
            email_to=delivery.email_to,
            email_cc=delivery.email_cc,
            subject=delivery.subject,
            body_html=delivery.body_html,
        )

        self.assertEqual(second, delivery)
        self.assertEqual(
            self.env["codestra.crm.call.delivery"].sudo().search_count(
                [("followup_id", "=", followup.id)]
            ),
            1,
        )

    def test_reconcile_marks_sent(self):
        _, delivery = self._complete_with_email("delivery-sent")
        delivery.mail_id.sudo().write({"state": "sent"})

        self.env["codestra.crm.call.delivery"]._cron_reconcile_mail_states()
        delivery.invalidate_recordset()
        self.assertEqual(delivery.state, "sent")
        self.assertTrue(delivery.sent_at)

    def test_reconcile_skips_outgoing_backlog_and_processes_terminal_mail(self):
        _, outgoing = self._complete_with_email("delivery-outgoing-backlog")
        _, sent = self._complete_with_email("delivery-terminal-behind-backlog")
        self.assertLess(outgoing.id, sent.id)
        sent.mail_id.sudo().write({"state": "sent"})

        self.env["codestra.crm.call.delivery"]._cron_reconcile_mail_states(limit=1)

        outgoing.invalidate_recordset()
        sent.invalidate_recordset()
        self.assertEqual(outgoing.state, "queued")
        self.assertEqual(sent.state, "sent")

    def test_reconcile_preserves_native_mail_cancellation(self):
        _, delivery = self._complete_with_email("delivery-native-cancel")
        delivery.mail_id.sudo().write({"state": "cancel"})

        self.env["codestra.crm.call.delivery"]._cron_reconcile_mail_states()

        delivery.invalidate_recordset()
        self.assertEqual(delivery.state, "cancelled")
        self.assertFalse(delivery.next_attempt_at)

    def test_reconcile_preserves_cancellation_after_delivery_failed(self):
        _, delivery = self._complete_with_email("delivery-failed-then-cancelled")
        delivery._write_from_worker({"state": "failed", "attempt_count": 1})
        delivery.mail_id.sudo().write({"state": "cancel"})

        self.env["codestra.crm.call.delivery"]._cron_reconcile_mail_states()

        delivery.invalidate_recordset()
        self.assertEqual(delivery.state, "cancelled")
        self.assertFalse(delivery.next_attempt_at)

    def test_exception_schedules_retry_and_cron_requeues_mail(self):
        _, delivery = self._complete_with_email("delivery-retry")
        delivery.mail_id.sudo().write(
            {"state": "exception", "failure_reason": "synthetic SMTP failure"}
        )
        self.env["codestra.crm.call.delivery"]._cron_reconcile_mail_states()
        delivery.invalidate_recordset()

        self.assertEqual(delivery.state, "failed")
        self.assertEqual(delivery.attempt_count, 1)
        self.assertTrue(delivery.next_attempt_at)
        self.assertIn("synthetic", delivery.last_error)

        delivery._write_from_worker(
            {"next_attempt_at": fields.Datetime.now() - timedelta(seconds=1)}
        )
        self.env["codestra.crm.call.delivery"]._cron_retry_failed()
        delivery.invalidate_recordset()
        self.assertEqual(delivery.state, "queued")
        self.assertEqual(delivery.mail_id.state, "outgoing")
        self.assertFalse(delivery.last_error)

    def test_retry_budget_moves_delivery_to_dead_letter(self):
        _, delivery = self._complete_with_email("delivery-dead")
        delivery._write_from_worker({"attempt_count": 4})
        delivery.mail_id.sudo().write(
            {"state": "exception", "failure_reason": "final synthetic failure"}
        )
        self.env["codestra.crm.call.delivery"]._cron_reconcile_mail_states()
        delivery.invalidate_recordset()

        self.assertEqual(delivery.state, "dead")
        self.assertEqual(delivery.attempt_count, 5)
        self.assertFalse(delivery.next_attempt_at)

    def test_agent_cannot_retry_or_delete_delivery(self):
        _, delivery = self._complete_with_email("delivery-agent-denied")
        agent_delivery = self.env(user=self.agent)[
            "codestra.crm.call.delivery"
        ].browse(delivery.id)

        with self.assertRaises(AccessError):
            agent_delivery.action_retry_now()
        with self.assertRaises(AccessError):
            delivery.unlink()

    def test_manager_can_retry_failed_delivery(self):
        _, delivery = self._complete_with_email("delivery-manager-retry")
        delivery.mail_id.sudo().write(
            {"state": "exception", "failure_reason": "manager retry test"}
        )
        self.env["codestra.crm.call.delivery"]._cron_reconcile_mail_states()
        manager_delivery = self.env(user=self.manager)[
            "codestra.crm.call.delivery"
        ].browse(delivery.id)
        self.assertTrue(manager_delivery.action_retry_now())
        delivery.invalidate_recordset()
        self.assertEqual(delivery.state, "queued")

    def test_manager_can_recover_dead_letter_with_one_new_attempt(self):
        _, delivery = self._complete_with_email("delivery-manager-dead-retry")
        delivery._write_from_worker({"state": "dead", "attempt_count": 5})

        self.env(user=self.manager)["codestra.crm.call.delivery"].browse(
            delivery.id
        ).action_retry_now()

        delivery.invalidate_recordset()
        self.assertEqual(delivery.state, "queued")
        self.assertEqual(delivery.max_attempts, 6)

    def test_retry_reconciles_already_sent_linked_mail(self):
        _, delivery = self._complete_with_email("delivery-retry-already-sent")
        mail = delivery.mail_id
        delivery._write_from_worker({"state": "failed", "attempt_count": 1})
        mail.sudo().write({"state": "sent"})

        self.env(user=self.manager)["codestra.crm.call.delivery"].browse(
            delivery.id
        ).action_retry_now()

        delivery.invalidate_recordset()
        self.assertEqual(delivery.state, "sent")
        self.assertEqual(delivery.mail_id, mail)

    def test_cancel_reconciles_already_sent_linked_mail(self):
        _, delivery = self._complete_with_email("delivery-cancel-already-sent")
        mail = delivery.mail_id
        mail.sudo().write({"state": "sent"})

        self.env(user=self.manager)["codestra.crm.call.delivery"].browse(
            delivery.id
        ).action_cancel()

        delivery.invalidate_recordset()
        self.assertEqual(delivery.state, "sent")
        self.assertEqual(delivery.mail_id, mail)

    def test_cancel_moves_failed_linked_mail_to_terminal_cancel(self):
        _, delivery = self._complete_with_email("delivery-cancel-failed-mail")
        mail = delivery.mail_id
        mail.sudo().write({"state": "exception"})
        delivery._write_from_worker({"state": "failed", "attempt_count": 1})

        self.env(user=self.manager)["codestra.crm.call.delivery"].browse(
            delivery.id
        ).action_cancel()

        delivery.invalidate_recordset()
        mail.invalidate_recordset()
        self.assertEqual(delivery.state, "cancelled")
        self.assertEqual(mail.state, "cancel")

    def test_reconcile_fails_queued_delivery_when_linked_mail_is_removed(self):
        _, delivery = self._complete_with_email("delivery-missing-mail")
        delivery.mail_id.sudo().unlink()

        self.env["codestra.crm.call.delivery"]._cron_reconcile_mail_states()

        delivery.invalidate_recordset()
        self.assertEqual(delivery.state, "failed")
        self.assertEqual(delivery.attempt_count, 1)
        self.assertIn("missing", delivery.last_error.lower())

    def test_other_agent_cannot_read_delivery(self):
        _, delivery = self._complete_with_email("delivery-isolation")
        other_env = self.env(user=self.other_agent)
        self.assertFalse(
            other_env["codestra.crm.call.delivery"].search(
                [("id", "=", delivery.id)]
            )
        )
