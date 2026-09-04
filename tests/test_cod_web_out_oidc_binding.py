from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "deploy/kong-production-standby/identity-registry/002_cod_web_out_klyrow_binding.sql"
KEYCLOAK = ROOT / "deploy/keycloak/cod-web-out-email-production.json"


class CodWebOutOidcBindingContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sql = MIGRATION.read_text(encoding="utf-8")
        cls.keycloak = json.loads(KEYCLOAK.read_text(encoding="utf-8"))

    def test_migration_uses_exact_canonical_identity_and_tenant(self) -> None:
        self.assertIn(
            "canonical_issuer CONSTANT text := 'https://auth.codestra.co/realms/codestra'",
            self.sql,
        )
        self.assertIn(
            "canonical_client_id CONSTANT text := 'cod-web-out-email-production'",
            self.sql,
        )
        self.assertIn("canonical_tenant_key CONSTANT text := 'COD'", self.sql)
        self.assertIn(
            "current_setting('codestra.cod_web_out_subject', true)", self.sql
        )

    def test_resolver_permissions_are_exact_and_least_privilege(self) -> None:
        match = re.search(
            r"canonical_scopes CONSTANT text\[\] := ARRAY\[(.*?)\]::text\[\];",
            self.sql,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(match)
        scopes = set(re.findall(r"'([^']+)'", match.group(1)))
        self.assertEqual(scopes, {"klyrow.send", "klyrow.read", "email.status"})
        self.assertFalse(any("*" in scope for scope in scopes))
        self.assertFalse(any("admin" in scope for scope in scopes))

    def test_reconciliation_is_idempotent_and_preserves_row_identity(self) -> None:
        self.assertIn("ON CONFLICT (issuer, subject) DO UPDATE", self.sql)
        self.assertIn("LOCK TABLE oidc_tenant_registry", self.sql)
        self.assertNotIn("DELETE FROM OIDC_TENANT_REGISTRY", self.sql.upper())
        self.assertNotIn("TRUNCATE ", self.sql.upper())

    def test_conflicting_subject_client_or_tenant_fails_closed(self) -> None:
        self.assertIn("cod_web_out_identity_conflict", self.sql)
        self.assertIn("cod_web_out_identity_not_unique", self.sql)
        self.assertIn("cod_web_out_identity_readback_failed", self.sql)
        self.assertIn("issuer IS DISTINCT FROM canonical_issuer", self.sql)
        self.assertIn("subject IS DISTINCT FROM service_subject", self.sql)
        self.assertIn("tenant_key IS DISTINCT FROM canonical_tenant_key", self.sql)

    def test_no_real_service_subject_is_committed(self) -> None:
        # UUID-shaped literals in the migration would be an accidental real
        # subject or a misleading placeholder. The subject must come from the
        # protected database session only.
        uuid_literal = re.compile(
            r"['\"]?[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
            r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}['\"]?"
        )
        without_regex_definition = "\n".join(
            line for line in self.sql.splitlines() if "service_subject !~*" not in line
        )
        self.assertIsNone(uuid_literal.search(without_regex_definition))

    def test_keycloak_client_remains_service_only_and_canonical(self) -> None:
        item = self.keycloak
        self.assertEqual(item["issuer"], "https://auth.codestra.co/realms/codestra")
        self.assertEqual(item["clientId"], "cod-web-out-email-production")
        self.assertTrue(item["serviceAccountsEnabled"])
        self.assertFalse(item["publicClient"])
        self.assertFalse(item["standardFlowEnabled"])
        self.assertFalse(item["directAccessGrantsEnabled"])
        self.assertFalse(item["fullScopeAllowed"])
        self.assertEqual(
            item["tenantClaim"],
            {"name": "tenant_id", "value": "COD", "source": "server"},
        )
        self.assertLessEqual(item["accessTokenLifespanSeconds"], 300)

    def test_repository_contains_only_a_secret_file_reference(self) -> None:
        self.assertEqual(
            self.keycloak["secretFile"],
            "/etc/codestra/secrets/cod-web-out-email/klyrow-oidc-client-secret",
        )
        self.assertNotIn(
            "secret", {key.lower() for key in self.keycloak if key != "secretFile"}
        )


if __name__ == "__main__":
    unittest.main()
