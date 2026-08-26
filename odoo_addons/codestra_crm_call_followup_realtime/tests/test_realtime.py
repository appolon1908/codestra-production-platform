from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError
from odoo.fields import Command
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCodestraCallFollowupRealtime(TransactionCase):
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
                "name": "Realtime Agent",
                "login": "realtime-agent@test.invalid",
                "email": "realtime-agent@test.invalid",
                "company_id": cls.company.id,
                "company_ids": [Command.set([cls.company.id])],
                "group_ids": [Command.set([base_user.id, agent_group.id])],
            }
        )
        cls.other_agent = cls.env["res.users"].with_context(no_reset_password=True).create(
            {
                "name": "Other Realtime Agent",
                "login": "other-realtime-agent@test.invalid",
                "email": "other-realtime-agent@test.invalid",
                "company_id": cls.company.id,
                "company_ids": [Command.set([cls.company.id])],
                "group_ids": [Command.set([base_user.id, agent_group.id])],
            }
        )
        cls.service = cls.env["res.users"].with_context(no_reset_password=True).create(
            {
                "name": "Realtime Integration",
                "login": "realtime-integration@test.invalid",
                "email": "realtime-integration@test.invalid",
                "company_id": cls.company.id,
                "company_ids": [Command.set([cls.company.id])],
                "group_ids": [Command.set([base_user.id, service_group.id])],
            }
        )

    def _register(self, event_id):
        ended_at = fields.Datetime.now()
        payload = {
            "event_id": event_id,
            "company_id": self.company.id,
            "agent_user_id": self.agent.id,
            "ended_at": fields.Datetime.to_string(ended_at),
            "started_at": fields.Datetime.to_string(ended_at - timedelta(minutes=2)),
            "duration_seconds": 120,
            "source": "realtime-test",
        }
        response = self.env(user=self.service)[
            "codestra.crm.call.followup"
        ].register_completed_call(payload)
        return self.env["codestra.crm.call.followup"].browse(response["followup_id"])

    def test_one_browser_claim_excludes_another(self):
        followup = self._register("rt-exclusive")
        record = self.env(user=self.agent)["codestra.crm.call.followup"].browse(followup.id)

        first = record.rt_claim_v1("browser-one", lease_seconds=90)
        second = record.rt_claim_v1("browser-two", lease_seconds=90)

        self.assertEqual(first["status"], "claimed")
        self.assertTrue(first["claim_token"])
        self.assertEqual(second["status"], "busy")

    def test_same_browser_can_reclaim_and_renew(self):
        followup = self._register("rt-renew")
        record = self.env(user=self.agent)["codestra.crm.call.followup"].browse(followup.id)
        claim = record.rt_claim_v1("browser-one")
        renewed = record.rt_renew_v1(claim["claim_token"], lease_seconds=120)

        self.assertEqual(renewed["status"], "renewed")
        self.assertEqual(renewed["claim_token"], claim["claim_token"])

    def test_release_makes_action_available(self):
        followup = self._register("rt-release")
        record = self.env(user=self.agent)["codestra.crm.call.followup"].browse(followup.id)
        claim = record.rt_claim_v1("browser-one")
        released = record.rt_release_v1(claim["claim_token"], reason="navigation")
        next_claim = record.rt_claim_v1("browser-two")

        self.assertEqual(released["status"], "released")
        self.assertEqual(next_claim["status"], "claimed")

    def test_other_agent_cannot_claim(self):
        followup = self._register("rt-assigned-only")
        record = self.env(user=self.other_agent)["codestra.crm.call.followup"].browse(
            followup.id
        )
        with self.assertRaises(AccessError):
            record.rt_claim_v1("other-browser")

    def test_expired_claim_is_recovered(self):
        followup = self._register("rt-expired")
        record = self.env(user=self.agent)["codestra.crm.call.followup"].browse(followup.id)
        claim = record.rt_claim_v1("browser-one")
        self.assertEqual(claim["status"], "claimed")

        followup.sudo()._write_from_workflow(
            {"rt_claim_expires_at": fields.Datetime.now() - timedelta(seconds=1)}
        )
        self.env["codestra.crm.call.followup"]._cron_rt_expire_claims()
        followup.invalidate_recordset()
        self.assertFalse(followup.rt_claim_token)

        recovered = self.env(user=self.agent)[
            "codestra.crm.call.followup.realtime.api"
        ].recover_v1("browser-two", limit=10)
        self.assertIn(followup.id, [item["followup_id"] for item in recovered["items"]])
