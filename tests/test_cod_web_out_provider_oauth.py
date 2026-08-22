import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from control_plane_service import providers
from control_plane_service.providers import ProviderError, submit


class Response:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.value).encode()


class CodWebOutProviderOAuthTests(unittest.TestCase):
    def setUp(self):
        providers._token_cache = None
        self.temp = tempfile.TemporaryDirectory()
        for name in ("secret", "ca", "cert", "key"):
            with open(os.path.join(self.temp.name, name), "w", encoding="utf-8") as handle:
                handle.write("test-value")
        self.env = patch.dict(os.environ, {
            "KLYROW_MODE": "production",
            "CONTROL_PLANE_PRODUCTION_DELIVERY_AUTHORIZED": "true",
            "KLYROW_URL": "https://10.40.0.4:18000/v1/email/send",
            "KLYROW_ALLOWED_CAMPAIGN": "COD-WEB-OUT",
            "KLYROW_OIDC_TOKEN_URL": "https://auth.codestra.co/realms/codestra/protocol/openid-connect/token",
            "KLYROW_OIDC_CLIENT_ID": "cod-web-out-email-production",
            "KLYROW_OIDC_CLIENT_SECRET_FILE": os.path.join(self.temp.name, "secret"),
            "KLYROW_MTLS_CA_FILE": os.path.join(self.temp.name, "ca"),
            "KLYROW_MTLS_CERT_FILE": os.path.join(self.temp.name, "cert"),
            "KLYROW_MTLS_KEY_FILE": os.path.join(self.temp.name, "key"),
        }, clear=False)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    @staticmethod
    def message(campaign="COD-WEB-OUT"):
        return {
            "provider": "klyrow", "message_id": "message-1", "tenant_id": "COD",
            "customer_id": "synthetic", "correlation_id": "correlation-1",
            "idempotency_key": "key-1", "sender": "sales@codestra.co",
            "normalized_destination": "appolon@codestra.co", "classification": "transactional",
            "campaign_id": campaign,
            "content_payload": json.dumps({"subject":"Synthetic","html":"<p>Synthetic</p>",
                                            "text":"Synthetic","reply_to":"support@codestra.co"}),
        }

    @patch("control_plane_service.providers.ssl.create_default_context")
    @patch("control_plane_service.providers.urllib.request.urlopen")
    def test_scoped_oauth_mtls_submission(self, urlopen, create_context):
        context = MagicMock()
        create_context.return_value = context
        urlopen.side_effect = [Response({"access_token":"token","expires_in":60}),
                               Response({"id":"provider-1","status":"queued"})]
        result = submit(self.message())
        self.assertEqual(result.provider_message_id, "provider-1")
        provider_request = urlopen.call_args_list[1].args[0]
        self.assertEqual(provider_request.headers["Authorization"], "Bearer token")
        self.assertEqual(provider_request.headers["X-codestra-campaign"], "COD-WEB-OUT")
        self.assertIs(urlopen.call_args_list[1].kwargs["context"], context)
        payload = json.loads(provider_request.data)
        self.assertEqual(payload["sender"], "sales@codestra.co")
        self.assertEqual(payload["reply_to"], "support@codestra.co")
        self.assertEqual(payload["campaign_id"], "COD-WEB-OUT")

    def test_other_campaign_is_denied_before_network(self):
        with patch("control_plane_service.providers.urllib.request.urlopen") as urlopen:
            with self.assertRaisesRegex(ProviderError, "campaign_not_authorized"):
                submit(self.message("COD-TEST-OUT"))
            urlopen.assert_not_called()

    def test_static_api_key_cannot_replace_oidc_secret_file(self):
        os.environ.pop("KLYROW_OIDC_CLIENT_SECRET_FILE")
        os.environ["KLYROW_OUTBOUND_API_KEY"] = "legacy"
        with self.assertRaisesRegex(ProviderError, "credentials_missing"):
            submit(self.message())
