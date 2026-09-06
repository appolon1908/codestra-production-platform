from odoo.exceptions import ValidationError

from .test_call_followup_api import TestCodestraCrmCallFollowupApi


class TestCodestraCrmCallFollowupApiHardening(
    TestCodestraCrmCallFollowupApi
):
    def test_v1_rejects_unsupported_api_version(self):
        payload = self._payload("unsupported-version")
        payload["api_version"] = "2.0"

        with self.assertRaisesRegex(
            ValidationError,
            "Unsupported completed-call API version",
        ):
            self._api().validate_completed_call_v1(payload)

    def test_v1_rejects_payload_larger_than_64_kib(self):
        payload = self._payload("oversized-payload")
        payload["padding"] = "x" * 65_536

        with self.assertRaisesRegex(ValidationError, "65,536 bytes"):
            self._api().validate_completed_call_v1(payload)

    def test_v1_rejects_invalid_customer_email(self):
        payload = self._payload("invalid-customer-email")
        payload["customer_email"] = "not-an-email"

        with self.assertRaisesRegex(
            ValidationError,
            "one valid email address",
        ):
            self._api().validate_completed_call_v1(payload)

    def test_capabilities_publish_enforced_limits(self):
        capabilities = self._api().get_integration_capabilities()

        self.assertEqual(
            capabilities["supported_api_versions"],
            ["1.0"],
        )
        self.assertEqual(
            capabilities["limits"]["max_payload_bytes"],
            65_536,
        )
        self.assertEqual(
            capabilities["limits"]["max_customer_email_length"],
            320,
        )
