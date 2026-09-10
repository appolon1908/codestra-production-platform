import importlib.util
import json
import time
import unittest
from pathlib import Path

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "webphone_auth_preflight", ROOT / "scripts/webphone_auth_preflight.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class Response:
    def __init__(self, status, body):
        self.status_code = status
        self.body = body

    def json(self):
        return self.body


class FakeHTTP:
    def __init__(self, token, jwks, rejected=False, backend=422, degraded=None):
        self.token, self.jwks = token, jwks
        self.rejected, self.backend = rejected, backend
        self.degraded = [] if degraded is None else degraded
        self.requests = []

    def post(self, url, **kwargs):
        self.requests.append(("POST", url))
        assert url == probe.TOKEN_URL
        if self.rejected:
            return Response(401, {"error": "invalid_client", "sensitive": "never-print"})
        return Response(200, {"access_token": self.token})

    def get(self, url, headers=None):
        self.requests.append(("GET", url))
        if url == probe.JWKS_URL:
            return Response(200, self.jwks)
        if "/admin/realms/codestra/users/" in url:
            return Response(404, {"error": "User not found"})
        if "/v1/provisioning/requests/" in url:
            if not headers:
                return Response(401, {"detail": "authentication_required"})
            return Response(self.backend, {
                "detail": [{"loc": ["body"], "type": "missing", "msg": "Field required"}]})
        if url == probe.PROVISIONING_URL + "/ready":
            return Response(200, {"status": "ready", "environment": "production",
                                  "degraded_capabilities": self.degraded})
        raise AssertionError(url)


class WebphoneAuthPreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.key.public_key()))
        jwk.update(kid="fixture", alg="RS256", use="sig")
        cls.jwks = {"keys": [jwk]}

    def claims(self):
        now = int(time.time())
        return {"iss": probe.ISSUER, "sub": "synthetic-service-account",
                "aud": probe.CLIENT_ID, "azp": probe.CLIENT_ID,
                "iat": now, "exp": now + 300, "jti": "synthetic-one-use",
                "typ": "Bearer", "codestra_scopes": " ".join(sorted(probe.SCOPES)),
                "resource_access": {"realm-management": {"roles": ["view-users"]}}}

    def token(self, claims=None, key=None, kid="fixture"):
        return jwt.encode(self.claims() if claims is None else claims,
                          self.key if key is None else key, algorithm="RS256",
                          headers={"kid": kid})

    def run_probe(self, http):
        return probe.run_preflight(http, probe.CLIENT_ID, "synthetic-value",
                                   probe.TOKEN_URL, probe.PROVISIONING_URL)

    def test_authentication_pass_does_not_claim_a_call(self):
        http = FakeHTTP(self.token(), self.jwks)
        result = self.run_probe(http)
        self.assertEqual(result["machine_authentication"], "pass")
        self.assertEqual(result["call_readiness"], "not_tested")
        self.assertEqual(result["calls_placed"], 0)
        self.assertEqual(result["sessions_created"], 0)
        self.assertEqual([url for method, url in http.requests if method == "POST"],
                         [probe.TOKEN_URL])
        self.assertFalse(any(url.endswith(("/session", "/execute", "/renew"))
                             for _, url in http.requests))

    def test_disabled_capabilities_remain_visible(self):
        result = self.run_probe(FakeHTTP(self.token(), self.jwks, degraded=["sip", "vicidial"]))
        self.assertEqual(result["machine_authentication"], "pass")
        self.assertEqual(result["call_readiness"], "blocked")
        self.assertEqual(result["degraded_capabilities"], ["sip", "vicidial"])

    def test_rejected_client_never_calls_backend_or_leaks_body(self):
        http = FakeHTTP(self.token(), self.jwks, rejected=True)
        with self.assertRaises(probe.PreflightFailure) as caught:
            self.run_probe(http)
        self.assertEqual(caught.exception.reason, "client_authentication_rejected")
        self.assertEqual(caught.exception.http_status, 401)
        self.assertNotIn("never-print", str(caught.exception))
        self.assertEqual(len(http.requests), 1)

    def test_staging_and_wrong_urls_are_rejected_before_network(self):
        for client, token_url, backend in [
            ("codestra-provisioning-service-staging", probe.TOKEN_URL, probe.PROVISIONING_URL),
            (probe.CLIENT_ID, "https://auth-staging.codestra.co/token", probe.PROVISIONING_URL),
            (probe.CLIENT_ID, probe.TOKEN_URL, "https://provisioning-service:8443"),
            (probe.CLIENT_ID, "http://auth.codestra.co/token", probe.PROVISIONING_URL),
        ]:
            http = FakeHTTP(self.token(), self.jwks)
            with self.assertRaises(probe.PreflightFailure):
                probe.run_preflight(http, client, "synthetic-value", token_url, backend)
            self.assertEqual(http.requests, [])

    def test_signature_and_unknown_key_are_rejected(self):
        for token in [self.token(key=self.other_key), self.token(kid="unknown")]:
            with self.assertRaises(probe.PreflightFailure):
                probe.validate_token(token, self.jwks)

    def test_unsigned_token_is_rejected(self):
        with self.assertRaises(probe.PreflightFailure):
            probe.validate_token(jwt.encode(self.claims(), key="", algorithm="none"),
                                 self.jwks)

    def test_expired_future_and_long_lived_tokens_are_rejected(self):
        now = int(time.time())
        for times in [{"iat": now - 400, "exp": now - 100},
                      {"iat": now + 60, "exp": now + 360},
                      {"iat": now, "exp": now + 301}]:
            claims = self.claims()
            claims.update(times)
            with self.assertRaises(probe.PreflightFailure):
                probe.validate_token(self.token(claims), self.jwks)

    def test_wrong_issuer_audience_client_and_scopes_are_rejected(self):
        for key, value in [
            ("iss", "https://auth-staging.codestra.co/realms/codestra"),
            ("aud", "middleware-api"), ("aud", [probe.CLIENT_ID, "another-service"]),
            ("azp", "codestra-provisioning-service-staging"),
            ("codestra_scopes", "provisioning:read"),
            ("codestra_scopes", " ".join(sorted(probe.SCOPES)) + " admin"),
        ]:
            claims = self.claims()
            claims[key] = value
            with self.assertRaises(probe.PreflightFailure):
                probe.validate_token(self.token(claims), self.jwks)

    def test_missing_jti_and_admin_privileges_are_rejected(self):
        for mutation in ["missing_jti", "no_read_role", "manage_users", "realm_admin"]:
            claims = self.claims()
            if mutation == "missing_jti":
                del claims["jti"]
            elif mutation == "no_read_role":
                claims["resource_access"] = {}
            elif mutation == "manage_users":
                claims["resource_access"]["realm-management"]["roles"].append("manage-users")
            else:
                claims["realm_access"] = {"roles": ["realm-admin"]}
            with self.assertRaises(probe.PreflightFailure):
                probe.validate_token(self.token(claims), self.jwks)

    def test_failed_backend_validation_is_not_a_pass(self):
        for status in [200, 401, 403, 404, 409, 500]:
            with self.assertRaises(probe.PreflightFailure):
                self.run_probe(FakeHTTP(self.token(), self.jwks, backend=status))
