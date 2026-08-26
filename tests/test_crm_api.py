import os
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

from control_plane_service.core import ControlPlaneError, Store
from control_plane_service.crm import CrmService, OdooCrmClient, request_hash


class CrmApiTests(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp(); os.close(handle)
        self.store = Store(self.path)
        self.store.crm_register_customer("customer-a", "consumer-a", "custom-a", True, "Company A", "Unit A")
        self.store.crm_register_customer("customer-b", "consumer-b", "custom-b", True, "Company B", "Unit B")
        self.store.crm_register_customer("disabled", "consumer-disabled", "custom-disabled", False, "Disabled", "Disabled")

    def tearDown(self):
        for suffix in ("", "-wal", "-shm"):
            try: os.unlink(self.path + suffix)
            except FileNotFoundError: pass

    def test_customer_identity_and_disabled_customer(self):
        self.assertEqual(self.store.crm_customer("consumer-a", "custom-a")["customer_id"], "customer-a")
        with self.assertRaisesRegex(ControlPlaneError, "crm_customer_unknown"):
            self.store.crm_customer("consumer-a", "wrong")
        with self.assertRaisesRegex(ControlPlaneError, "crm_customer_disabled"):
            self.store.crm_customer("consumer-disabled", "custom-disabled")

    def test_mapping_is_tenant_scoped(self):
        self.store.crm_save_object("customer-a", "lead-1", "middleware-1", "crm.lead")
        self.assertEqual(self.store.crm_object("customer-a", "lead-1")["middleware_id"], "middleware-1")
        with self.assertRaisesRegex(ControlPlaneError, "crm_object_not_found"):
            self.store.crm_object("customer-b", "lead-1")

    def test_idempotency_returns_original_and_rejects_conflict(self):
        payload = {"name": "Synthetic", "customer_reference": "lead-1"}; digest = request_hash(payload)
        self.store.crm_save_idempotency("customer-a", "lead.create", "key-1", digest, {"external_id": "lead-1"}, 201)
        result = self.store.crm_idempotency("customer-a", "lead.create", "key-1", digest)
        self.assertEqual(result, ({"external_id": "lead-1"}, 201))
        with self.assertRaisesRegex(ControlPlaneError, "idempotency_conflict"):
            self.store.crm_idempotency("customer-a", "lead.create", "key-1", request_hash({"name": "Changed"}))

    def test_allowlists_reject_privileged_fields(self):
        with self.assertRaisesRegex(ControlPlaneError, "unsupported_fields:company_id"):
            CrmService.validate_fields({"name": "Synthetic", "company_id": 1}, {"name"})

    def test_odoo_outage_is_controlled(self):
        old = {key: os.environ.get(key) for key in ("CRM_ODOO_URL", "CRM_ODOO_HMAC_SECRET")}
        os.environ["CRM_ODOO_URL"] = "http://odoo.invalid"
        os.environ["CRM_ODOO_HMAC_SECRET"] = "synthetic-secret"
        try:
            with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("synthetic outage")):
                with self.assertRaisesRegex(ControlPlaneError, "odoo_unavailable"):
                    OdooCrmClient().request("POST", "/leads", {"name": "Synthetic"}, "customer-a", "corr", "idem", retries=1)
        finally:
            for key, value in old.items():
                if value is None: os.environ.pop(key, None)
                else: os.environ[key] = value


if __name__ == "__main__": unittest.main()
