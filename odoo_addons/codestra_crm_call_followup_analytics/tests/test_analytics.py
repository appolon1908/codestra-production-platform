from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError
from odoo.fields import Command
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCodestraCallFollowupAnalytics(TransactionCase):
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
                "name": "Analytics Agent",
                "login": "analytics-agent@test.invalid",
                "email": "analytics-agent@test.invalid",
                "company_id": cls.company.id,
                "company_ids": [Command.set([cls.company.id])],
                "group_ids": [Command.set([base_user.id, agent_group.id])],
            }
        )
        cls.other_agent = cls.env["res.users"].with_context(no_reset_password=True).create(
            {
                "name": "Other Analytics Agent",
                "login": "other-analytics-agent@test.invalid",
                "email": "other-analytics-agent@test.invalid",
                "company_id": cls.company.id,
                "company_ids": [Command.set([cls.company.id])],
                "group_ids": [Command.set([base_user.id, agent_group.id])],
            }
        )
        cls.manager = cls.env["res.users"].with_context(no_reset_password=True).create(
            {
                "name": "Analytics Manager",
                "login": "analytics-manager@test.invalid",
                "email": "analytics-manager@test.invalid",
                "company_id": cls.company.id,
                "company_ids": [Command.set([cls.company.id])],
                "group_ids": [Command.set([base_user.id, manager_group.id])],
            }
        )
        cls.service = cls.env["res.users"].with_context(no_reset_password=True).create(
            {
                "name": "Analytics Integration",
                "login": "analytics-integration@test.invalid",
                "email": "analytics-integration@test.invalid",
                "company_id": cls.company.id,
                "company_ids": [Command.set([cls.company.id])],
                "group_ids": [Command.set([base_user.id, service_group.id])],
            }
        )

    def _register(self, event_id, agent=None, ended_at=None):
        agent = agent or self.agent
        ended_at = ended_at or fields.Datetime.now()
        payload = {
            "event_id": event_id,
            "company_id": self.company.id,
            "agent_user_id": agent.id,
            "source": "analytics-test",
            "started_at": fields.Datetime.to_string(ended_at - timedelta(minutes=3)),
            "ended_at": fields.Datetime.to_string(ended_at),
            "duration_seconds": 180,
        }
        response = self.env(user=self.service)[
            "codestra.crm.call.followup"
        ].register_completed_call(payload)
        return self.env["codestra.crm.call.followup"].browse(response["followup_id"])

    def test_report_reflects_pending_and_completed_calls(self):
        pending = self._register(
            "analytics-pending",
            ended_at=fields.Datetime.now() - timedelta(minutes=15),
        )
        completed = self._register(
            "analytics-completed",
            ended_at=fields.Datetime.now() - timedelta(minutes=2),
        )
        completed._write_from_workflow(
            {
                "state": "completed",
                "disposition": "contacted",
                "popup_completed_at": fields.Datetime.now(),
            }
        )
        self.env["codestra.crm.call.followup"].flush_model()

        reports = self.env(user=self.manager)[
            "codestra.crm.call.followup.report"
        ].search([("followup_id", "in", [pending.id, completed.id])])
        self.assertEqual(len(reports), 2)
        self.assertEqual(len(reports.filtered("is_pending")), 1)
        self.assertEqual(len(reports.filtered("is_completed")), 1)
        self.assertTrue(reports.filtered("is_completed").completed_within_5_minutes)

    def test_agent_report_rule_hides_other_agent(self):
        own = self._register("analytics-own", agent=self.agent)
        other = self._register("analytics-other", agent=self.other_agent)
        reports = self.env(user=self.agent)[
            "codestra.crm.call.followup.report"
        ].search([("followup_id", "in", [own.id, other.id])])
        self.assertEqual(reports.mapped("followup_id").ids, [own.id])

    def test_manager_summary_api_returns_scoped_kpis(self):
        first = self._register("analytics-api-pending")
        second = self._register("analytics-api-completed")
        second._write_from_workflow(
            {
                "state": "completed",
                "disposition": "appointment",
                "schedule_kind": "appointment",
                "callback_at": fields.Datetime.now() + timedelta(days=1),
                "popup_completed_at": fields.Datetime.now(),
            }
        )
        today = fields.Date.context_today(self)
        result = self.env(user=self.manager)[
            "codestra.crm.call.followup.analytics.api"
        ].summary_v1(
            date_from=fields.Date.to_string(today),
            date_to=fields.Date.to_string(today),
            company_ids=[self.company.id],
        )
        self.assertGreaterEqual(result["metrics"]["total_calls"], 2)
        self.assertGreaterEqual(result["metrics"]["pending"], 1)
        self.assertGreaterEqual(result["metrics"]["completed"], 1)
        self.assertGreaterEqual(result["metrics"]["appointments"], 1)

    def test_report_is_read_only_for_agent(self):
        followup = self._register("analytics-read-only")
        report = self.env(user=self.agent)[
            "codestra.crm.call.followup.report"
        ].search([("followup_id", "=", followup.id)], limit=1)
        with self.assertRaises(AccessError):
            report.write({"name": "mutated"})

    def test_summary_date_window_uses_manager_timezone(self):
        self.manager.tz = "America/Santo_Domingo"
        call = self._register(
            "analytics-local-day",
            ended_at=fields.Datetime.to_datetime("2026-08-27 00:30:00"),
        )
        result = self.env(user=self.manager)[
            "codestra.crm.call.followup.analytics.api"
        ].summary_v1(date_from="2026-08-26", date_to="2026-08-26")
        self.assertGreaterEqual(result["metrics"]["total_calls"], 1)
        report = self.env["codestra.crm.call.followup.report"].search([
            ("followup_id", "=", call.id)
        ])
        self.assertTrue(report)
