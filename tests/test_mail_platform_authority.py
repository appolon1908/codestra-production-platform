import unittest

from mail_platform.registry import MailRegistry, PolicyError


class MailPlatformAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.registry = MailRegistry()
        self.registry.migrate()
        self.registry.register_domain(
            domain="example.test", brand="Codestra", domain_type="AGENT_CAMPAIGN",
            campaign_id="campaign-a", active=True, assignment_status="ASSIGNED",
            allow_agent_send=True, allow_agent_receive=True, allow_shared_mailboxes=True,
        )
        self.alice = self.registry.create_user(
            keycloak_subject="alice", display_name="Alice", primary_address="alice@example.test",
            user_type="ODOO_LINKED", role="SUPERVISOR", quota=100, odoo_user_id=1,
            campaign_id="campaign-a",
        )["mail_user_uuid"]
        self.bob = self.registry.create_user(
            keycloak_subject="bob", display_name="Bob", primary_address="bob@example.test",
            user_type="ODOO_LINKED", role="AGENT", quota=100, odoo_user_id=2,
            campaign_id="campaign-a",
        )["mail_user_uuid"]

    def message(self, **changes):
        values = dict(tenant="tenant-a", direction="OUTBOUND", sender="alice@example.test",
                      recipients=["outside@example.net"], correlation_id="correlation-1",
                      idempotency_key="idempotency-1", actor_uuid=self.alice)  # gitleaks:allow test fixture
        values.update(changes)
        return self.registry.register_message(**values)

    def test_sender_requires_active_non_blocked_domain(self):
        self.registry.db.execute("UPDATE mail_domain SET active=0 WHERE domain='example.test'")
        with self.assertRaisesRegex(PolicyError, "sender_domain_denied"):
            self.message()

    def test_inbound_requires_exact_active_mailbox(self):
        route = self.registry.route_inbound("alice@example.test")
        self.assertEqual(self.alice, route["mailbox_uuid"])
        with self.assertRaisesRegex(PolicyError, "inbound_recipient_not_found"):
            self.registry.route_inbound("unknown@example.test")

    def test_idempotency_replay_rejects_changed_payload(self):
        first = self.message()
        self.assertTrue(self.message()["duplicate"])
        with self.assertRaisesRegex(PolicyError, "idempotency_conflict"):
            self.message(recipients=["different@example.net"])
        self.assertFalse(first["duplicate"])

    def test_personal_messages_are_not_campaign_wide(self):
        message = self.message()
        self.assertEqual([message["message_uuid"]], [row["message_uuid"] for row in
                         self.registry.messages_for_user(tenant="tenant-a", mail_user_uuid=self.alice)])
        self.assertEqual([], self.registry.messages_for_user(tenant="tenant-a", mail_user_uuid=self.bob))

    def test_shared_mailbox_requires_membership(self):
        mailbox = self.registry.create_shared_mailbox(
            actor_uuid=self.alice, address="team@example.test", campaign_id="campaign-a",
            supervisor_uuid=self.alice, members=[(self.bob, "READ")],
        )
        message = self.registry.register_message(
            tenant="tenant-a", direction="INBOUND", sender="outside@example.net",
            recipients=["team@example.test"], correlation_id="correlation-2",
            idempotency_key="idempotency-2",  # gitleaks:allow test fixture
        )
        self.assertEqual(mailbox, message["mailbox_uuid"])
        self.assertEqual(1, len(self.registry.messages_for_user(tenant="tenant-a", mail_user_uuid=self.bob)))


if __name__ == "__main__":
    unittest.main()
