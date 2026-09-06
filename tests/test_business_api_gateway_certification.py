from __future__ import annotations

import copy
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "validate_business_api_gateway_certification.py"
spec = importlib.util.spec_from_file_location("business_api_certification", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def policy() -> dict:
    return {
        "schema_version": 1,
        "expected_business_applications": 15,
        "expected_kong_routes": 29,
        "required_endpoint_classes": ["health", "readiness", "version", "capabilities", "openapi"],
        "allowed_methods": ["GET", "HEAD"],
        "allowed_protected_statuses": [200, 204, 302, 400, 401, 403, 405, 415, 422, 429],
    }


def endpoint(path: str) -> dict:
    return {
        "method": "GET",
        "path": path,
        "status_code": 200,
        "route_exists": True,
        "tls_verified": True,
        "elapsed_ms": 15,
        "response_size_bytes": 128,
        "response_body_sha256": "a" * 64,
        "sensitive_data_detected": False,
        "request_body_sent": False,
    }


def route(index: int) -> dict:
    return {
        "name": f"route-{index:02d}",
        "application": f"business-{index % 15:02d}",
        "method": "GET" if index % 2 == 0 else "HEAD",
        "path": f"/read-only/{index:02d}",
        "status_code": 200,
        "route_exists": True,
        "tls_verified": True,
        "authentication_boundary": "PASS",
        "source_match": True,
        "digest_match": True,
        "elapsed_ms": 20,
        "latency_limit_ms": 1000,
        "write_effect_observed": False,
        "evidence_ref": f"evidence:gateway/route-{index:02d}",
    }


def application(index: int, route_names: list[str]) -> dict:
    marker = f"{index % 16:x}"
    openapi_hash = f"{(index + 1) % 16:x}" * 64
    return {
        "application": f"business-{index:02d}",
        "repository": f"example/business-{index:02d}",
        "expected_source_sha": marker * 40,
        "expected_image_digest": "sha256:" + marker * 64,
        "base_url": f"https://business-{index:02d}.staging.example.invalid",
        "max_latency_ms": 1000,
        "endpoint_results": {
            "health": endpoint("/health"),
            "readiness": endpoint("/ready"),
            "version": endpoint("/version"),
            "capabilities": endpoint("/capabilities"),
            "openapi": endpoint("/openapi.json"),
        },
        "authorization": {
            "authenticated_positive": "PASS",
            "unauthenticated_negative": "PASS",
            "wrong_role_negative": "PASS",
            "wrong_business_negative": "PASS",
            "cross_business_leaks": 0,
        },
        "runtime_identity": {
            "source_sha_readback": marker * 40,
            "image_digest_readback": "sha256:" + marker * 64,
        },
        "openapi_alignment": {
            "status": "PASS",
            "source_sha256": openapi_hash,
            "runtime_sha256": openapi_hash,
            "source_path_count": 10,
            "runtime_path_count": 10,
        },
        "gateway_alignment": {
            "status": "PASS",
            "route_names": route_names,
        },
        "evidence_ref": f"evidence:application/business-{index:02d}",
    }


def evidence() -> dict:
    routes = [route(index) for index in range(29)]
    by_application = {f"business-{index:02d}": [] for index in range(15)}
    for item in routes:
        by_application[item["application"]].append(item["name"])
    return {
        "schema_version": 1,
        "candidate": {
            "release_id": "codestra-candidate-20260903",
            "platform_source_sha": "f" * 40,
            "endpoint_manifest_sha256": "e" * 64,
        },
        "applications": [
            application(index, by_application[f"business-{index:02d}"])
            for index in range(15)
        ],
        "kong_routes": routes,
        "summary": {
            "unexpected_404": 0,
            "unexpected_5xx": 0,
            "cross_business_leaks": 0,
            "calls_delta": 0,
            "emails_delta": 0,
            "sms_delta": 0,
            "provider_effects_delta": 0,
            "business_writes_delta": 0,
            "secrets_in_responses": 0,
            "secrets_in_logs": 0,
        },
        "safety": {
            "business_writes": False,
            "communications_delivery": False,
            "provider_effects": False,
            "financial_or_trading_mutation": False,
        },
    }


class BusinessApiGatewayCertificationTests(unittest.TestCase):
    def test_complete_15_by_29_evidence_passes(self) -> None:
        result = module.validate(evidence(), policy())
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["business_apis"], "15/15")
        self.assertEqual(result["gateway_routes"], "29/29")

    def test_exactly_fifteen_applications_required(self) -> None:
        value = evidence()
        value["applications"].pop()
        with self.assertRaisesRegex(module.CertificationError, "exactly 15"):
            module.validate(value, policy())

    def test_exactly_twenty_nine_routes_required(self) -> None:
        value = evidence()
        value["kong_routes"].pop()
        with self.assertRaisesRegex(module.CertificationError, "exactly 29"):
            module.validate(value, policy())

    def test_404_is_rejected(self) -> None:
        value = evidence()
        value["applications"][0]["endpoint_results"]["health"]["status_code"] = 404
        with self.assertRaisesRegex(module.CertificationError, "allowed protected result"):
            module.validate(value, policy())

    def test_5xx_is_rejected(self) -> None:
        value = evidence()
        value["kong_routes"][0]["status_code"] = 503
        with self.assertRaisesRegex(module.CertificationError, "allowed protected result"):
            module.validate(value, policy())

    def test_tls_must_be_verified(self) -> None:
        value = evidence()
        value["applications"][0]["endpoint_results"]["readiness"]["tls_verified"] = False
        with self.assertRaisesRegex(module.CertificationError, "tls_verified must be true"):
            module.validate(value, policy())

    def test_wrong_business_denial_is_required(self) -> None:
        value = evidence()
        value["applications"][0]["authorization"]["wrong_business_negative"] = "FAIL"
        with self.assertRaisesRegex(module.CertificationError, "must be PASS"):
            module.validate(value, policy())

    def test_runtime_source_readback_must_match(self) -> None:
        value = evidence()
        value["applications"][0]["runtime_identity"]["source_sha_readback"] = "b" * 40
        with self.assertRaisesRegex(module.CertificationError, "source SHA does not match"):
            module.validate(value, policy())

    def test_runtime_digest_readback_must_match(self) -> None:
        value = evidence()
        value["applications"][0]["runtime_identity"]["image_digest_readback"] = "sha256:" + "b" * 64
        with self.assertRaisesRegex(module.CertificationError, "image digest does not match"):
            module.validate(value, policy())

    def test_openapi_hashes_must_match(self) -> None:
        value = evidence()
        value["applications"][0]["openapi_alignment"]["runtime_sha256"] = "c" * 64
        with self.assertRaisesRegex(module.CertificationError, "OpenAPI hashes differ"):
            module.validate(value, policy())

    def test_every_gateway_route_must_be_mapped(self) -> None:
        value = evidence()
        value["applications"][0]["gateway_alignment"]["route_names"].remove("route-00")
        with self.assertRaisesRegex(module.CertificationError, "route coverage mismatch"):
            module.validate(value, policy())

    def test_live_effect_delta_must_be_zero(self) -> None:
        value = evidence()
        value["summary"]["calls_delta"] = 1
        with self.assertRaisesRegex(module.CertificationError, "must be zero"):
            module.validate(value, policy())

    def test_request_body_is_forbidden(self) -> None:
        value = evidence()
        value["applications"][0]["endpoint_results"]["openapi"]["request_body_sent"] = True
        with self.assertRaisesRegex(module.CertificationError, "request_body_sent must be false"):
            module.validate(value, policy())

    def test_secret_value_field_is_rejected(self) -> None:
        value = evidence()
        value["applications"][0]["authorization"]["access_token"] = "not-a-real-token"
        with self.assertRaisesRegex(module.CertificationError, "secret value field"):
            module.validate(value, policy())


if __name__ == "__main__":
    unittest.main()
