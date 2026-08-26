from datetime import timedelta

from odoo import fields
from odoo.fields import Command
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCodestraCallFollowupAutomation(TransactionCase):
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
                "name": "Automation Agent",
                "login": "automation-agent@test.invalid",
                "email": "automation-agent@test.invalid",
                "company_id": cls.company.id,
                "company_ids": [Command.set([cls.company.id])],
                "group_ids": [Command.set([base_user.id, agent_group.id])],
            }
        )
        cls.service = cls.env["res.users"].with_context(no_reset_password=True).create(
            {
                "name": "Automation Integration",
                "login": "automation-integration@test.invalid",
                "email": "automation-integration@test.invalid",
                "company_id": cls.company.id,
                "company_ids": [Command.set([cls.company.id])],
                "group_ids": [Command.set([base_user.id, service_group.id])],
            }
        )
        cls.customer = cls.env["res.partner"].create(
            {"name": "Automation Customer", "email": "automation-customer@test.invalid"}
        )
        cls.policy = cls.env["codestra.crm.call.followup.policy"].create(
            {
                "name": "Automation Test Policy",
                "company_id": cls.company.id,
                "pending_sla_minutes": 5,
                "callback_grace_minutes": 5,
                "max_attempts": 3,
                "retry_base_minutes": 1,
                "escalation_user_id": cls.agent.id,
            }
        )

    def _register(self, event_id, ended_at=None):
        ended_at = ended_at or fields.Datetime.now()
        payload = {
            "event_id": event_id,
            "company_id": self.company.id,
            "agent_user_id": self.agent.id,
            "partner_id": self.customer.id,
            "source": "automation-test",
            "started_at": fields.Datetime.to_string(ended_at - timedelta(minutes=2)),
            "ended_at": fields.Datetime.to_string(ended_at),
            "duration_seconds": 120,
        }
        response = self.env(user=self.service)[
            "codestra.crm.call.followup"
        ].register_completed_call(payload)
        return self.env["codestra.crm.call.followup"].browse(response["followup_id"])

    def test_pending_sla_job_is_idempotent_and_creates_one_activity(self):
        followup = self._register(
            "automation-pending-sla",
            fields.Datetime.now() - timedelta(minutes=20),
        )
        Job = self.env["codestra.crm.call.followup.job"]

        first = Job._cron_enqueue_due_jobs(company_ids=[self.company.id])
        second = Job._cron_enqueue_due_jobs(company_ids=[self.company.id])
        processed = Job._cron_process_jobs()

        jobs = Job.search(
            [("followup_id", "=", followup.id), ("job_type", "=", "pending_sla")]
        )
        self.assertEqual(first, 1)
        self.assertEqual(second, 0)
        self.assertEqual(processed, 1)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs.state, "done")
        self.assertTrue(jobs.activity_id)
        followup.invalidate_recordset()
        self.assertTrue(followup.automation_pending_sla_at)

    def test_missed_callback_creates_escalation_activity(self):
        followup = self._register("automation-missed-callback")
        followup._write_from_workflow(
            {
                "state": "completed",
                "popup_completed_at": fields.Datetime.now(),
                "schedule_kind": "callback",
                "callback_at": fields.Datetime.now() - timedelta(minutes=30),
            }
        )
        Job = self.env["codestra.crm.call.followup.job"]
        Job._cron_enqueue_due_jobs(company_ids=[self.company.id])
        Job._cron_process_jobs()

        job = Job.search(
            [("followup_id", "=", followup.id), ("job_type", "=", "missed_callback")],
            limit=1,
        )
        self.assertEqual(job.state, "done")
        self.assertTrue(job.activity_id)
        followup.invalidate_recordset()
        self.assertTrue(followup.automation_missed_callback_at)

    def test_reminder_health_repairs_missing_alarms(self):
        followup = self._register("automation-reminder-health")
        callback_at = fields.Datetime.now() + timedelta(hours=3)
        wizard = self.env(user=self.agent)["codestra.crm.post.call.wizard"].create(
            {
                "followup_id": followup.id,
                "disposition": "callback",
                "schedule_kind": "callback",
                "callback_at": callback_at,
                "duration_minutes": 30,
                "reminder_email_enabled": True,
                "send_post_call_email": False,
            }
        )
        wizard.action_complete()
        followup.invalidate_recordset()
        event = followup.calendar_event_id
        event.with_context(skip_codestra_followup_sync=True).write(
            {"alarm_ids": [Command.clear()]}
        )

        Job = self.env["codestra.crm.call.followup.job"]
        Job._cron_enqueue_due_jobs(company_ids=[self.company.id])
        Job._cron_process_jobs()

        event.invalidate_recordset()
        expected = {
            self.env.ref(
                "codestra_crm_call_followup.calendar_alarm_prepare_30_minutes"
            ).id,
            self.env.ref(
                "codestra_crm_call_followup.calendar_alarm_email_15_minutes"
            ).id,
        }
        self.assertTrue(expected.issubset(set(event.alarm_ids.ids)))
        followup.invalidate_recordset()
        self.assertTrue(followup.automation_reminders_repaired_at)
