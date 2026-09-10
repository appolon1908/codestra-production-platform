from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError
from odoo.fields import Command
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCodestraCrmCallFollowupRealtimeLease(TransactionCase):
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
                "name": "Lease Test Agent",
                "login": "lease-agent@test.invalid",
                "email": "lease-agent@test.invalid",
                "company_id": cls.company.id,
                "company_ids": [Command.set([cls.company.id])],
                "group_ids": [Command.set([base_user.id, agent_group.id])],
            }
        )
        cls.other_agent = cls.env["res.users"].with_context(
            no_reset_password=True
        ).create(
            {
                "name": "Other Lease Agent",
                "login": "other-lease-agent@test.invalid",
                "email": "other-lease-agent@test.invalid",
                "company_id": cls.company.id,
                "company_ids": [Command.set([cls.company.id])],
                "group_ids": [Command.set([base_user.id, agent_group.id])],
            }
        )
        cls.service_user = cls.env["res.users"].with_context(
            no_reset_password=True
        ).create(
            {
                "name": "Lease Integration Service",
                "login": "lease-service@test.invalid",
                "email": "lease-service@test.invalid",
                "company_id": cls.company.id,
                "company_ids": [Command.set([cls.company.id])],
                "group_ids": [Command.set([base_user.id, service_group.id])],
            }
        )
        cls.customer = cls.env["res.partner"].create(
            {"name": "Lease Customer", "email": "lease-customer@test.invalid"}
        )
        cls.lead = cls.env["crm.lead"].create(
            {
                "name": "Lease Opportunity",
                "type": "opportunity",
                "company_id": cls.company.id,
                "user_id": cls.agent.id,
                "partner_id": cls.customer.id,
            }
        )

    def _register(self, event_id):
        ended_at = fields.Datetime.now()
        payload = {
            "api_version": "1.0",
            "event_id": event_id,
            "company_id": self.company.id,
            "agent_user_id": self.agent.id,
            "lead_id": self.lead.id,
            "partner_id": self.customer.id,
            "started_at": fields.Datetime.to_string(
                ended_at - timedelta(minutes=2)
            ),
            "ended_at": fields.Datetime.to_string(ended_at),
            "duration_seconds": 120,
            "call_direction": "outbound",
        }
        return self.env(user=self.service_user)[
            "codestra.crm.call.followup.api"
        ].register_completed_call(payload)

    def _agent_model(self, user=None):
        return self.env(user=user or self.agent)[
            "codestra.crm.call.followup"
        ]

    def test_one_tab_claims_one_pending_action(self):
        registration = self._register("lease-one-tab")
        claimed = self._agent_model().claim_pending_post_call_actions(
            "tab-a", limit=1
        )

        self.assertEqual(len(claimed), 1)
        self.assertEqual(claimed[0]["followup_id"], registration["followup_id"])
        self.assertTrue(claimed[0]["lease_token"])
        followup = self._agent_model().browse(registration["followup_id"])
        self.assertEqual(followup.popup_lease_owner, "tab-a")
        self.assertTrue(followup.popup_lease_expires_at)

    def test_second_tab_cannot_claim_active_lease(self):
        self._register("lease-two-tabs")
        first = self._agent_model().claim_pending_post_call_actions(
            "tab-a", limit=1
        )
        second = self._agent_model().claim_pending_post_call_actions(
            "tab-b", limit=1
        )

        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])

    def test_release_makes_action_claimable(self):
        self._register("lease-release")
        first = self._agent_model().claim_pending_post_call_actions(
            "tab-a", limit=1
        )[0]
        followup = self._agent_model().browse(first["followup_id"])
        self.assertTrue(
            followup.release_popup_lease("tab-a", first["lease_token"])
        )

        second = self._agent_model().claim_pending_post_call_actions(
            "tab-b", limit=1
        )
        self.assertEqual(len(second), 1)
        self.assertEqual(second[0]["followup_id"], first["followup_id"])
        self.assertNotEqual(second[0]["lease_token"], first["lease_token"])

    def test_expired_lease_is_reclaimed(self):
        registration = self._register("lease-expiry")
        first = self._agent_model().claim_pending_post_call_actions(
            "tab-a", limit=1
        )[0]
        followup = self.env["codestra.crm.call.followup"].sudo().browse(
            registration["followup_id"]
        )
        followup._write_from_workflow(
            {
                "popup_lease_expires_at": (
                    fields.Datetime.now() - timedelta(seconds=1)
                )
            }
        )

        second = self._agent_model().claim_pending_post_call_actions(
            "tab-b", limit=1
        )[0]
        self.assertEqual(second["followup_id"], first["followup_id"])
        self.assertNotEqual(second["lease_token"], first["lease_token"])
        self.assertEqual(followup.popup_lease_owner, "tab-b")

    def test_renew_extends_owned_lease(self):
        registration = self._register("lease-renew")
        claim = self._agent_model().claim_pending_post_call_actions(
            "tab-a", limit=1
        )[0]
        followup = self._agent_model().browse(registration["followup_id"])
        original_expiry = followup.popup_lease_expires_at
        result = followup.renew_popup_lease("tab-a", claim["lease_token"])

        followup.invalidate_recordset()
        self.assertEqual(result["lease_token"], claim["lease_token"])
        self.assertGreaterEqual(followup.popup_lease_expires_at, original_expiry)

    def test_other_agent_cannot_release_assigned_lease(self):
        registration = self._register("lease-access")
        claim = self._agent_model().claim_pending_post_call_actions(
            "tab-a", limit=1
        )[0]
        other_followup = self._agent_model(self.other_agent).browse(
            registration["followup_id"]
        )

        with self.assertRaises(AccessError):
            other_followup.release_popup_lease(
                "tab-a", claim["lease_token"]
            )

    def test_completion_and_snooze_clear_lease(self):
        registration = self._register("lease-cleanup")
        claim = self._agent_model().claim_pending_post_call_actions(
            "tab-a", limit=1
        )[0]
        followup = self.env["codestra.crm.call.followup"].sudo().browse(
            registration["followup_id"]
        )
        self.assertEqual(followup.popup_lease_token, claim["lease_token"])

        followup._write_from_workflow(
            {"snoozed_until": fields.Datetime.now() + timedelta(minutes=10)}
        )
        self.assertFalse(followup.popup_lease_token)
        self.assertFalse(followup.popup_lease_owner)
        self.assertFalse(followup.popup_lease_expires_at)
